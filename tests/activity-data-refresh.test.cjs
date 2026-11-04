const {prepare}=require('./activity-fixture.cjs');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
const section=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
test('identical in-flight ranges share one request and failures can be retried',async()=>{
 const pending=[];
 const c=context({clubApi:{request:()=>new Promise(resolve=>pending.push(resolve))}});
 const first=c.requestActivityRange('2026-11-09','2026-11-30');
 const duplicate=c.requestActivityRange('2026-11-09','2026-11-30');
 assert.equal(pending.length,1);
 pending[0]({ok:false,json:async()=>({error:'offline'})});
 await Promise.all([assert.rejects(first,/offline/),assert.rejects(duplicate,/offline/)]);
 const retry=c.requestActivityRange('2026-11-09','2026-11-30');
 assert.equal(pending.length,2);
 pending[1]({ok:true,json:async()=>({days:[]})});await retry;
 assert.equal(c.activityStore.pending.size,0);
});
for(const change of ['mode','month','reload'])test(`a late layout supplement cannot override a changed ${change}`,async()=>{
 const pending=[],nodes=new Map();let renders=0;
 const c=context({trainingRequestVersion:0,activityPayload:{start:'2026-08-01',today:'2026-11-04',neighborDays:[{date:'2026-11-08'}]},
  $:s=>{if(!nodes.has(s))nodes.set(s,{value:s==='#activityMonth'?'2026-11':'month',setAttribute(){},removeAttribute(){}});return nodes.get(s);},
  clubApi:{request:()=>new Promise(resolve=>pending.push(resolve))},renderTrainingActivity:()=>renders++});
 c.document.documentElement.dataset.heatmapMonthGap='true';
 vm.runInContext(section('async function refreshActivityLayout()',"window.addEventListener('site-heatmap-layout-change'"),c);
 const load=c.refreshActivityLayout();
 if(change==='mode'){c.document.documentElement.dataset.heatmapMonthGap='false';await c.refreshActivityLayout();}
 if(change==='month')c.$('#activityMonth').value='2026-10';
 if(change==='reload')c.trainingRequestVersion++;
 pending[0]({ok:true,json:async()=>({days:[{date:'2026-11-30'}]})});await load;
 assert.equal(c.activityPayload.neighborDays.length,1);
 assert.equal(renders,change==='mode'?1:0);
});
test('a failed layout supplement preserves existing dates and supports retry',async()=>{
 const nodes=new Map();let attempts=0;
 const c=context({trainingRequestVersion:0,activityPayload:{start:'2026-08-01',today:'2026-11-04',neighborDays:[{date:'2026-11-08'}]},
  $:s=>{if(!nodes.has(s))nodes.set(s,{value:s==='#activityMonth'?'2026-11':'month',setAttribute(){},removeAttribute(){}});return nodes.get(s);},
  clubApi:{request:async()=>({ok:++attempts>1,json:async()=>({days:[{date:'2026-11-30'}]})})},
  renderTrainingActivity(){}});
 c.document.documentElement.dataset.heatmapMonthGap='true';
 vm.runInContext(section('async function refreshActivityLayout()',"window.addEventListener('site-heatmap-layout-change'"),c);
 await c.refreshActivityLayout();
 assert.match(c.$('#activityNote').innerHTML,/data-activity-layout-retry/);
 assert.equal(c.activityPayload.neighborDays.length,1);
 await c.refreshActivityLayout();
 assert.equal(attempts,2);assert.equal(c.activityPayload.neighborDays.length,2);
});
function context(extra={}) {
 const c={document:{documentElement:{dataset:{heatmapMonthGap:'false'}}},pulseToday:'2026-11-04',...extra};
 prepare(c);vm.createContext(c);
 vm.runInContext(section('function shiftActivityMonth(',"\n$('#activityMonthPopover')?.addEventListener"),c);
 return c;
}

for(const [today,sunday] of [['2026-11-30','2026-12-06'],['2026-12-31','2027-01-03']])test(`gapped layout clamps a cross-month week back to ${today.slice(0,7)}`,async()=>{
 const month={value:sunday.slice(0,7)},nodes=new Map();let renders=0;
 const c=context({pulseToday:today,selectedPulseDate:today,
  activityPayload:{today,start:today,end:sunday,neighborDays:[{date:today},{date:sunday}]},
  $:s=>{if(s==='#activityMonth')return month;if(!nodes.has(s))nodes.set(s,{value:'month',removeAttribute(){}});return nodes.get(s);},
  renderTrainingActivity(){renders++;},loadTrainingActivity(){throw Error('cached dates should be reused');}});
 c.document.documentElement.dataset.heatmapMonthGap='true';
 vm.runInContext(section('async function refreshActivityLayout()',"window.addEventListener('site-heatmap-layout-change'"),c);
 await c.refreshActivityLayout();
 assert.equal(month.value,today.slice(0,7));assert.equal(month.max,today.slice(0,7));
 assert.equal(c.activityPayload.end,c.activityCurrentMonthEnd({today}));
 assert.equal(c.selectedPulseDate,today);assert.equal(renders,1);
 assert.deepEqual(Array.from(c.activityPayload.days,day=>day.date),[today]);
});

test('switching a month-end gapped window to gapless loads through Sunday in the next month',async()=>{
 const nodes=new Map(),requests=[];
 const c=context({pulseToday:'2026-11-30',trainingRequestVersion:0,
  activityPayload:{today:'2026-11-30',start:'2026-08-01',end:'2026-11-30',neighborDays:[{date:'2026-11-30'}]},
  $:s=>{if(!nodes.has(s))nodes.set(s,{value:s==='#activityMonth'?'2026-11':'month',setAttribute(){},removeAttribute(){}});return nodes.get(s);},
  clubApi:{request:async url=>{requests.push(url);return {ok:true,json:async()=>({days:[{date:'2026-12-06',records:[]}]})};}},
  renderTrainingActivity(){}});
 vm.runInContext(section('async function refreshActivityLayout()',"window.addEventListener('site-heatmap-layout-change'"),c);
 await c.refreshActivityLayout();
 assert.deepEqual(requests,['/api/training-activity?start=2026-12-01&end=2026-12-06']);
 assert.equal(c.activityPayload.end,'2026-12-06');
});
test('a newer dashboard date advances week and month limits despite an older heatmap',()=>{
 const c=context();
 c.pulseToday='2026-11-09';
 assert.equal(c.activityBrowseEnd({today:'2026-11-08'}),'2026-11-15');
 c.pulseToday='2026-12-01';
 assert.equal(c.activityCurrentMonthEnd({today:'2026-11-30'}),'2026-12-31');
 assert.equal(c.activityBrowseEnd({today:'2026-12-07'}),'2026-12-13');
});
test('switching from current-week to full-month layout requests only missing dates',async()=>{
 let renders=0;const requests=[],nodes=new Map();
 const c=context({trainingRequestVersion:0,activityPayload:{start:'2026-08-01',today:'2026-11-04',neighborDays:[{date:'2026-11-08'}]},
  $:s=>{if(!nodes.has(s))nodes.set(s,{value:s==='#activityMonth'?'2026-11':'month',setAttribute(){},removeAttribute(){}});return nodes.get(s);},
  clubApi:{request:async url=>{requests.push(url);return {ok:true,json:async()=>({days:[{date:'2026-11-30'}]})};}},
  loadTrainingActivity:()=>{throw Error('must not reload the full window');},renderTrainingActivity:()=>renders++});
 vm.runInContext(section('async function refreshActivityLayout()',"window.addEventListener('site-heatmap-layout-change'"),c);
 await c.refreshActivityLayout();assert.equal(renders,1);assert.equal(requests.length,0);
 c.document.documentElement.dataset.heatmapMonthGap='true';
 await c.refreshActivityLayout();assert.equal(requests.length,1);
 assert.match(requests[0],/start=2026-11-09&end=2026-11-30$/);
 assert.equal(c.activityPayload.neighborDays.length,2);
 await c.refreshActivityLayout();assert.equal(requests.length,1);assert.equal(renders,3);
});
test('right prefetch resumes immediately after a partial month without a missing date interval',async()=>{
 const requests=[];
 const c=context({activityPrefetch:null,activityPayload:{today:'2026-11-04',neighborDays:[{date:'2026-01-01'},{date:'2026-11-08'}]},
  $:()=>null,applyActivityPrefetch(){},clubApi:{request:async url=>{requests.push(url);return {ok:true,json:async()=>({days:[]})};}}});
 c.document.documentElement.dataset.heatmapMonthGap='true';
 vm.runInContext(section('async function prefetchActivityMonths(','function wirePulseAtlas('),c);
 await c.prefetchActivityMonths('2026-11');
 assert.equal(requests.length,1);
 assert.match(requests[0],/start=2026-11-09&end=2026-11-30$/);
});
function selectedContext() {
 const pending=[],selections=[],records={};
 const c=context({activityDayRequest:null,selectedPulseDate:'2026-06-10',pulseDays:[],
  activityPayload:{days:[{date:'2026-11-04'}]},$:()=>records,
  clubApi:{request:url=>new Promise(resolve=>pending.push({url,resolve}))},
  selectPulseDay:(date,options)=>selections.push({date,...options})});
 vm.runInContext(section('function updatePulseDay(','async function refreshActivityLayout('),c);
 return {c,pending,selections,records};
}
test('selected historical day loads independently without changing the heatmap window',async()=>{
 const {c,pending,selections}=selectedContext(),payload=c.activityPayload;
 const promise=c.loadActivitySelectedDay(c.selectedPulseDate);
 await c.loadActivitySelectedDay(c.selectedPulseDate);
 assert.equal(pending.length,1);
 assert.match(pending[0].url,/start=2026-06-10&end=2026-06-10$/);
 pending[0].resolve({ok:true,json:async()=>({days:[{date:'2026-06-10',ac:2,records:[]}]})});
 await promise;
 assert.equal(c.activityPayload,payload);assert.equal(c.activityPayload.days.length,1);
 assert.equal(c.pulseDays[0].ac,2);
 assert.deepEqual(selections,[{date:'2026-06-10',reveal:false}]);
});
test('an old selected-day response cannot replace a newer selection',async()=>{
 const {c,pending,selections}=selectedContext();
 const old=c.loadActivitySelectedDay(c.selectedPulseDate);
 c.selectedPulseDate='2026-06-11';
 const fresh=c.loadActivitySelectedDay(c.selectedPulseDate);
 pending[1].resolve({ok:true,json:async()=>({days:[{date:'2026-06-11',records:[]}]})});await fresh;
 pending[0].resolve({ok:true,json:async()=>({days:[{date:'2026-06-10',records:[]}]})});await old;
 assert.equal(selections.length,1);assert.equal(selections[0].date,'2026-06-11');
 assert.equal(c.pulseDays.length,1);
});
test('failed selected-day loading offers retry and a retry can complete',async()=>{
 const {c,pending,records,selections}=selectedContext();
 const first=c.loadActivitySelectedDay(c.selectedPulseDate);
 pending[0].resolve({ok:false,json:async()=>({error:'offline'})});await first;
 assert.match(records.innerHTML,/data-activity-day-retry/);assert.equal(c.activityDayRequest,null);
 const retry=c.loadActivitySelectedDay(c.selectedPulseDate,{force:true});
 pending[1].resolve({ok:true,json:async()=>({days:[{date:c.selectedPulseDate,records:[]}]})});await retry;
 assert.equal(selections.length,1);
});
test('cached selected-day records stay visible after browsing outside their month',()=>{
 const nodes=new Map();
 const c=context({activityPayload:{days:[]},selectedPulseDate:'2026-06-10',
  $:s=>{if(!nodes.has(s))nodes.set(s,{});return nodes.get(s);},$$:()=>[],
  escapeHtml:s=>s,uiProblemTitle:s=>s,activitySafeLink:()=>'',
  loadActivitySelectedDay:()=>{throw Error('cached records must not be requested again');}});
 c.document.body={classList:{contains:()=>false}};

 const day={date:'2026-06-10',ac:1,records:[{kind:'ac',title:'Historical problem'}]};c.activityStore.merge([day]);c.renderActivityDay(day);
 assert.match(nodes.get('#activityRecords').innerHTML,/Historical problem/);
 assert.doesNotMatch(nodes.get('#activityRecords').innerHTML,/正在加载/);
});
