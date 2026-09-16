// Read-only browser regression. Source overrides allow testing before restarting the catalog server.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

(async () => {
  const base = process.env.REVIEW_URL || "http://127.0.0.1:8770";
  const sourceMode = process.env.REVIEW_SOURCE === "1";
  const output = path.resolve(".local/reports/geometry-sidebar-20260916", sourceMode ? "source" : "live");
  fs.mkdirSync(output, { recursive: true });
  const config = JSON.parse(fs.readFileSync("apps/geometry-review/catalog.json", "utf8"));
  const hashes = () => Object.fromEntries(config.bundles.flatMap(entry => [entry.reviews, `${entry.bundle}/review-data.json`]).map(file => [file,
    fs.existsSync(file) ? crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex") : null]));
  const beforeHashes = hashes();
  const browser = await chromium.launch({ headless: true, channel: "chrome", args: ["--enable-unsafe-swiftshader"] });
  const errors = [], failedRequests = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    page.on("pageerror", error => errors.push(String(error)));
    page.on("response", response => { if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`); });
    await page.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      assert.equal(request.method(), "GET", "This test must never submit a human review");
      if (sourceMode && url.origin === base) {
        const files = { "/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css", "/vendor/lucide/lucide.min.js": "vendor/lucide/lucide.min.js" };
        if (files[url.pathname]) return route.fulfill({ path: path.resolve("apps/geometry-review", files[url.pathname]) });
      }
      return route.continue();
    });
    const ready = async id => page.waitForFunction(id => document.documentElement.dataset.appState === "ready" && document.querySelector("#experimentFilter").value === id && !document.querySelector("#experimentFilter").disabled, id);
    await page.goto(`${base}/?view=features`);
    await ready("features");
    assert.equal(await page.locator("#runFilters").getAttribute("open"), null);
    assert.equal(await page.locator("#experimentRecords").isVisible(), false);
    assert.ok(await page.locator("#runList .run-item").count() >= 30);
    await page.locator("#runFilters summary").click();
    await page.selectOption("#outcomeFilter", "failed");
    assert.equal(await page.locator("#filterCount").innerText(), "1 项");
    const filtered = await page.locator("#runList .run-item").count();
    assert.ok(filtered > 0 && filtered < 30);
    await page.selectOption("#reviewFilter", "disputed");
    assert.equal(await page.locator("#filterCount").innerText(), "2 项");
    await page.locator("#resetFilters").click();
    assert.ok(await page.locator("#resetFilters").isDisabled());
    assert.ok(await page.locator("#runList .run-item").count() >= 30);

    for (const width of [1920, 1600, 1280, 1040, 800, 675, 390, 360]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator(".run-browser").evaluate(e => { e.scrollTop = 0; });
      const layout = await page.evaluate(() => {
        const sidebar = document.querySelector(".run-browser");
        return {
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          sidebarOverflow: sidebar.scrollWidth > sidebar.clientWidth + 1,
          labels: [...sidebar.querySelectorAll("[data-select-value]")].every(e => e.scrollWidth <= e.clientWidth + 1 && e.scrollHeight <= e.clientHeight + 1),
          icons: sidebar.querySelectorAll("svg.lucide").length,
        };
      });
      assert.equal(layout.overflow, false, `${width}: page width`);
      assert.equal(layout.sidebarOverflow, false, `${width}: sidebar width`);
      assert.ok(layout.labels, `${width}: wrapped selected labels`);
      assert.ok(layout.icons >= 6);
      assert.ok(await page.locator('#drawingResultsLink').isVisible());
      assert.ok(await page.locator('.review-navigation').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
      await page.screenshot({ path: path.join(output, `filters-${width}.png`) });
      await page.locator("#runFilters summary").click();
      await page.screenshot({ path: path.join(output, `sidebar-${width}.png`) });
      await page.locator("#runFilters summary").click();
    }
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.locator("#runFilters summary").click();
    await page.locator("#openRecords").click();
    assert.ok(await page.locator("#recordsDialog").isVisible());
    const links = await page.locator("#recordsLibrary a").evaluateAll(links => links.map(a => a.getAttribute("href")));
    for (const href of links) assert.equal((await page.request.get(`${base}/${href}`)).status(), 200, href);
    assert.ok(links.includes("kimi-vision-direct-4.html") && links.includes("kimi-vision-evocad-2.html"));
    await page.screenshot({ path: path.join(output, "archive-desktop.png") });
    await page.setViewportSize({ width: 360, height: 844 });
    await page.screenshot({ path: path.join(output, "archive-mobile.png") });
    assert.ok(await page.locator("#recordsDialog").evaluate(e => e.scrollWidth <= e.clientWidth + 1));
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#recordsDialog").isVisible(), false);
    await page.setViewportSize({ width: 1600, height: 1000 });

    await page.selectOption("#harnessFilter", "Kimi Code");
    await ready("direct-kimi-2");
    await page.selectOption("#experimentFilter", "direct-kimi-4");
    await ready("direct-kimi-4");
    assert.equal(await page.locator("#experimentRecords a").getAttribute("href"), "kimi-vision-direct-4.html");
    await page.selectOption("#harnessFilter", "Codex");
    await page.waitForFunction(() => !document.querySelector("#experimentFilter").disabled);
    await page.selectOption("#experimentFilter", "direct-astra-2");
    await ready("direct-astra-2");
    assert.equal(await page.locator("#experimentRecords a").getAttribute("href"), "astra.html?run=direct-astra-2");
    await page.screenshot({ path: path.join(output, "astra-context.png") });
    await page.selectOption("#harnessFilter", "EvoCAD");
    await ready("features");
    await page.selectOption("#experimentFilter", "evocad-kimi-2");
    await ready("evocad-kimi-2");
    for (const width of [1280, 800, 675, 360]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.locator('[data-select-value="experimentFilter"]').evaluate(e => e.scrollWidth <= e.clientWidth + 1 && e.scrollHeight <= e.clientHeight + 1));
      await page.screenshot({ path: path.join(output, `long-experiment-${width}.png`) });
    }
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.selectOption("#experimentFilter", "features");
    await ready("features");
    assert.equal(await page.locator("#experimentRecords").isVisible(), false);
    await page.locator('#candidateViewer[data-viewer-state="ready"]').waitFor({ timeout: 30000 });
    const canvases = page.locator(".geometry-viewer canvas");
    const pixels = () => canvases.evaluateAll(list => list.map(c => {
      const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
      let nonBackground = 0, checksum = 0;
      for (let i = 0; i < d.length; i += 16) {
        if (Math.abs(d[i] - 28) + Math.abs(d[i + 1] - 37) + Math.abs(d[i + 2] - 44) > 40) nonBackground++;
        checksum = (checksum + d[i] * (i + 1)) % 1000000007;
      }
      return { nonBackground, checksum };
    }));
    const before = await pixels();
    assert.equal(before.length, 3);
    before.forEach(p => assert.ok(p.nonBackground > 500));
    const canvas = page.locator("#candidateViewer canvas");
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width * .4, box.y + box.height * .4);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * .7, box.y + box.height * .6, { steps: 12 });
    await page.mouse.up();
    const after = await pixels();
    after.forEach((p, i) => assert.notEqual(p.checksum, before[i].checksum, "Synchronized orbit remains interactive"));
    await page.locator('#drawingResultsLink').click();
    await page.waitForURL('http://127.0.0.1:8775/results.html');
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    assert.equal(await page.locator('#caseRows tr').count(),45);
    assert.ok(await page.locator('#geometryReviewLink').isVisible());
    await page.locator('#geometryReviewLink').click();
    await ready('features');
    assert.deepEqual(errors, []);
    assert.deepEqual(failedRequests, []);
    assert.deepEqual(hashes(), beforeHashes, "Evidence and human review ledgers remain unchanged");
    fs.writeFileSync(path.join(output, "result.json"), JSON.stringify({ status: "passed", sourceMode, links, errors, failedRequests, canvases: { before, after }, immutableFiles: beforeHashes }, null, 2));
    console.log("Sidebar: 8 widths, filters/reset, contextual archive, catalog switches, synchronized 3D orbit; evidence/ledgers unchanged.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
