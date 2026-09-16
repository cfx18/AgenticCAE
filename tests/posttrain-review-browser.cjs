// Read-only browser acceptance: never create a human review during automation.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const output=path.resolve('.local/reports/posttrain-ui');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'chrome',args:['--enable-unsafe-swiftshader']});
  const errors=[];
  try {
    const page=await browser.newPage({viewport:{width:1600,height:1000}});
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('response',response=>{if(response.status()>=400)errors.push(`${response.status()} ${response.url()}`);});
    await page.goto(process.env.POSTTRAIN_REVIEW_URL||'http://127.0.0.1:8772/');
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    assert.equal(await page.locator('#tasks button').count(),20);
    await page.waitForFunction(()=>[...document.querySelectorAll('#images img')].every(image=>image.complete&&image.naturalWidth>0));
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(output,'input-desktop.png'),fullPage:true});
    await page.locator('#openReview').click();
    await page.locator('#notes').fill('Unsaved test draft; never submitted.');
    await page.locator('#closeReview').click();
    await page.locator('[data-task="repair-01"]').click();
    await page.locator('#openReview').click();
    assert.equal(await page.locator('#notes').inputValue(),'');
    await page.locator('#closeReview').click();
    await page.locator('[data-task="line-01"]').click();
    await page.locator('#openReview').click();
    assert.match(await page.locator('#notes').inputValue(),/Unsaved test draft/);
    await page.locator('#closeReview').click();
    await page.locator('[data-task="repair-01"]').click();
    await page.locator('[data-tab="gold"]').click();
    await page.locator('#truthViewer[data-viewer-state="ready"]').waitFor();
    await page.locator('#candidateViewer[data-viewer-state="ready"]').waitFor();
    const pixels=async id=>page.locator(`#${id} canvas`).evaluate(canvas=>{
      if(canvas.hidden)throw new Error('Cannot validate pixels in a hidden/stale canvas');
      const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
      let nonBackground=0,checksum=0;
      for(let i=0;i<pixels.length;i+=16){if(Math.abs(pixels[i]-28)+Math.abs(pixels[i+1]-37)+Math.abs(pixels[i+2]-44)>40)nonBackground++;checksum=(checksum+pixels[i]*(i+1))%1000000007;}
      return {nonBackground,checksum};
    });
    const before={truth:await pixels('truthViewer'),candidate:await pixels('candidateViewer'),overlay:await pixels('overlayViewer')};
    for(const item of Object.values(before))assert.ok(item.nonBackground>500);
    const box=await page.locator('#candidateViewer canvas').boundingBox();
    await page.mouse.move(box.x+box.width*.4,box.y+box.height*.4);await page.mouse.down();
    await page.mouse.move(box.x+box.width*.7,box.y+box.height*.65,{steps:12});await page.mouse.up();
    const after={truth:await pixels('truthViewer'),candidate:await pixels('candidateViewer'),overlay:await pixels('overlayViewer')};
    for(const key of Object.keys(before))assert.notEqual(before[key].checksum,after[key].checksum,`${key} follows shared camera`);
    await page.screenshot({path:path.join(output,'geometry-desktop.png'),fullPage:true});
    await page.locator('[data-tab="details"]').click();
    assert.equal(await page.locator('#negativeChecks details').count(),5);
    await page.screenshot({path:path.join(output,'checks-desktop.png'),fullPage:true});
    await page.locator('[data-tab="details"]').click();
    assert.ok(await page.locator('#downloads a').count()>=4);
    await page.setViewportSize({width:390,height:844});
    await page.locator('[data-tab="input"]').click();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(output,'input-mobile.png'),fullPage:true});
    await page.locator('[data-tab="gold"]').click();
    await page.locator('#truthViewer[data-viewer-state="ready"]').waitFor();
    await page.locator('#candidateViewer[data-viewer-state="ready"]').waitFor();
    await page.locator('#overlayViewer[data-viewer-state="ready"]').waitFor();
    assert.ok((await pixels('truthViewer')).nonBackground>500);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(output,'geometry-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify({status:'passed',errors,before,after,human_reviews_created:0},null,2));
    console.log('Posttrain review: images, evidence, draft isolation, desktop/mobile layout, nonblank 3D and synchronized orbit passed.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
