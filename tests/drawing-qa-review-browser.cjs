const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const output=path.resolve(process.env.DRAWING_REVIEW_TEST_OUTPUT||'.local/reports/drawing-review-v2');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'chrome'}),errors=[];
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1000}});
    page.on('pageerror',e=>errors.push(String(e)));
    page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`);});
    const origin=process.env.POSTTRAIN_REVIEW_URL||'http://127.0.0.1:8778/';
    await page.goto(origin);
    await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    const get=async url=>(await page.request.get(new URL(url,origin).href)).json();
    const bundle=await get('/data/review-data.json'),beforeReviews=await get('/api/reviews');
    const boxed=bundle.campaign.protocol==='boxed-minimal-v1';
    const waitImage=()=>page.waitForFunction(()=>{const i=document.querySelector('#mainDrawing');return i.complete&&i.naturalWidth>0&&document.querySelector('#drawingLoading').hidden;});
    const noOverflow=async()=>assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    const ids=await page.locator('#tasks button').evaluateAll(rows=>rows.map(x=>x.dataset.task));
    const visible=bundle.runs.filter(r=>r.task_manifest.diagnostic_eligible!==false);
    assert.deepEqual(ids,visible.map(r=>r.sample_id));
    assert.ok(ids.length>=10&&ids.length<=24);
    for(const id of ids){
      await page.locator(`[data-task="${id}"]`).click();await waitImage();await noOverflow();
      assert.equal(await page.locator('#reviewDrawer').isVisible(),false);
      assert.ok(await page.locator('#referenceValue').textContent());
      if(boxed){
        assert.equal(await page.locator('#images img').count(),1);
        assert.equal(await page.locator('#questionOptions').isVisible(),false);
        assert.ok((await page.locator('#query').textContent()).length<=35);
        assert.equal(await page.locator('#focusDrawing').getAttribute('aria-pressed'),'true');
        const run=bundle.runs.find(r=>r.sample_id===id),bbox=run.annotation.author.regions[0].bbox;
        assert.ok(await page.evaluate(bbox=>{
          const image=document.querySelector('#mainDrawing'),v=document.querySelector('#imageViewport');
          const x=(bbox[0]+bbox[2])/2000*image.naturalWidth*Number(v.dataset.scale)+Number(v.dataset.x);
          const y=(bbox[1]+bbox[3])/2000*image.naturalHeight*Number(v.dataset.scale)+Number(v.dataset.y);
          return x>0&&y>0&&x<v.clientWidth&&y<v.clientHeight;
        },bbox),'Target box must be visible in focused viewport');
      }
    }
    await page.locator(`[data-task="${ids[0]}"]`).click();await waitImage();
    const focus=Number(await page.locator('#imageViewport').getAttribute('data-scale'));
    await page.locator('#fitDrawing').click();
    const full=Number(await page.locator('#imageViewport').getAttribute('data-scale'));
    if(boxed)assert.ok(focus>full*1.5);
    await page.locator('#zoomIn').click();assert.ok(Number(await page.locator('#imageViewport').getAttribute('data-scale'))>full);
    await page.locator('#focusDrawing').click();
    const v=await page.locator('#imageViewport').boundingBox(),oldX=Number(await page.locator('#imageViewport').getAttribute('data-x'));
    await page.mouse.move(v.x+v.width*.4,v.y+v.height*.4);await page.mouse.down();await page.mouse.move(v.x+v.width*.6,v.y+v.height*.55,{steps:8});await page.mouse.up();
    assert.ok(Math.abs(Number(await page.locator('#imageViewport').getAttribute('data-x'))-oldX)>50);
    const beforeWheel=Number(await page.locator('#imageViewport').getAttribute('data-scale'));
    await page.mouse.wheel(0,-150);await page.waitForFunction(scale=>Number(document.querySelector('#imageViewport').dataset.scale)>scale,beforeWheel);
    await page.locator('#focusDrawing').click();
    await page.locator('#openReview').click();await page.locator('#notes').fill('Unsaved UI test; never persisted.');await page.locator('#closeReview').click();
    await page.locator('#nextTask').click();assert.equal(await page.locator('#taskName').textContent(),ids[1]);
    await page.locator('#openReview').click();assert.equal(await page.locator('#notes').inputValue(),'');await page.keyboard.press('Escape');
    await page.locator('#previousTask').click();await page.locator('#openReview').click();assert.match(await page.locator('#notes').inputValue(),/Unsaved UI test/);
    let submission;
    await page.route(/\/api\/(?:bundles\/[^/]+\/)?reviews$/,async route=>{if(route.request().method()==='POST'){submission=route.request().postDataJSON();await route.fulfill({json:{test_only:true}});}else await route.continue();});
    await page.locator('#reviewer').fill('UI fixture');await page.locator('#decision').selectOption('approve');
    for(const id of ['inputRating','goldRating','verifierRating'])await page.locator('#'+id).selectOption('5');
    await page.locator('#reviewForm button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent.includes('已保存'));
    assert.equal(submission.target_id,visible[0].target_id);assert.equal(submission.attempt_id,visible[0].selected_attempt_id);
    const health=await get('/api/health');if(health.catalog){assert.equal(submission.bundle_sha256,bundle.bundle_sha256);assert.equal(submission.presentation_sha256,(await get('/api/catalog')).presentation_sha256);}
    await page.locator('#closeReview').click();
    await page.locator('[data-tab="details"]').click();
    await page.locator('#modelAnnotation > summary').click();assert.match(await page.locator('#annotation').textContent(),/blind_audit/);
    for(const url of await page.locator('#downloads a').evaluateAll(a=>a.map(x=>x.href)))assert.equal((await page.request.get(url)).status(),200);
    await page.locator('[data-tab="trajectory"]').click();
    const receiptCount=await page.locator('.receipt-image').count();if(process.env.REQUIRE_LEARNER==='1')assert.ok(receiptCount>0);
    for(let i=0;i<receiptCount;i++){await page.locator('.receipt-image').nth(i).scrollIntoViewIfNeeded();await page.waitForFunction(i=>document.querySelectorAll('.receipt-image')[i].naturalWidth>0,i);}
    await page.locator('[data-tab="input"]').click();await waitImage();
    for(const [width,height] of [[1920,1080],[1600,1000],[1280,800],[800,1000],[390,844],[360,780]]){
      await page.setViewportSize({width,height});await noOverflow();await page.locator('#focusDrawing').click();
      await page.screenshot({path:path.join(output,`input-${width}.png`),fullPage:true});
      await page.locator('#openReview').click();assert.ok(await page.locator('#reviewDrawer').isVisible());await noOverflow();
      if(width===390)await page.screenshot({path:path.join(output,'review-mobile.png'),fullPage:true});
      await page.keyboard.press('Escape');
    }
    // Synthetic response fixture exercises trace rendering without modifying any ledger.
    const mock=structuredClone(bundle),run=mock.runs.find(r=>r.sample_id===ids[0]),imageBody=await (await page.request.get(new URL('/'+run.input_images[0],origin).href)).body();
    run.learner={status:'graded',passed:true,observations:1,elapsed_seconds:3};run.learner_answer=run.reference_answer;
    run.events=[{sequence:1,event_type:'observation_returned',payload:{observation_id:'test',intent:'UI fixture: inspect boxed stroke',image:'ui-fixture.png'}},{sequence:2,event_type:'observation_conclusion',payload:{observation_id:'test',public_conclusion:'UI fixture: visible finding <not HTML>'}}];
    await page.route('**/review-data.json',route=>route.fulfill({json:mock}));
    await page.route('**/episode/ui-fixture.png',route=>route.fulfill({body:imageBody,contentType:'image/png'}));
    await page.setViewportSize({width:1600,height:1000});await page.goto(new URL('?task='+run.sample_id,origin).href);await page.waitForFunction(()=>document.documentElement.dataset.appState==='ready');
    await page.locator('[data-tab="trajectory"]').click();assert.match(await page.locator('#events').textContent(),/inspect boxed stroke/);assert.match(await page.locator('#events').textContent(),/visible finding <not HTML>/);
    await page.locator('.receipt-image').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('.receipt-image').naturalWidth>0);
    await noOverflow();assert.equal(await page.locator('#events not').count(),0);
    assert.deepEqual((await get('/api/reviews')).records,beforeReviews.records);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'smoke.json'),JSON.stringify({status:'passed',tasks:ids.length,boxed,receiptCount,errors,human_reviews_created:0,viewports:[1920,1600,1280,800,390,360],pan_zoom:true,review_post_intercepted:true,synthetic_trace_fixture:true},null,2));
    console.log('Review v2: all tasks, focused targets, pan/zoom, Chinese answers, bound review drafts, trace rendering and six viewport sizes passed. No human reviews created.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
