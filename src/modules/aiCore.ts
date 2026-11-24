/** Pure protocol/config helpers shared by the UI and translation flow. */
export interface AIConfig {
  baseURL: string;
  model: string;
  sourceLang: string;
  targetLang: string;
  pages: string;
  qps: number;
  translateTables: boolean;
  skipReferences?: boolean;
}

export interface AIJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  message: string;
}

export function normalizeAIConfig(raw: AIConfig): AIConfig {
  const baseURL = raw.baseURL
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/chat\/completions$/, "");
  let url: URL;
  try {
    url = new URL(baseURL);
  } catch {
    throw new Error("请先在插件设置里填写 AI 接口 Base URL");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("Base URL 不能包含密钥、查询参数或片段");
  }
  if (
    url.protocol !== "https:" &&
    !(
      url.protocol === "http:" &&
      ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
    )
  ) {
    throw new Error("远程 AI 接口请使用 HTTPS；本机接口可以使用 HTTP");
  }
  const model = raw.model.trim();
  if (!model) throw new Error("请先在插件设置里填写模型名称");
  const sourceLang = raw.sourceLang.trim() || "en";
  const targetLang = raw.targetLang.trim() || "zh";
  if (
    ![sourceLang, targetLang].every((v) =>
      /^[A-Za-z][A-Za-z0-9-]{0,20}$/.test(v),
    )
  ) {
    throw new Error("语言代码无效，请填写 en、zh、ja 等语言代码");
  }
  const pages = raw.pages.trim();
  if (pages && !/^[0-9,\- ]{1,200}$/.test(pages)) {
    throw new Error("页码范围请填写 1-3 或 1,3,5；留空翻译全文");
  }
  return {
    baseURL,
    model,
    sourceLang,
    targetLang,
    pages,
    qps: Math.max(1, Math.min(4, Number(raw.qps) || 2)),
    translateTables: !!raw.translateTables,
    skipReferences: raw.skipReferences !== false,
  };
}

export function cacheSignature(config: AIConfig, sourceHash: string): string {
  return JSON.stringify([
    sourceHash,
    config.baseURL,
    config.model,
    config.sourceLang,
    config.targetLang,
    config.pages,
    config.translateTables,
    config.skipReferences !== false,
  ]);
}

export function parseAIJob(raw: unknown): AIJob {
  const job = raw as AIJob;
  if (
    !job ||
    !/^[a-f0-9]{32}$/.test(job.id) ||
    !["queued", "running", "completed", "failed", "cancelled"].includes(
      job.status,
    )
  ) {
    throw new Error("本地翻译服务返回了无效的任务状态");
  }
  return {
    ...job,
    progress: Math.max(0, Math.min(100, Number(job.progress) || 0)),
    message: String(job.message || ""),
  };
}

export function isPDFBytes(bytes: Uint8Array): boolean {
  return (
    bytes.length > 5 &&
    bytes[0] === 37 &&
    bytes[1] === 80 &&
    bytes[2] === 68 &&
    bytes[3] === 70 &&
    bytes[4] === 45
  );
}
