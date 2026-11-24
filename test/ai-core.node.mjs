import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { TextEncoder } from "node:util";
import { test } from "node:test";
import { build } from "esbuild";
const built = await build({
  entryPoints: ["src/modules/aiCore.ts"],
  bundle: true,
  write: false,
  format: "esm",
  platform: "node",
});
const { normalizeAIConfig, cacheSignature, parseAIJob, isPDFBytes } =
  await import(
    "data:text/javascript;base64," +
      Buffer.from(built.outputFiles[0].text).toString("base64")
  );
const raw = {
  baseURL: "https://example.invalid/v1/chat/completions/",
  model: "example-model",
  sourceLang: "en",
  targetLang: "zh",
  pages: "",
  qps: 2,
  translateTables: false,
};
test("normalize OpenAI endpoints and preserve local API support", () => {
  assert.equal(normalizeAIConfig(raw).baseURL, "https://example.invalid/v1");
  assert.equal(
    normalizeAIConfig({ ...raw, baseURL: "http://127.0.0.1:11434/v1" }).baseURL,
    "http://127.0.0.1:11434/v1",
  );
  assert.throws(() =>
    normalizeAIConfig({ ...raw, baseURL: "http://example.invalid/v1" }),
  );
  assert.throws(() =>
    normalizeAIConfig({
      ...raw,
      baseURL: "https://example.invalid/v1?key=secret",
    }),
  );
});
test("cache invalidates when source, model, language, pages or layout changes", () => {
  const config = normalizeAIConfig(raw);
  const initial = cacheSignature(config, "original-hash");
  for (const changed of [
    { model: "other" },
    { targetLang: "ja" },
    { pages: "1-2" },
    { translateTables: true },
    { baseURL: "https://other.invalid/v1" },
  ]) {
    assert.notEqual(
      cacheSignature({ ...config, ...changed }, "original-hash"),
      initial,
    );
  }
  assert.notEqual(cacheSignature(config, "edited-file-hash"), initial);
});
test("reject non-PDF output and malformed task IDs", () => {
  assert.ok(isPDFBytes(new TextEncoder().encode("%PDF-1.7")));
  assert.equal(
    isPDFBytes(new TextEncoder().encode("<html>Error</html>")),
    false,
  );
  assert.throws(() => parseAIJob({ id: "../file", status: "completed" }));
  assert.equal(
    parseAIJob({ id: "a".repeat(32), status: "running", progress: 150 })
      .progress,
    100,
  );
});

test("bibliography is skipped by default and its switch invalidates cached results", () => {
  const defaults = normalizeAIConfig(raw);
  assert.equal(defaults.skipReferences, true);
  assert.equal(
    normalizeAIConfig({ ...raw, skipReferences: false }).skipReferences,
    false,
  );
  assert.notEqual(
    cacheSignature(defaults, "same-file"),
    cacheSignature({ ...defaults, skipReferences: false }, "same-file"),
  );
});
