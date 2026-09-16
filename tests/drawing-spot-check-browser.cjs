const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const base=process.env.POSTTRAIN_REVIEW_URL||'http://127.0.0.1:8775/';
  const output=path.resolve('.local/reports/drawing-results-ui/spot-check');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'chrome'}),errors=[];
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1100}});
    page.on('pageerror',e=>errors.push(String(e)));
    page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`);});
    await page.route('**/*',route=>{assert.equal(route.request().method(),'GET');return route.continue();});
    const json=async url=>(await page.request.get(new URL(url,base).href)).json();
    const reviewsUrl='/api/bundles/spot-omnimech-4/reviews',before=await json(reviewsUrl);
    const bundle=await json('/bundles/spot-omnimech-4/review-data.json'),run=bundle.runs[0];
    assert.equal(run.task_manifest.label_status,'unlabeled_probe');
    assert.equal(run.reference_answer.answer,null);assert.equal(run.annotation.blind_audit,null);
    assert.equal(run.learner.passed,null);
    const submitted=run.learner_answer!==null;
    assert.ok(submitted||run.learner.status==='timeout'||run.learner.status==='no_submission');
    await page.goto(new URL('results.html',base).href);
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    assert.equal(await page.locator('#caseRows tr').count(),45);
    await page.locator('#diagnosticLinks a').click();
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready'&&document.querySelector('#taskName')?.textContent==='omnimech4-line-01');
    await page.waitForFunction(()=>document.querySelector('#mainDrawing').naturalWidth>0);
    assert.equal(await page.locator('#query').innerText(),'红框中这段线表示什么？');
    assert.equal(await page.locator('#referenceValue').innerText(),'暂无独立标注');
    assert.equal(await page.locator('#learnerValue').innerText(),submitted?run.learner_answer.answer:'未提交答案');
    if(run.learner.status==='timeout')assert.equal(await page.locator('#learnerStatus').innerText(),'超时，未评分');
    assert.equal(await page.locator('#blindDetails').isVisible(),false);
    for(const width of [1600,390]){
      await page.setViewportSize({width,height:1100});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await page.screenshot({path:path.join(output,`answer-${width}.png`),fullPage:true});
    }
    await page.setViewportSize({width:1600,height:1100});
    await page.locator('[data-tab="trajectory"]').click();
    assert.equal(await page.locator('.receipt-image').count(),run.learner.observations);
    for(let i=0;i<run.learner.observations;i++){
      await page.locator('.receipt-image').nth(i).scrollIntoViewIfNeeded();
      await page.waitForFunction(i=>document.querySelectorAll('.receipt-image')[i].naturalWidth>0,i);
    }
    await page.locator('[data-tab="details"]').click();
    assert.match(await page.locator('#checkSummary').innerText(),/未进行独立标注或盲审/);
    for(const href of await page.locator('#downloads a').evaluateAll(items=>items.map(a=>a.href)))assert.equal((await page.request.get(href)).status(),200);
    assert.deepEqual((await json(reviewsUrl)).records,before.records);
    assert.deepEqual(errors,[]);
    console.log('Unlabeled probe: exact question/answer, no fabricated GT/audit, unchanged 45-question denominator, actual receipts, two widths, immutable ledger passed.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
