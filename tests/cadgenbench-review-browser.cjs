// Read-only smoke test against the local review server; never submits human reviews.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

(async () => {
  const output = path.resolve(".local/reports/cadgenbench-111-html");
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, channel:"chrome", args:["--enable-unsafe-swiftshader"]});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:1000}});
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    await page.goto("http://127.0.0.1:8770/astra.html?run=cadgenbench-astra-111");
    await page.locator("#title").filter({hasText:"cadgenbench / 111"}).waitFor();
    await page.locator("#benchmarkComparison .benchmark-table").waitFor();
    assert.match(await page.locator("#benchmarkComparison").innerText(), /0\.664/);
    assert.match(await page.locator("#benchmarkComparison").innerText(), /0\.616/);
    assert.match(await page.locator("#metrics").innerText(), /UNSCORED/);
    await page.waitForFunction(() => [...document.querySelectorAll("#media img")].every(i => i.complete && i.naturalWidth > 0));
    await page.screenshot({path:path.join(output,"astra-desktop.png"),fullPage:true});
    await page.getByRole("button", {name:"Model I/O",exact:true}).click();
    assert.match(await page.locator("#eventCount").innerText(), /157/);
    await page.getByRole("button", {name:"AutoCAD jobs",exact:true}).click();
    assert.equal(await page.locator("#nativeJob option").count(),15);
    await page.goto("http://127.0.0.1:8770/?view=cadgenbench-astra-111");
    await page.waitForFunction(() => document.documentElement.dataset.appState === "ready");
    await page.locator('#candidateViewer[data-viewer-state="ready"]').waitFor({timeout:30000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1),"No horizontal review page overflow on desktop");
    const canvas = page.locator("#candidateViewer canvas");
    const pixels = () => canvas.evaluate(c => {
      const d = c.getContext("2d").getImageData(0,0,c.width,c.height).data;
      let nonBackground=0, checksum=0;
      for(let i=0;i<d.length;i+=16){if(Math.abs(d[i]-28)+Math.abs(d[i+1]-37)+Math.abs(d[i+2]-44)>40)nonBackground++;checksum=(checksum+d[i]*(i+1))%1000000007;}
      return {nonBackground,checksum};
    });
    const before = await pixels();
    assert.ok(before.nonBackground>500,"Candidate canvas must contain visible geometry");
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x+box.width*.45,box.y+box.height*.4);
    await page.mouse.down();
    await page.mouse.move(box.x+box.width*.7,box.y+box.height*.6,{steps:12});
    await page.mouse.up();
    const after = await pixels();
    assert.notEqual(before.checksum, after.checksum,"Orbit drag must move geometry");
    assert.match(await page.locator("#overlayViewer .viewer-status").innerText(),/requires both/);
    await page.screenshot({path:path.join(output,"geometry-desktop.png"),fullPage:true});
    await page.getByRole("button",{name:"Verifier",exact:true}).click();
    await page.locator("#benchmarkComparison .benchmark-table").waitFor();
    await page.screenshot({path:path.join(output,"metrics-desktop.png"),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.goto("http://127.0.0.1:8770/?view=cadgenbench-astra-111");
    await page.waitForFunction(() => document.documentElement.dataset.appState === "ready");
    await page.locator('#candidateViewer[data-viewer-state="ready"]').waitFor({timeout:30000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1),"No horizontal review page overflow on mobile");
    await page.screenshot({path:path.join(output,"geometry-mobile.png"),fullPage:true});
    await page.goto("http://127.0.0.1:8770/astra.html?run=cadgenbench-astra-111");
    await page.locator("#benchmarkComparison .benchmark-table").waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1),"No horizontal page overflow on mobile");
    await page.screenshot({path:path.join(output,"astra-mobile.png"),fullPage:true});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,"smoke.json"),JSON.stringify({status:"passed",errors,canvas:{before,after},screenshots:output},null,2));
    console.log("CADGenBench HTML: desktop/mobile, images, metrics, I/O, native jobs and 3D orbit passed.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error);process.exitCode=1; });
