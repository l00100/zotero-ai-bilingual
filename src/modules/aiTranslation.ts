import { getPref, setPref } from "../utils/prefs";
import { SplitViewFactory } from "./splitView";
import {
  AIConfig,
  AIJob,
  cacheSignature,
  isPDFBytes,
  normalizeAIConfig,
  parseAIJob,
} from "./aiCore";

interface PendingJob {
  sourceID: number;
  signature: string;
  jobID: string;
}
type Report = (text: string, progress: number) => void;

/** AI translation is manual only: selecting the AI menu explicitly starts a job. */
export class AITranslationFactory {
  private static readonly origin = "chrome://hjfy-ai-reader";
  private static readonly realm = "OpenAI-compatible API";
  private static readonly base = "http://127.0.0.1:8891";
  private static readonly running = new Map<number, string>();
  private static readonly claimed = new Set<number>();

  static registerItemMenu(win: _ZoteroTypes.MainWindow) {
    const menu = win.document.getElementById("zotero-itemmenu");
    if (!menu) return;
    for (const [id, label, action] of [
      [
        "ai-open-existing",
        "打开已有译文并分屏阅读（不翻译）",
        () => this.handleOpenExisting(win),
      ],
      [
        "ai-translate",
        "AI 翻译 PDF 并分屏打开…",
        () => this.handleCommand(win),
      ],
      ["ai-cancel", "取消所有 AI 翻译任务", () => this.cancelJobs()],
    ] as const) {
      if (win.document.getElementById(id)) continue;
      ztoolkit.UI.appendElement(
        {
          tag: "menuitem",
          id,
          namespace: "xul",
          attributes: { label },
          listeners: [
            {
              type: "command",
              listener: () => {
                void action();
              },
            },
          ],
        },
        menu,
      );
    }
  }

  static unregisterMenus(win?: Window) {
    const windows = win ? [win] : Zotero.getMainWindows();
    for (const w of windows) {
      w.document.getElementById("ai-open-existing")?.remove();
      w.document.getElementById("ai-translate")?.remove();
      w.document.getElementById("ai-cancel")?.remove();
    }
  }

  static async savedKey(): Promise<string> {
    await Services.logins.initializationPromise;
    return (
      Services.logins.findLogins(this.origin, "", this.realm)[0]?.password || ""
    );
  }

  static async saveKey(key: string) {
    await Services.logins.initializationPromise;
    const existing = Services.logins.findLogins(this.origin, "", this.realm)[0];
    const value = key.trim();
    if (!value) throw new Error("密钥为空，未更改已保存的密钥");
    const login = (Components.classes as any)[
      "@mozilla.org/login-manager/loginInfo;1"
    ].createInstance(Components.interfaces.nsILoginInfo) as nsILoginInfo;
    login.init(
      this.origin,
      null as unknown as string,
      this.realm,
      "api",
      value,
    );
    if (existing) Services.logins.modifyLogin(existing, login);
    else await Services.logins.addLoginAsync(login);
  }

  static async clearKey() {
    await Services.logins.initializationPromise;
    for (const login of Services.logins.findLogins(
      this.origin,
      "",
      this.realm,
    )) {
      Services.logins.removeLogin(login);
    }
  }

  private static config(): AIConfig {
    return normalizeAIConfig({
      baseURL: getPref("aiBaseURL"),
      model: getPref("aiModel"),
      sourceLang: getPref("aiSourceLang"),
      targetLang: getPref("aiTargetLang"),
      pages: getPref("aiPages"),
      qps: getPref("aiQPS"),
      translateTables: getPref("aiTranslateTables"),
      skipReferences: getPref("aiSkipReferences") !== false,
    });
  }

  private static async request(
    path: string,
    method = "GET",
    body?: object,
    timeout = 15000,
  ) {
    const token = String(getPref("aiBridgeToken") || "");
    if (!token)
      throw new Error("本地翻译服务未配置，请先运行安装包里的本地服务设置脚本");
    let response;
    try {
      response = await Zotero.HTTP.request(method, this.base + path, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
        timeout,
        successCodes: false,
        // Never include the request body (PDF/API credentials) in Zotero debug logs.
        logBodyLength: 0,
        errorDelayMax: 0,
      });
    } catch {
      throw new Error(
        "无法连接本地 PDF 翻译服务，请检查本地引擎路径或重新运行启动脚本",
      );
    }
    let payload;
    try {
      payload = JSON.parse(response.responseText || "");
    } catch {
      throw new Error("本地翻译服务返回了无效响应");
    }
    if (response.status < 200 || response.status >= 300) {
      throw new Error(
        String(payload.message || `本地服务 HTTP ${response.status}`),
      );
    }
    return payload;
  }

  static async ensureService(): Promise<string> {
    try {
      const health = await this.request("/health", "GET", undefined, 1500);
      if (health.protocol !== 1) throw new Error("本地服务协议不匹配");
      return String(health.engine);
    } catch {
      /* Start the installed local worker without opening a console. */
    }
    const python = String(getPref("aiPythonPath") || "");
    const service = String(getPref("aiServicePath") || "");
    const state = String(getPref("aiStatePath") || "");
    if (
      !python ||
      !service ||
      !state ||
      !(await IOUtils.exists(python)) ||
      !(await IOUtils.exists(service))
    ) {
      throw new Error(
        "本地 PDF 引擎尚未安装，请先运行安装包里的本地服务设置脚本",
      );
    }
    void Zotero.Utilities.Internal.exec(python, [
      service,
      "--state-dir",
      state,
    ]).catch(() => {});
    for (let i = 0; i < 15; i++) {
      await Zotero.Promise.delay(500);
      try {
        const health = await this.request("/health", "GET", undefined, 1500);
        if (health.protocol === 1) return String(health.engine);
      } catch {
        /* wait for service startup */
      }
    }
    throw new Error("本地服务启动失败，请检查 Python 环境或运行启动脚本");
  }

  private static hasTag(item: Zotero.Item, tag: string): boolean {
    return item.getTags().some((t) => t.tag === tag);
  }

  private static isTranslation(item: Zotero.Item): boolean {
    const title = String(item.getField("title") || "");
    const filename = String(item.attachmentFilename || "");
    return (
      item.getTags().some((t) => t.tag.startsWith("ai-reader-source:")) ||
      /幻觉翻译|hjfy|AI译文/i.test(title) ||
      /(?:_hjfy_|[._-](?:mono|dual)(?:[._-]|\.pdf$))/i.test(filename)
    );
  }

  private static async resolveSource(item: Zotero.Item): Promise<Zotero.Item> {
    if (
      item.isFileAttachment() &&
      item.attachmentContentType === "application/pdf" &&
      !this.isTranslation(item)
    )
      return item;
    const sourceTag = item
      .getTags()
      .find((t) => t.tag.startsWith("ai-reader-source:"));
    if (sourceTag) {
      const source = Zotero.Items.getByLibraryAndKey(
        item.libraryID,
        sourceTag.tag.slice("ai-reader-source:".length),
      );
      if (source) return source;
    }
    const parent = item.isRegularItem()
      ? item
      : item.parentItemID
        ? Zotero.Items.get(item.parentItemID)
        : null;
    const sources = parent
      ? parent
          .getAttachments()
          .map((id) => Zotero.Items.get(id))
          .filter(
            (a) =>
              a?.isFileAttachment() &&
              a.attachmentContentType === "application/pdf" &&
              !this.isTranslation(a),
          )
      : [];
    if (!sources.length)
      throw new Error(
        "没有找到本地原文 PDF。请先添加论文的 PDF 附件；AI 翻译不要求 arXiv ID。",
      );
    const best = await parent!.getBestAttachment();
    return sources.find((s) => best && s.id === best.id) || sources[0];
  }

  private static pending(): PendingJob[] {
    try {
      const value = JSON.parse(String(getPref("aiPendingJobs") || "[]"));
      return Array.isArray(value)
        ? value.filter(
            (j) =>
              Number.isInteger(j.sourceID) &&
              typeof j.signature === "string" &&
              /^[a-f0-9]{32}$/.test(j.jobID),
          )
        : [];
    } catch {
      return [];
    }
  }

  private static storePending(job: PendingJob) {
    setPref(
      "aiPendingJobs",
      JSON.stringify([
        ...this.pending().filter((j) => j.sourceID !== job.sourceID),
        job,
      ]),
    );
  }

  private static clearPending(sourceID: number) {
    setPref(
      "aiPendingJobs",
      JSON.stringify(this.pending().filter((j) => j.sourceID !== sourceID)),
    );
  }

  private static async existing(source: Zotero.Item, signature: string) {
    const search = new Zotero.Search();
    search.addCondition("libraryID", "is", String(source.libraryID));
    search.addCondition("tag", "is", `ai-reader-cache:${signature}`);
    const ids = await search.search();
    for (const id of ids) {
      const item = Zotero.Items.get(id);
      if (
        !item?.deleted &&
        this.hasTag(item, `ai-reader-source:${source.key}`) &&
        item.isFileAttachment() &&
        (await item.getFilePathAsync())
      )
        return item;
    }
    return null;
  }

  /** Find saved translations by source identity, independently of AI settings. */
  private static async localTranslations(source: Zotero.Item) {
    const search = new Zotero.Search();
    search.addCondition("libraryID", "is", String(source.libraryID));
    search.addCondition("tag", "is", `ai-reader-source:${source.key}`);
    const ids = new Set(await search.search());
    if (source.parentItemID) {
      const parent = Zotero.Items.get(source.parentItemID);
      for (const id of parent?.getAttachments() || []) ids.add(id);
    }
    const translations: Zotero.Item[] = [];
    for (const id of ids) {
      const item = Zotero.Items.get(id);
      if (
        !item ||
        item.deleted ||
        item.id === source.id ||
        item.libraryID !== source.libraryID ||
        !item.isFileAttachment() ||
        item.attachmentContentType !== "application/pdf" ||
        !this.isTranslation(item)
      )
        continue;
      const sourceTags = item
        .getTags()
        .filter((tag) => tag.tag.startsWith("ai-reader-source:"));
      // Never pick a translation belonging to a different original PDF.
      if (
        sourceTags.length &&
        !this.hasTag(item, `ai-reader-source:${source.key}`)
      )
        continue;
      const path = await item.getFilePathAsync();
      if (path && (await IOUtils.exists(path))) translations.push(item);
    }
    return translations;
  }

  /** Read-only entry point: never reads API settings or starts a translation. */
  static async handleOpenExisting(win: _ZoteroTypes.MainWindow) {
    const promptParent = win as unknown as mozIDOMWindowProxy;
    try {
      const selected = win.ZoteroPane.getSelectedItems();
      if (selected.length !== 1)
        throw new Error("请先选择一篇论文、原文 PDF 或已有译文 PDF");
      const source = await this.resolveSource(selected[0]);
      const path = await source.getFilePathAsync();
      if (!path || !(await IOUtils.exists(path)))
        throw new Error("原文 PDF 尚未下载到本机，请先下载原文附件");
      const candidates = await this.localTranslations(source);
      if (!candidates.length)
        throw new Error(
          "没有找到已保存到本机的译文 PDF。请先下载已有译文附件，或使用“AI 翻译 PDF 并分屏打开…”生成译文。此按钮不会发起翻译。",
        );
      // Selecting a translation explicitly takes precedence over other versions.
      let translation = candidates.find((item) => item.id === selected[0].id);
      if (!translation && candidates.length === 1) translation = candidates[0];
      if (!translation) {
        const choice = { value: 0 };
        const labels = candidates.map(
          (item) =>
            `${item.getField("title") || item.attachmentFilename}${item.dateAdded ? ` · ${item.dateAdded}` : ""}`,
        );
        let accepted: boolean;
        try {
          accepted = Services.prompt.select(
            promptParent,
            "选择已有译文",
            "找到多个译文版本，请选择要打开的文件（不会重新翻译）",
            labels,
            choice,
          );
        } catch (error) {
          // Earlier Gecko versions include a separate list-length argument.
          if (
            !/NS_ERROR_XPC_(?:NOT_ENOUGH_ARGS|BAD_CONVERT_JS|NEED_OUT_OBJECT)/.test(
              String(error),
            )
          )
            throw error;
          accepted = (
            Services.prompt.select as unknown as (...args: unknown[]) => boolean
          )(
            win,
            "选择已有译文",
            "找到多个译文版本，请选择要打开的文件（不会重新翻译）",
            labels.length,
            labels,
            choice,
          );
        }
        if (!accepted) return;
        translation = candidates[choice.value];
        if (!translation) return;
      }
      await SplitViewFactory.openItemsInSplitView(source, translation, {
        primarySide: "right",
        activeSide: "right",
      });
    } catch (error) {
      Services.prompt.alert(
        promptParent,
        "打开已有译文",
        error instanceof Error ? error.message : "无法打开已有译文",
      );
    }
  }

  private static async translate(source: Zotero.Item, report: Report) {
    const config = this.config();
    const path = await source.getFilePathAsync();
    if (!path || !(await IOUtils.exists(path)))
      throw new Error("原文 PDF 尚未下载到本机");
    const sourceHash = await Zotero.Utilities.Internal.md5Async(path);
    const signature = Zotero.Utilities.Internal.md5(
      cacheSignature(config, sourceHash),
    );
    const cached = await this.existing(source, signature);
    if (cached) {
      report("复用已有 AI 译文，无需再次请求模型", 90);
      return cached;
    }
    await this.ensureService();
    let job: AIJob;
    const old = this.pending().find(
      (j) => j.sourceID === source.id && j.signature === signature,
    );
    if (old) {
      try {
        job = parseAIJob(await this.request(`/jobs/${old.jobID}`));
      } catch (error) {
        if (error instanceof Error && /任务不存在/.test(error.message))
          this.clearPending(source.id);
        throw error;
      }
      if (["failed", "cancelled"].includes(job.status)) {
        this.clearPending(source.id);
        throw new Error(`${job.message}；再次点击可重新翻译`);
      }
      report("继续读取此前任务的进度，不重复提交", 15);
    } else {
      const key = await this.savedKey();
      if (!key) throw new Error("请先在插件设置的 AI 翻译区域保存 API Key");
      const stat = await IOUtils.stat(path);
      if ((stat.size || 0) > 100 * 1024 * 1024)
        throw new Error("当前支持最大 100 MB 的 PDF");
      report("正在提交 PDF 给本地排版引擎", 10);
      const bytes = await IOUtils.read(path);
      if (!isPDFBytes(bytes)) throw new Error("原文不是有效 PDF");
      let binary = "";
      for (let i = 0; i < bytes.length; i += 32768) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      }
      const pdf = Zotero.getMainWindow().btoa(binary);
      const jobID = Zotero.Utilities.Internal.md5(
        Zotero.Utilities.generateObjectKey() + String(Date.now()),
      );
      this.storePending({ sourceID: source.id, signature, jobID });
      job = parseAIJob(
        await this.request(
          "/jobs",
          "POST",
          { pdf, jobID, config: { ...config, apiKey: key } },
          120000,
        ),
      );
    }
    this.running.set(source.id, job.id);
    const deadline = Date.now() + 3 * 60 * 60 * 1000;
    let failures = 0;
    while (["queued", "running"].includes(job.status)) {
      if (!addon.data.alive)
        throw new Error("插件已关闭；任务可在下次操作时继续读取");
      if (Date.now() > deadline)
        throw new Error("等待译文超时；任务记录已保留，再次点击可读取结果");
      report(job.message || "正在翻译", 15 + job.progress * 0.7);
      await Zotero.Promise.delay(1500);
      try {
        job = parseAIJob(await this.request(`/jobs/${job.id}`));
        failures = 0;
      } catch {
        if (++failures >= 5)
          throw new Error(
            "本地服务连接中断；任务记录已保留，再次点击可继续读取",
          );
      }
    }
    if (job.status !== "completed") {
      this.clearPending(source.id);
      throw new Error(job.message || "翻译任务未完成");
    }
    report("译文已生成，正在保存 Zotero 附件", 88);
    const response = await Zotero.HTTP.request(
      "GET",
      `${this.base}/jobs/${job.id}/pdf`,
      {
        headers: { Authorization: `Bearer ${getPref("aiBridgeToken")}` },
        responseType: "arraybuffer",
        timeout: 120000,
      },
    );
    const bytes = new Uint8Array(response.response);
    if (!isPDFBytes(bytes)) throw new Error("本地引擎返回的译文不是有效 PDF");
    const tempFile = Zotero.getTempDirectory();
    tempFile.append(`ai-reader-${job.id}.pdf`);
    await IOUtils.write(tempFile.path, bytes);
    try {
      // A second invocation may have imported the result already.
      const existing = await this.existing(source, signature);
      if (existing) return existing;
      const attachment = await Zotero.Attachments.importFromFile({
        file: tempFile,
        parentItemID: source.parentItemID || undefined,
        libraryID: source.libraryID,
        collections: source.parentItemID ? undefined : source.getCollections(),
        title: `AI译文 (${config.targetLang}) · ${config.model}${config.pages ? ` · 页 ${config.pages}` : ""}`,
      });
      attachment.addTag(`ai-reader-source:${source.key}`);
      attachment.addTag(`ai-reader-cache:${signature}`);
      await attachment.saveTx();
      this.clearPending(source.id);
      return attachment;
    } finally {
      await IOUtils.remove(tempFile.path, { ignoreAbsent: true });
    }
  }

  static async handleCommand(win: _ZoteroTypes.MainWindow) {
    const items = win.ZoteroPane.getSelectedItems();
    const popup = new ztoolkit.ProgressWindow("AI 论文翻译", {
      closeOnClick: false,
      closeTime: -1,
    });
    popup.createLine({ text: "正在检查本地 PDF 和翻译设置", progress: 0 });
    popup.show();
    let source: Zotero.Item | undefined;
    let ownClaim = false;
    try {
      if (items.length !== 1)
        throw new Error("请先选择一篇论文或一个 PDF 附件");
      source = await this.resolveSource(items[0]);
      if (this.claimed.has(source.id))
        throw new Error("这篇论文正在翻译，请等待当前任务完成");
      this.claimed.add(source.id);
      ownClaim = true;
      const report: Report = (text, progress) =>
        popup.changeLine({ idx: 0, text, progress });
      const translation = await this.translate(source, report);
      report("已保存译文，正在打开原文 / 译文分屏", 95);
      await SplitViewFactory.openItemsInSplitView(source, translation, {
        primarySide: "right",
        activeSide: "right",
      });
      popup.changeLine({
        idx: 0,
        text: "原文与 AI 译文已分屏打开",
        progress: 100,
        type: "success",
      });
      popup.startCloseTimer(5000);
    } catch (error) {
      const message = error instanceof Error ? error.message : "翻译失败";
      popup.changeLine({ idx: 0, text: message, progress: 100, type: "error" });
      popup.startCloseTimer(12000);
    } finally {
      if (source && ownClaim) {
        this.claimed.delete(source.id);
        this.running.delete(source.id);
      }
    }
  }

  static async cancelJobs() {
    const records = this.pending();
    for (const job of records) {
      try {
        await this.request(`/jobs/${job.jobID}/cancel`, "POST");
        this.clearPending(job.sourceID);
      } catch {
        /* Keep pending records if the service could not confirm cancellation. */
      }
    }
  }

  /** Local, credential-free diagnostic for command-line installation verification. */
  static async writeDiagnostics() {
    const state = String(getPref("aiStatePath") || "");
    if (!state || !(await IOUtils.exists(state))) return;
    try {
      const windows = Zotero.getMainWindows();
      let bridgeReachable = false;
      let credentialStoreAvailable = false;
      try {
        bridgeReachable =
          (await this.request("/health", "GET", undefined, 2000)).protocol ===
          1;
      } catch {
        /* offline */
      }
      try {
        await Services.logins.initializationPromise;
        credentialStoreAvailable =
          typeof Services.logins.countLogins === "function";
      } catch {
        /* unavailable */
      }
      const diagnostics = {
        version: addon.data.config.addonName,
        initialized: true,
        bridgeReachable,
        credentialStoreAvailable,
        aiMenuRegistered: windows.some(
          (w) => !!w.document.getElementById("ai-translate"),
        ),
        openExistingMenuRegistered: windows.some(
          (w) => !!w.document.getElementById("ai-open-existing"),
        ),
        timestamp: new Date().toISOString(),
      };
      await IOUtils.writeUTF8(
        state + (Zotero.isWin ? "\\" : "/") + "plugin-status.json",
        JSON.stringify(diagnostics),
      );
    } catch {
      /* Diagnostics must never prevent plugin startup. */
    }
  }
}
