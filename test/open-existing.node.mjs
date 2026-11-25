import assert from "node:assert/strict";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";

const built = await build({
  entryPoints: ["src/modules/aiTranslation.ts"],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
  plugins: [
    {
      name: "isolate-zotero-io",
      setup(builder) {
        builder.onResolve(
          { filter: /(?:\/splitView|\/utils\/prefs)$/ },
          (args) => ({
            path: args.path,
            namespace: "test-double",
          }),
        );
        builder.onLoad({ filter: /.*/, namespace: "test-double" }, (args) => ({
          contents: args.path.endsWith("splitView")
            ? "export const SplitViewFactory = { async openItemsInSplitView(...args) { globalThis.state.opened.push(args); } };"
            : "export function getPref() { globalThis.state.forbidden.push('AI settings'); throw new Error('No settings access'); } export const setPref = getPref;",
        }));
      },
    },
  ],
});

function fixture() {
  const state = { opened: [], alerts: [], choices: [], forbidden: [] };
  const records = new Map();
  const present = new Set();
  let selected = [];
  const win = { ZoteroPane: { getSelectedItems: () => selected } };
  const context = {
    module: { exports: {} },
    state,
    Zotero: {
      Items: {
        get: (id) => records.get(id),
        getByLibraryAndKey: (library, key) =>
          [...records.values()].find(
            (item) => item.libraryID === library && item.key === key,
          ),
      },
      Search: class {
        conditions = [];
        addCondition(...args) {
          this.conditions.push(args);
        }
        async search() {
          const tag = this.conditions.find(([field]) => field === "tag")[2];
          return [...records.values()]
            .filter((item) => item.getTags().some((t) => t.tag === tag))
            .map((item) => item.id);
        }
      },
      HTTP: {
        request() {
          state.forbidden.push("HTTP");
          throw new Error("No translation requests");
        },
      },
      Utilities: {
        Internal: {
          md5Async() {
            state.forbidden.push("hash");
            throw new Error("No cache signature");
          },
        },
      },
    },
    IOUtils: { exists: async (path) => present.has(path) },
    Services: {
      logins: new Proxy(
        {},
        {
          get() {
            state.forbidden.push("credentials");
            throw new Error("No credentials access");
          },
        },
      ),
      prompt: {
        alert: (_win, _title, message) => state.alerts.push(message),
        select: (...args) => {
          state.choices.push(args);
          args.at(-1).value = 1;
          return true;
        },
      },
    },
  };
  runInNewContext(built.outputFiles[0].text, context);
  const factory = context.module.exports.AITranslationFactory;
  function item(id, options = {}) {
    const value = {
      id,
      key: `K${id}`,
      libraryID: 1,
      parentItemID: 1,
      attachmentContentType: "application/pdf",
      attachmentFilename: `${id}.pdf`,
      getTags: () => [],
      getField: () => "Original",
      isFileAttachment: () => true,
      isRegularItem: () => false,
      getFilePathAsync: async () => `/fixture/${id}.pdf`,
      ...options,
    };
    records.set(id, value);
    present.add(`/fixture/${id}.pdf`);
    return value;
  }
  const source = item(2);
  const parent = item(1, {
    parentItemID: false,
    isFileAttachment: () => false,
    isRegularItem: () => true,
    getAttachments: () => [...records.keys()].filter((id) => id !== 1),
    getBestAttachment: async () => source,
  });
  function translation(id, options = {}) {
    return item(id, {
      getField: () => `AI译文 · version ${id}`,
      getTags: () => [
        { tag: "ai-reader-source:K2" },
        { tag: `ai-reader-cache:old-settings-${id}` },
      ],
      ...options,
    });
  }
  async function open(value = parent) {
    selected = Array.isArray(value) ? value : [value];
    await factory.handleOpenExisting(win);
    assert.deepEqual(
      state.forbidden,
      [],
      "Opening a saved PDF must never touch AI settings, credentials, hashes or HTTP",
    );
  }
  return {
    state,
    context,
    source,
    parent,
    records,
    present,
    translation,
    open,
  };
}

test("opens saved translation from the parent without cache/config/API access", async () => {
  const f = fixture();
  const translated = f.translation(3);
  await f.open();
  assert.equal(f.state.opened[0][0], f.source);
  assert.equal(f.state.opened[0][1], translated);
  assert.equal(f.state.alerts.length, 0);
});

test("selecting a translation opens that exact version and resolves its original", async () => {
  const f = fixture();
  const translated = f.translation(3);
  f.translation(4);
  await f.open(translated);
  assert.equal(f.state.opened[0][0], f.source);
  assert.equal(f.state.opened[0][1], translated);
  assert.equal(f.state.choices.length, 0);
});

test("multiple saved translations require a choice; cancelling opens nothing", async () => {
  const f = fixture();
  f.translation(3);
  const second = f.translation(4);
  await f.open(f.source);
  assert.equal(f.state.opened[0][1], second);
  assert.equal(f.state.choices.length, 1);
  f.context.Services.prompt.select = () => false;
  await f.open();
  assert.equal(f.state.opened.length, 1);
});

test("ignores missing, deleted, foreign-library and other-source PDFs", async () => {
  const f = fixture();
  f.translation(3, { deleted: true });
  f.translation(4, { libraryID: 2 });
  f.translation(5, { getTags: () => [{ tag: "ai-reader-source:OTHER" }] });
  f.translation(6);
  f.present.delete("/fixture/6.pdf");
  await f.open();
  assert.equal(f.state.opened.length, 0);
  assert.match(f.state.alerts[0], /没有找到.*译文/);
});

test("supports standalone source/translation pairs and legacy HJFY attachments", async () => {
  const f = fixture();
  f.source.parentItemID = false;
  const standalone = f.translation(3, { parentItemID: false });
  await f.open(f.source);
  assert.equal(f.state.opened[0][1], standalone);
  f.records.delete(3);
  f.source.parentItemID = 1;
  const legacy = f.translation(4, {
    getField: () => "幻觉翻译 - example",
    getTags: () => [],
  });
  await f.open();
  assert.equal(f.state.opened[1][1], legacy);
});

test("missing original or no selection never falls back to translation", async () => {
  const f = fixture();
  f.translation(3);
  f.present.delete("/fixture/2.pdf");
  await f.open();
  await f.open([]);
  assert.equal(f.state.opened.length, 0);
  assert.match(f.state.alerts[0], /原文 PDF 尚未下载/);
  assert.match(f.state.alerts[1], /请先选择/);
});

test("supports earlier Gecko selection signatures without opening twice", async () => {
  const f = fixture();
  f.translation(3);
  const second = f.translation(4);
  f.context.Services.prompt.select = (...args) => {
    if (args.length === 5) throw new Error("NS_ERROR_XPC_NOT_ENOUGH_ARGS");
    assert.equal(args[3], 2);
    args[5].value = 1;
    return true;
  };
  await f.open();
  assert.equal(f.state.opened.length, 1);
  assert.equal(f.state.opened[0][1], second);
});
