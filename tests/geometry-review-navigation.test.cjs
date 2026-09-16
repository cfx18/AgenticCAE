const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../apps/geometry-review/app.js"), "utf8");

function fixture() {
  const fields = [{ value: "", checked: false, hasAttribute: () => false }];
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value: "", textContent: "", innerHTML: "", dataset: {},
      reset() { fields[0].value = ""; fields[0].checked = false; },
      querySelectorAll: () => fields,
      classList: { toggle() {} }, setAttribute() {},
    });
    return elements.get(id);
  };
  const storage = new Map();
  const context = vm.createContext({
    URL, AbortController, console, Date,
    document: {
      getElementById: element, documentElement: { dataset: {} },
      querySelector: () => null, querySelectorAll: () => [],
    },
    sessionStorage: { setItem: (key, value) => storage.set(key, value) },
    localStorage: { getItem: () => null },
    location: { href: "http://localhost:8770/" },
    history: { replaceState(_state, _title, url) { context.location.href = String(url); } },
  });
  vm.runInContext(source.slice(0, source.lastIndexOf("\nstart().catch(")), context);
  const run = (code) => vm.runInContext(code, context);
  return { context, run, element, fields, storage };
}

function bundle(id) {
  return {
    bundle_sha256: id, campaign: { campaign_id: id }, models: ["sol"],
    runs: [{ sample_id: "omnimech:2", target_id: "same-target", model: "sol", dataset: "omnimech",
      selected_attempt_id: "a001", attempts: [{ attempt_id: "a001" }] }],
  };
}

function setupNavigation(f) {
  f.context.makeBundle = bundle;
  f.run(`
    renderHeader = () => {};
    renderNavigation = () => {};
    renderRun = () => {};
    renderRunList = () => {};
    state.catalog = {bundles: [
      {id: 'evo', harness: 'EvoCAD', bundle_sha256: 'evo'},
      {id: 'codex', harness: 'Codex', bundle_sha256: 'codex'}
    ]};
    state.data = makeBundle('evo'); state.bundleId = 'evo';
    state.selectedTarget = 'same-target'; state.selectedAttempt = 'a001';
  `);
}

test("drafts are scoped by immutable bundle and restored after switching", () => {
  const f = fixture();
  setupNavigation(f);
  f.fields[0].value = "EvoCAD note";
  f.run("state.formDirty = true; rememberDraft(); state.data = makeBundle('codex'); resetReviewForm(); restoreDraft();");
  assert.equal(f.fields[0].value, "");
  f.fields[0].value = "Codex note";
  f.run("state.formDirty = true; rememberDraft(); state.data = makeBundle('evo'); resetReviewForm(); restoreDraft();");
  assert.equal(f.fields[0].value, "EvoCAD note");
  f.run("state.data = makeBundle('codex'); resetReviewForm(); restoreDraft();");
  assert.equal(f.fields[0].value, "Codex note");
  assert.equal(Object.keys(JSON.parse(f.storage.get("evocadReviewDrafts"))).length, 2);
});

test("bundle load uses scoped routes and preserves the same sample", async () => {
  const f = fixture();
  setupNavigation(f);
  const requests = [];
  f.context.fetch = async (url) => {
    requests.push(url);
    return { ok: true, json: async () => url.endsWith("reviews")
      ? { integrity: { bundle: { bundle_sha256: "codex" } }, records: [] } : bundle("codex") };
  };
  await f.run("loadBundle('codex')");
  assert.deepEqual(requests, ["/bundles/codex/review-data.json", "/api/bundles/codex/reviews"]);
  assert.equal(f.run("state.bundleId"), "codex");
  assert.equal(f.run("currentRun().sample_id"), "omnimech:2");
  assert.equal(f.run("assetUrl('assets/part.stl')"), "/bundles/codex/assets/part.stl");
  assert.equal(f.context.location.href, "http://localhost:8770/?view=codex");
  assert.equal(f.run("state.loading"), false);
});

test("a ledger failure leaves the previous experiment intact", async () => {
  const f = fixture();
  setupNavigation(f);
  f.context.fetch = async (url) => ({
    ok: !url.endsWith("reviews"), status: 503, json: async () => bundle("codex"),
  });
  await f.run("loadBundle('codex')");
  assert.equal(f.run("state.bundleId"), "evo");
  assert.equal(f.run("state.data.bundle_sha256"), "evo");
  assert.match(f.element("navigationStatus").textContent, /Switch failed/);
  assert.equal(f.element("harnessFilter").disabled, false);
});

test("stale or mismatched ledger data cannot replace the active bundle", async () => {
  const f = fixture();
  setupNavigation(f);
  f.context.fetch = async (url) => ({ ok: true, json: async () => url.endsWith("reviews")
    ? { integrity: { bundle: { bundle_sha256: "evo" } } } : bundle("codex") });
  await f.run("loadBundle('codex')");
  assert.equal(f.run("state.bundleId"), "evo");
  assert.match(f.element("navigationStatus").textContent, /do not match/);
});

test("late responses from a previous switch cannot win a race", async () => {
  const f = fixture();
  setupNavigation(f);
  const pending = [];
  f.context.fetch = (url) => new Promise((resolve) => pending.push({ url, resolve }));
  const first = f.run("loadBundle('codex')");
  const second = f.run("loadBundle('evo')");
  const finish = (entry) => {
    const id = entry.url.includes("codex") ? "codex" : "evo";
    entry.resolve({ ok: true, json: async () => entry.url.endsWith("reviews")
      ? { integrity: { bundle: { bundle_sha256: id } } } : bundle(id) });
  };
  pending.slice(2).forEach(finish);
  await second;
  pending.slice(0, 2).forEach(finish);
  await first;
  assert.equal(f.run("state.bundleId"), "evo");
  assert.equal(f.run("state.data.bundle_sha256"), "evo");
});

test("navigation is blocked while a review is being saved", async () => {
  const f = fixture();
  setupNavigation(f);
  f.context.fetch = () => { throw new Error("Unexpected request"); };
  f.run("state.saving = true;");
  await f.run("loadBundle('codex')");
  assert.equal(f.run("state.bundleId"), "evo");
});

test("record links belong to the selected experiment, not another model or harness", () => {
  const f = fixture();
  assert.equal(f.run("experimentRecord({id:'features'})"), null);
  assert.equal(f.run("experimentRecord({id:'direct-kimi-4'}).href"), "kimi-vision-direct-4.html");
  assert.equal(f.run("experimentRecord({id:'evocad-kimi-2'}).href"), "kimi-vision-evocad-2.html");
  assert.equal(f.run("experimentRecord({id:'direct-astra-2',recorded_io:{summary:{model:'gpt-6-astra'}}}).href"), "astra.html?run=direct-astra-2");
  assert.equal(f.run("experimentRecord({id:'new-sol',recorded_io:{summary:{model:'gpt-5.6-sol'}}})"), null);
});

test("archive only lists catalog experiments and hides unrelated contextual links", () => {
  const f = fixture();
  f.run(`state.catalog = {bundles: [
    {id:'features',harness:'EvoCAD',label:'V2'},
    {id:'direct-kimi-4',harness:'Kimi Code',label:'OmniMech 4 <Kimi>'}
  ]}; renderRecords(state.catalog.bundles[0]);`);
  assert.equal(f.element("experimentRecords").hidden, true);
  assert.match(f.element("recordsLibrary").innerHTML, /OmniMech 4 &lt;Kimi&gt;/);
  assert.doesNotMatch(f.element("recordsLibrary").innerHTML, /direct-2\.html|astra\.html/);
});

test("filter count and reset keep all controls and query state consistent", () => {
  const f = fixture();
  f.run("state.filters.model='sol'; state.filters.outcome='failed'; renderFilterState();");
  assert.equal(f.element("filterCount").textContent, "2 项");
  assert.equal(f.element("resetFilters").disabled, false);
  f.run("renderRunList = renderFilterState; resetFilters();");
  assert.equal(f.element("filterCount").hidden, true);
  assert.equal(f.element("resetFilters").disabled, true);
  assert.equal(f.element("modelFilter").value, "all");
  assert.equal(f.run("Object.values(state.filters).every(v=>v==='all')"), true);
});
