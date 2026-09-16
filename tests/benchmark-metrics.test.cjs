const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const context = vm.createContext({ URL });
vm.runInContext(fs.readFileSync(path.join(__dirname, "../apps/geometry-review/benchmark-metrics.js"), "utf8"), context);

test("unmeasured candidate is never converted into zero or a pass", () => {
  const output = context.renderBenchmarkComparison({sample_id:"111",candidate:{label:"ours",metrics:{}},references:[],notes:"",formula:""});
  assert.ok(output.includes("Pending /"));
  assert.ok(!output.includes(">0.000<"));
  assert.ok(output.includes("Not evaluated"));
});
test("reference text and non-HTTPS source links cannot execute", () => {
  const output = context.renderBenchmarkComparison({sample_id:"<img>",candidate:{label:"ours",metrics:{}},references:[{label:"<script>",source_url:"javascript:alert(1)",metrics:{volume_iou:0.6}}]});
  assert.ok(output.includes("&lt;script&gt;"));
  assert.ok(!output.includes('href="javascript:'));
  assert.ok(output.includes(">0.600<"));
});
