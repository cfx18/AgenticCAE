const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../apps/geometry-review/astra.js"), "utf8");

function fixture() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { value: "", textContent: "", innerHTML: "" });
    return elements.get(id);
  };
  const context = vm.createContext({ document: { getElementById: element }, console });
  vm.runInContext(source.slice(0, source.lastIndexOf("\nstart().catch(")), context);
  return { element, run: (text) => vm.runInContext(text, context) };
}

test("file URLs are scoped and encode hostile characters", () => {
  const f = fixture();
  f.run("records.current = {recorded_io: {base_url: '/recorded-io/astra/'}};");
  assert.equal(f.run("fileUrl('raw/a#b?.lsp')"), "/recorded-io/astra/raw/a%23b%3F.lsp");
});

test("unscored experiments remain neutral instead of zero/fail", () => {
  const f = fixture();
  assert.equal(f.run("scoreLabel(null)"), "N/A");
  assert.equal(f.run("scoreTone(null)"), "");
  assert.equal(f.run("scoreLabel(0)"), "0.00");
  assert.equal(f.run("scoreTone(false)"), "fail");
});

test("human diagnosis is not rendered as a model input", () => {
  const f = fixture();
  assert.equal(f.run("eventKind({kind:'human_diagnostic_evidence'})"), "evaluation");
  assert.equal(f.run("eventKind({kind:'model_input_prompt'})"), "input");
});

test("record text is escaped, searchable, and retains phase provenance", () => {
  const f = fixture();
  f.element("eventFilter").value = "all";
  f.run(`records.timeline = [{sequence:1, phase:'a001/interrupted/i001', kind:'cli_event', source:'raw/test.jsonl', source_line:3,
    payload:{type:'item.completed',item:{type:'agent_message',text:'<img onerror=alert(1)> BOX'}}}]; renderEvents();`);
  assert.ok(f.element("events").innerHTML.includes("&lt;img"));
  assert.ok(!f.element("events").innerHTML.includes("<img"));
  assert.ok(f.element("events").innerHTML.includes("a001/interrupted/i001"));
  f.element("eventSearch").value = "missing";
  f.run("renderEvents()");
  assert.equal(f.element("eventCount").textContent, "0 / 1 records");
});
