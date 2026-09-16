// Read-only acceptance of the result dashboard and links into all three frozen batches.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const base=process.env.POSTTRAIN_REVIEW_URL||'http://127.0.0.1:8775/';
  const output=path.resolve(process.env.DRAWING_REVIEW_TEST_OUTPUT||'.local/reports/drawing-results-ui/browser');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'chrome'}),errors=[];
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1100}});
    page.on('pageerror',e=>errors.push(String(e)));
    page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`);});
    await page.route('**/*',route=>{assert.equal(route.request().method(),'GET','Never submit reviews from this test');return route.continue();});
    const json=async url=>(await page.request.get(new URL(url,base).href)).json();
    const ledgerBefore=await json('/api/reviews');
    await page.goto(new URL('results.html',base).href);
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    const raw=await page.locator('#reportData').textContent(),data=JSON.parse(raw);
    assert.equal(data.rows.length,56);assert.equal(data.adjusted.attempted,45);
    assert.equal(data.adjusted.counts.agree,35);assert.equal(data.adjusted.counts.timeout,7);
    assert.equal(await page.locator('#caseRows tr').count(),45);
    assert.deepEqual(await page.locator('.metric strong').allTextContents(),['77.8%','92.1%','15.6%','1']);
    assert.equal(await page.locator('#batchPlot .plot-row').count(),3);
    for(const width of [1920,1600,1280,800,390,360]){
      await page.setViewportSize({width,height:1100});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert.ok(await page.locator('.plot-track').evaluateAll(rows=>rows.every(r=>Math.abs([...r.children].reduce((sum,e)=>sum+e.getBoundingClientRect().width,0)-r.clientWidth)<2)));
      await page.screenshot({path:path.join(output,`results-${width}.png`),fullPage:true});
    }
    await page.setViewportSize({width:1600,height:1100});
    await page.selectOption('#batch','hard');
    assert.deepEqual(await page.locator('.metric strong').allTextContents(),['54.5%','85.7%','36.4%','1']);
    assert.equal(await page.locator('#caseRows tr').count(),11);
    await page.locator('[data-mode="raw"]').click();
    assert.equal(await page.locator('.metric strong').first().textContent(),'18.2%');
    await page.selectOption('#outcome','pending');assert.equal(await page.locator('#caseRows tr').count(),5);
    await page.locator('[data-mode="adjusted"]').click();assert.equal(await page.locator('#emptyRow').count(),1);
    await page.selectOption('#outcome','disagree');assert.equal(await page.locator('#caseRows tr').count(),1);
    assert.match(await page.locator('#caseRows').innerText(),/hard-15.*人工确认答错/s);
    await page.locator('#caseRows td:first-child summary').click();
    await page.waitForFunction(()=>{const i=document.querySelector('.case-image');return i.complete&&i.naturalWidth>0;});
    await page.screenshot({path:path.join(output,'confirmed-error.png'),fullPage:true});
    assert.equal(await page.locator('#outcome option[value="excluded"]').count(),0);
    await page.selectOption('#outcome','all');
    await page.locator('#search').fill('hard-20');assert.equal(await page.locator('#caseRows tr').count(),1);
    const download=page.waitForEvent('download');await page.locator('#download').click();
    assert.equal((await download).suggestedFilename(),'kimi-drawing-results.json');
    for(const [batch,task] of [['long','drawing-01'],['boxed','boxed-03'],['hard','hard-15']]){
      await page.goto(new URL(`?batch=${batch}&task=${task}`,base).href);
      await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
      assert.equal(await page.locator('#taskName').innerText(),task);
      await page.waitForFunction(()=>{const i=document.querySelector('#mainDrawing');return i.complete&&i.naturalWidth>0;});
      assert.match(await page.locator('#mainDrawing').getAttribute('src'),new RegExp(`/bundles/${batch}/assets/`));
      assert.ok(await page.locator('#resultsLink').isVisible());
      const bundle=await json(`/bundles/${batch}/review-data.json`),eligible=bundle.runs.filter(r=>r.task_manifest.diagnostic_eligible!==false);
      assert.deepEqual(await page.locator('#tasks button').evaluateAll(items=>items.map(e=>e.dataset.task)),eligible.map(r=>r.sample_id));
      assert.match(await page.locator('#reviewCount').innerText(),new RegExp(`/ ${eligible.length} 题`));
      if(batch==='hard'){
        assert.equal(await page.locator('#learnerStatus').innerText(),'人工确认答错');
        await page.locator('#openReview').click();await page.locator('#history summary').first().click();assert.match(await page.locator('#history').innerText(),/明显是实体/);await page.keyboard.press('Escape');
      }
      await page.locator('[data-tab="trajectory"]').click();
      assert.ok(await page.locator('.receipt-image').count()>0);
      await page.locator('.receipt-image').first().scrollIntoViewIfNeeded();
      await page.waitForFunction(()=>document.querySelector('.receipt-image').naturalWidth>0);
    }
    await page.goto(new URL('?batch=hard&task=hard-01',base).href);
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    assert.equal(await page.locator('#taskName').innerText(),'hard-03');
    assert.equal(new URL(page.url()).searchParams.get('task'),'hard-03');
    assert.equal(await page.locator('#tasks button').count(),11);
    assert.equal(await page.locator('#previousTask').isDisabled(),true);
    await page.locator('#nextTask').click();assert.equal(await page.locator('#taskName').innerText(),'hard-07');
    await page.selectOption('#family','cross_view');assert.equal(await page.locator('#tasks button').count(),3);
    assert.equal(await page.locator('#taskName').innerText(),'hard-09');
    await page.route('**/review-data.json',async route=>{const response=await route.fetch(),bundle=await response.json();for(const run of bundle.runs)run.task_manifest.diagnostic_eligible=false;await route.fulfill({response,json:bundle});});
    await page.goto(new URL('?batch=hard',base).href);
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    assert.equal(await page.locator('#tasks button').count(),0);
    assert.ok(await page.locator('#emptyTasks').isVisible());
    assert.equal(await page.locator('#openReview').isVisible(),false);
    assert.deepEqual((await json('/api/reviews')).records,ledgerBefore.records);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify({status:'passed',errors,rows:56,attempted:45,agreed:35,timeouts:7,viewports:[1920,1600,1280,800,390,360],human_reviews_created:0},null,2));
    console.log('Results: denominators, raw/semantic modes, six widths, case filters, download, 3 batch links, actual images, human confirmation, immutable ledgers passed.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
