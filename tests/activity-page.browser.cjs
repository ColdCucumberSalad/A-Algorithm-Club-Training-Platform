const {chromium}=require('../.local/poker-ui/node_modules/playwright');
const assert=require('node:assert/strict');
const dates=require('../activity-dates.js');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
 for(const today of ['2026-11-04','2026-11-30','2026-12-31']){
  const sunday=dates.weekEnd(today),monthEnd=dates.monthBounds(today.slice(0,7),1)[1];
  const page=await browser.newPage({viewport:{width:1200,height:900}}),errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/api/training-activity'){
    requests.push(url.search);const days=[];
    for(let date=url.searchParams.get('start');date<=url.searchParams.get('end');date=dates.shiftDate(date,1))days.push({date,ac:0,records:[],isToday:date===today,canSubmit:true});
    await route.fulfill({json:{today,days,semester:{start:'2026-09-01',end:'2027-01-31'}}});
   }else await route.fulfill({status:503,json:{error:'Unrelated API disabled in this isolated UI test'}});
  });
  await page.addInitScript(()=>localStorage.setItem('rbc-site-theme-v3',JSON.stringify({heatmapMonthGap:false})));
  await page.goto('http://localhost/',{waitUntil:'load'});
  await page.waitForTimeout(1000);
  await page.evaluate(async today=>{
   document.documentElement.dataset.heatmapMonthGap='false';
   await loadTrainingActivity({today});
  },today);
  await page.waitForTimeout(600);
  assert.equal(await page.locator(`#activityHeatmap [data-activity-date="${sunday}"]`).count(),1);
  assert.equal(await page.locator(`#activityHeatmap [data-activity-date="${dates.shiftDate(sunday,1)}"]`).count(),0);
  assert.ok((await page.locator('#pulseFocus').textContent()).includes(today));
  const before=requests.length;
  await page.evaluate(()=>window.dispatchEvent(new StorageEvent('storage',{key:'rbc-site-theme-v3',newValue:JSON.stringify({heatmapMonthGap:true})})));
  await page.locator(`#activityHeatmap [data-activity-date="${monthEnd}"]`).waitFor();
  await page.waitForTimeout(650);
  if(sunday<monthEnd){
    assert.equal(requests.length,before+1);assert.equal(requests.at(-1),`?start=${dates.shiftDate(sunday,1)}&end=${monthEnd}`);
  }
  assert.equal(await page.locator('#activityMonth').inputValue(),today.slice(0,7));
  assert.equal(await page.locator('#activityMonth').getAttribute('max'),today.slice(0,7));
  assert.ok((await page.locator('#pulseFocus').textContent()).includes(today));
  const bounds=await page.locator(`#activityHeatmap [data-activity-date="${monthEnd}"]`).boundingBox();
  const viewport=await page.locator('.activity-heat-scroll').boundingBox();
  assert.ok(bounds.x>=viewport.x&&bounds.x+bounds.width<=viewport.x+viewport.width);
  // A fresh gapped window has no next-month cache: switching back must load
  // the rest of a cross-month week instead of showing placeholder cells.
  await page.evaluate(async today=>{
    activityStore.invalidate();activityPayload=null;
    await loadTrainingActivity({today});
  },today);
  await page.waitForTimeout(500);
  await page.evaluate(()=>window.dispatchEvent(new StorageEvent('storage',{key:'rbc-site-theme-v3',newValue:JSON.stringify({heatmapMonthGap:false})})));
  await page.locator(`#activityHeatmap [data-activity-date="${sunday}"]`).waitFor();
  assert.ok((await page.locator('#pulseFocus').textContent()).includes(today));
  assert.deepEqual(errors,[]);
  console.log(`Full-page mode switch passed for ${today}.`);
  await page.close();
 }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
