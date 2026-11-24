import { config } from "../../package.json";
import { HJFYSplitFactory } from "./hjfySplit";
import { AITranslationFactory } from "./aiTranslation";
import { getPref, setPref } from "../utils/prefs";

export async function registerPrefsScripts(_window: Window) {
  // This function is called when the prefs window is opened
  // See addon/content/preferences.xhtml onpaneload
  if (!addon.data.prefs) {
    addon.data.prefs = {
      window: _window,
    };
  } else {
    addon.data.prefs.window = _window;
  }
  updatePrefsUI();
  bindPrefEvents();
  bindAIPrefs(_window.document);
}

function bindAIPrefs(doc: Document) {
  const fields = [
    ["hjfy-ai-base-url", "aiBaseURL"],
    ["hjfy-ai-model", "aiModel"],
    ["hjfy-ai-source-lang", "aiSourceLang"],
    ["hjfy-ai-target-lang", "aiTargetLang"],
    ["hjfy-ai-pages", "aiPages"],
  ] as const;
  for (const [id, pref] of fields) {
    const input = doc.getElementById(id) as HTMLInputElement | null;
    if (!input) continue;
    input.value = String(getPref(pref) || "");
    input.addEventListener("change", () => setPref(pref, input.value.trim()));
  }
  const status = doc.getElementById("hjfy-ai-status");
  const say = (text: string) => {
    if (status) status.textContent = text;
  };
  const key = doc.getElementById("hjfy-ai-key") as HTMLInputElement | null;
  void AITranslationFactory.savedKey()
    .then((saved) => {
      if (key && saved) key.placeholder = "密钥已保存；留空保持原值";
    })
    .catch(() => say("无法读取加密凭据存储，请检查 Zotero 的凭据设置"));
  const qps = doc.getElementById("hjfy-ai-qps") as HTMLInputElement | null;
  if (qps) {
    qps.value = String(getPref("aiQPS"));
    qps.addEventListener("change", () => {
      const value = Math.max(1, Math.min(4, Number(qps.value) || 2));
      qps.value = String(value);
      setPref("aiQPS", value);
    });
  }
  const tables = doc.getElementById(
    "hjfy-ai-tables",
  ) as HTMLInputElement | null;
  if (tables) {
    tables.checked = getPref("aiTranslateTables");
    tables.addEventListener("command", () =>
      setPref("aiTranslateTables", tables.checked),
    );
  }
  const skipReferences = doc.getElementById(
    "hjfy-ai-skip-references",
  ) as HTMLInputElement | null;
  if (skipReferences) {
    skipReferences.checked = getPref("aiSkipReferences") !== false;
    skipReferences.addEventListener("command", () =>
      setPref("aiSkipReferences", skipReferences.checked),
    );
  }
  doc.getElementById("hjfy-ai-save-key")?.addEventListener("command", () => {
    void (async () => {
      try {
        await AITranslationFactory.saveKey(key?.value || "");
        if (key) {
          key.value = "";
          key.placeholder = "密钥已保存；留空保持原值";
        }
        say("API Key 已加密保存在 Zotero 本机凭据存储中");
      } catch (error) {
        say(error instanceof Error ? error.message : "保存失败");
      }
    })();
  });
  doc.getElementById("hjfy-ai-clear-key")?.addEventListener("command", () => {
    void AITranslationFactory.clearKey()
      .then(() => {
        if (key) {
          key.value = "";
          key.placeholder = "填写密钥后点击保存";
        }
        say("已清除保存的 API Key");
      })
      .catch(() => say("清除密钥失败"));
  });
  doc
    .getElementById("hjfy-ai-test-service")
    ?.addEventListener("command", () => {
      say("正在检查 / 启动本地引擎…");
      void AITranslationFactory.ensureService()
        .then((engine) => say(`本地引擎就绪：${engine}。尚未调用 AI 接口。`))
        .catch((error) =>
          say(error instanceof Error ? error.message : "检查失败"),
        );
    });
}

function updatePrefsUI() {
  if (!addon.data.prefs?.window) return;
  const doc = addon.data.prefs.window.document;

  // Initialize color preview with current pref values
  updateColorPreview(doc);
  updateHJFYCookieInput(doc);
}

function bindPrefEvents() {
  if (!addon.data.prefs?.window) return;
  const doc = addon.data.prefs.window.document;

  // Checkbox: Follow mouse focus to switch primary window
  const followFocusCheckbox = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-follow-focus`,
  ) as HTMLInputElement | null;
  followFocusCheckbox?.addEventListener("command", (e: Event) => {
    const target = e.target as HTMLInputElement;
    setPref("followFocusPrimary", target.checked);
  });

  // Checkbox: Actions Sync
  const syncEnabledCheckbox = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-sync-enabled`,
  ) as HTMLInputElement | null;
  syncEnabledCheckbox?.addEventListener("command", (e: Event) => {
    const target = e.target as HTMLInputElement;
    setPref("syncEnabled", target.checked);
  });

  // Checkbox: automatically fetch HJFY translations for newly added papers
  const autoFetchCheckbox = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-auto-fetch-on-new-items`,
  ) as HTMLInputElement | null;
  autoFetchCheckbox?.addEventListener("command", (e: Event) => {
    const target = e.target as HTMLInputElement;
    setPref("autoFetchOnNewItems", target.checked);
    HJFYSplitFactory.handleAutoTranslatePreferenceChange(target.checked);
  });

  // Password input: HJFY cookie for authenticated translation tasks
  const hjfyCookieInput = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-hjfy-cookie`,
  ) as HTMLInputElement | null;
  const saveHJFYCookie = (e: Event) => {
    const target = e.target as HTMLInputElement;
    setPref("hjfyCookie", target.value.trim());
  };
  hjfyCookieInput?.addEventListener("input", saveHJFYCookie);
  hjfyCookieInput?.addEventListener("change", saveHJFYCookie);

  // RGB inputs: Primary scrollbar color
  const rInput = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-scrollbar-r`,
  ) as HTMLInputElement | null;
  const gInput = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-scrollbar-g`,
  ) as HTMLInputElement | null;
  const bInput = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-scrollbar-b`,
  ) as HTMLInputElement | null;

  const handleColorChange = (
    input: HTMLInputElement | null,
    prefKey: "primaryScrollbarR" | "primaryScrollbarG" | "primaryScrollbarB",
  ) => {
    if (!input) return;
    input.addEventListener("change", () => {
      let val = parseInt(input.value, 10);
      if (isNaN(val)) val = 0;
      // Clamp to 0-255
      val = Math.max(0, Math.min(255, val));
      input.value = String(val);
      setPref(prefKey, val);
      updateColorPreview(doc);
    });
  };

  handleColorChange(rInput, "primaryScrollbarR");
  handleColorChange(gInput, "primaryScrollbarG");
  handleColorChange(bInput, "primaryScrollbarB");
}

function updateHJFYCookieInput(doc: Document) {
  const input = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-hjfy-cookie`,
  ) as HTMLInputElement | null;
  if (input) {
    input.value = String(getPref("hjfyCookie") || "");
  }
}

function updateColorPreview(doc: Document) {
  const r = getPref("primaryScrollbarR") ?? 255;
  const g = getPref("primaryScrollbarG") ?? 0;
  const b = getPref("primaryScrollbarB") ?? 0;

  const preview = doc.querySelector(
    `#zotero-prefpane-${config.addonRef}-color-preview`,
  ) as HTMLElement | null;
  if (preview) {
    preview.style.backgroundColor = `rgb(${r}, ${g}, ${b})`;
  }
}
