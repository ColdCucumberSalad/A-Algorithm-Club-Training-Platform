const {chromium}=require('../.local/poker-ui/node_modules/playwright');
const fs=require('fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('app.js','utf8');
(async()=>{const browser=await chromium.launch({headless:true,channel:process.env.ACTIVITY_BROWSER_CHANNEL||"msedge"});try{
for(const gap of ['true','false'])for(const width of [360,900]){
 const page=await browser.newPage({viewport:{width:width+40,height:600}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent(`<div class="activity-heat-layout" style="width:${width}px"><div class="activity-fixed-weekdays"></div><div class="activity-heat-scroll" style="overflow:auto"><div id="activityHeatmap" class="activity-heatmap" data-range="month"></div></div></div><input id="activityMonth" value="2026-08"><select id="activityRange"><option value="month">month</option></select><div id="activityPeriod"></div>`);
 await page.addStyleTag({path:'theme-settings.css'});
 for(const path of ['activity-dates.js','activity-data.js','activity-view.js'])await page.addScriptTag({path});
 await page.evaluate(({source,gap})=>{
 document.documentElement.dataset.heatmapMonthGap=gap;
 window.$=s=>document.querySelector(s);window.selectedPulseDate='2026-11-04';window.loads=0;window.requests=[];
 window.makeDays=(start,end)=>{const days=[];for(let d=new Date(start+'T12:00:00');d.toISOString().slice(0,10)<=end;d.setDate(d.getDate()+1))days.push({date:d.toISOString().slice(0,10),ac:0});return days;};
 window.activityPayload={neighborDays:makeDays('2025-06-01','2027-01-31'),days:[],today:'2026-11-04',semester:{end:'2027-01-31'}};
 window.loadTrainingActivity=()=>{loads++;};
 window.clubApi={request:async url=>{requests.push(url);const p=new URL(url,'http://local').searchParams;return {ok:true,json:async()=>({days:makeDays(p.get('start'),p.get('end'))})};}};
 window.activityStore=new ActivityData.Store(url=>clubApi.request(url));
 (0,eval)(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")));
 (0,eval)(source.slice(source.indexOf('let activityPrefetch = null;'),source.indexOf('function wirePulseAtlas(')));
 window.framesScheduled=0;
 const platform=Object.fromEntries(['document','getComputedStyle','ResizeObserver','cancelAnimationFrame','matchMedia','setTimeout','clearTimeout'].map(key=>[key,window[key]]));platform.requestAnimationFrame=callback=>{framesScheduled++;return requestAnimationFrame(callback);};
 Object.assign(window,ActivityView.create(window,platform));
 document.querySelector('#activityHeatmap').innerHTML=renderActivitySlidingMonths(activityPayload);wireActivityHeatScroll();
 },{source,gap});
 await page.waitForTimeout(650);
 const before=await page.evaluate(()=>({count:activityVisibleMonthCount(),month:$('#activityMonth').value,left:$('.activity-heat-scroll').scrollLeft}));
 await page.evaluate(()=>{
 const t=$('.activity-heat-scroll'),markers=[...t.querySelectorAll('[data-window-end]')];
 const target=markers.find(x=>x.dataset.windowEnd==='2026-05');
 const origin=(target.dataset.activityDate?markers[0].parentElement:markers[0]).getBoundingClientRect().left;
 t.scrollLeft=target.getBoundingClientRect().right-origin-t.clientWidth;
 });
 await page.waitForTimeout(800);
 const after=await page.evaluate(()=>({count:activityVisibleMonthCount(),month:$('#activityMonth').value,loads}));
 assert.equal(after.month,'2026-05');assert.equal(after.count,before.count);
 const sizes=await page.evaluate(()=>{
  const grid=$('.activity-heat-grid'),cell=$('.activity-heat-cell'),style=getComputedStyle(grid),heat=getComputedStyle($('#activityHeatmap'));
  const probe=grid.cloneNode(true);probe.removeAttribute('style');$('#activityHeatmap').append(probe);const expected=probe.querySelector('.activity-heat-cell').getBoundingClientRect().width;probe.remove();
  return {width:cell.getBoundingClientRect().width,height:cell.getBoundingClientRect().height,expected,gap:parseFloat(style.columnGap),expectedGap:parseFloat(heat.getPropertyValue('--activity-gap'))};
 });
 assert.ok(Math.abs(sizes.width-sizes.expected)<1,JSON.stringify(sizes));
 assert.ok(Math.abs(sizes.height-sizes.expected)<1,JSON.stringify(sizes));
 assert.equal(sizes.gap,sizes.expectedGap);
 const cachedMeasurements=await page.evaluate(()=>{
  const track=$('.activity-heat-scroll');updateActivityEdgeVisibility(track);
  let reads=0;const cells=[...track.querySelectorAll('.activity-heat-grid > *')];
  const originals=cells.map(cell=>cell.getBoundingClientRect);
  cells.forEach((cell,i)=>cell.getBoundingClientRect=function(){reads++;return originals[i].call(this);});
  const left=track.scrollLeft;track.scrollLeft+=20;
  updateActivityEdgeVisibility(track);track.scrollLeft=left;updateActivityEdgeVisibility(track);
  cells.forEach((cell,i)=>cell.getBoundingClientRect=originals[i]);return reads;
 });
 assert.equal(cachedMeasurements,0,'ordinary scrolling must reuse cached cell positions');
 const frames=await page.evaluate(async()=>{
  const before=framesScheduled;
  for(let i=0;i<50;i++)$('.activity-heat-scroll').dispatchEvent(new Event('scroll'));
  await new Promise(requestAnimationFrame);
  return framesScheduled-before;
 });
 assert.equal(frames,1,'multiple scroll events must share a single animation frame');
 if(gap==='true'){
  const geometry=await page.evaluate(()=>{
   const t=$('.activity-heat-scroll'),entries=[...t.querySelectorAll('.activity-slide-month')];
   const end=entries.findIndex(e=>e.dataset.windowEnd===$('#activityMonth').value);
   const visible=entries.slice(end-activityVisibleMonthCount()+1,end+1);
   return {first:visible[0].getBoundingClientRect().left-t.getBoundingClientRect().left,last:visible.at(-1).getBoundingClientRect().right-t.getBoundingClientRect().right};
  });
  assert.ok(Math.abs(geometry.first-4)<2,JSON.stringify(geometry));assert.ok(Math.abs(geometry.last+4)<2,JSON.stringify(geometry));
 }
const outlines=await page.evaluate(()=>{
 const track=$('.activity-heat-scroll'),r=track.getBoundingClientRect();
 const cells=[...track.querySelectorAll('.activity-heat-cell')].filter(el=>{const b=el.getBoundingClientRect();return getComputedStyle(el).visibility!=='hidden'&&b.left>=r.left&&b.right<=r.right;});
 return [cells[0],cells.at(-1)].map(el=>{el.setAttribute('aria-pressed','true');const s=getComputedStyle(el),b=el.getBoundingClientRect(),extra=parseFloat(s.outlineWidth)+parseFloat(s.outlineOffset);return {left:b.left-extra-r.left,right:r.right-b.right-extra};});
});
assert.ok(outlines.every(o=>o.left>=-.75&&o.right>=-.75),JSON.stringify(outlines));
assert.equal(after.loads,0);assert.deepEqual(errors,[]);
 await page.evaluate(()=>{$('.activity-heat-scroll').scrollLeft=0;});await page.waitForTimeout(1000);
 const edge=await page.evaluate(()=>({requests:requests.length,first:activityPayload.neighborDays[0].date,count:activityVisibleMonthCount()}));
 assert.ok(edge.requests>0);assert.equal(edge.first,'2025-01-01');assert.equal(edge.count,before.count);
 if(gap==='false'){
  const checkWeeks=async()=>{
   const geometry=await page.evaluate(()=>{
    const track=$('.activity-heat-scroll'),r=track.getBoundingClientRect(),grid=track.querySelector('.activity-heat-grid');
    const visible=[...grid.children].filter(el=>getComputedStyle(el).visibility!=='hidden').map(el=>el.getBoundingClientRect()).filter(b=>b.right>r.left+.75&&b.left<r.right-.75);
    return {partial:visible.filter(b=>b.left<r.left-.75||b.right>r.right+.75).length,rows:grid.children.length%7,selected:selectedPulseDate,end:track.dataset.weekEnd,visible:visible.length};
   });
   assert.equal(geometry.partial,0,JSON.stringify(geometry));assert.equal(geometry.rows,0);assert.equal(geometry.selected,'2026-11-04');assert.ok(geometry.visible>0);return geometry;
  };
  await checkWeeks();
  await page.evaluate(()=>{$('.activity-heat-scroll').scrollLeft+=93;});await page.waitForTimeout(800);await checkWeeks();
  await page.evaluate(()=>{const t=$('.activity-heat-scroll');t.scrollLeft=t.scrollWidth;});await page.waitForTimeout(800);
  assert.equal((await checkWeeks()).end,'2026-11-08');
  const lastWeek=await page.evaluate(()=>{const t=$('.activity-heat-scroll'),right=t.getBoundingClientRect().right;return [...t.querySelectorAll('[data-activity-date]')].slice(-7).map(e=>({date:e.dataset.activityDate,left:e.getBoundingClientRect().left,gutter:right-e.getBoundingClientRect().right,visible:getComputedStyle(e).visibility}));});
  assert.equal(lastWeek.length,7);assert.ok(lastWeek.every(e=>e.visible==='visible'&&e.gutter>=3.25),JSON.stringify(lastWeek));assert.equal(new Set(lastWeek.map(e=>e.left)).size,1);

  await page.evaluate(()=>{$('.activity-heat-layout').style.width='317px';});await page.waitForTimeout(800);await checkWeeks();
  // The current week ends on Sunday, with no partial trailing week.
  assert.equal(await page.evaluate(()=>[...$('.activity-heat-grid').children].slice(-7).filter(el=>!el.dataset.activityDate).length),0);
  await page.evaluate(()=>{$('#activityRange').innerHTML+='<option value="semester">semester</option>';$('#activityRange').value='semester';activityPayload.days=activityPayload.neighborDays;delete activityPayload.neighborDays;$('#activityHeatmap').innerHTML=renderActivityMonths(activityPayload.days,'ac','题',activityPayload.today);wireActivityHeatScroll();});
  await page.waitForTimeout(200);assert.deepEqual(errors,[]);
 }
 console.log(JSON.stringify({gap,width,before,after,edge}));await page.close();
}
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
