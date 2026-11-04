const {prepare}=require('./activity-fixture.cjs');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
test('month arithmetic supports year boundaries',()=>{
 const c={};prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 assert.equal(c.shiftActivityMonth('2026-12',1),'2027-01');
 assert.equal(c.shiftActivityMonth('2026-01',-1),'2025-12');
 assert.deepEqual(Array.from(c.activityMonthBounds('2027-01')),['2026-10-01','2027-01-31']);
 assert.deepEqual(Array.from(c.activityMonthBounds('2028-02')),['2027-11-01','2028-02-29']);
});
test('neighbor months map to four-month window endings',()=>{
 const c={renderActivityMonths:()=>'',document:{documentElement:{dataset:{}}}};prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 const days=['07','08','09','10','11','12'].map(m=>({date:'2026-'+m+'-01'}));
 const html=c.renderActivitySlidingMonths({neighborDays:days,today:'2026-11-03'});
 assert.equal((html.match(/class="activity-slide-month"/g)||[]).length,5);
 assert.match(html,/data-window-end="2026-10"/);
 assert.match(html,/data-window-end="2026-11"/);
 assert.doesNotMatch(html,/data-window-end="2026-12"/);
});


function activityLoadState() {
 const nodes = new Map([
  ['#activityMonth', {value:'2026-11'}], ['#activityRange', {value:'month'}],
  ['#activityNote', {hidden:false,textContent:'Previous note'}], ['#activityRecords', {}],
  ['#activityHeatmap', {setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];}}]
 ]);
 let resolve;
 const response = new Promise(done => {resolve=done;});
 const requests=[];
 const c = {$:selector=>nodes.get(selector)||null, trainingRequestVersion:0,
  selectedPulseDate:'', activityPayload:null, pulseToday:'2026-11-04', clubApi:{request:url=>{requests.push(url);return response;}}, renderTrainingActivity(){}};
 prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 vm.runInContext(source.slice(source.indexOf('async function loadTrainingActivity('),source.indexOf("\n$('#activityMonth')?.addEventListener")),c);
 return {c,nodes,resolve,requests};
}

test('browsing another heatmap month keeps its loading note hidden without range buttons',async()=>{
 const {c,nodes,resolve}=activityLoadState();
 const pending=c.loadTrainingActivity();
 assert.equal(nodes.get('#activityNote').hidden,true);
 assert.equal(nodes.get('#activityNote').textContent,'');
 assert.equal(nodes.get('#activityHeatmap')['aria-busy'],'true');
 resolve({ok:true,json:async()=>({days:[],semester:null})});
 await pending;
 assert.equal(c.activityPayload.end,'2026-11-30');
 assert.equal(nodes.get('#activityHeatmap')['aria-busy'],undefined);
});

test('failed heatmap requests still display the error and offer retry',async()=>{
 const {c,nodes,resolve}=activityLoadState();
 const pending=c.loadTrainingActivity();
 resolve({ok:false,json:async()=>({error:'连接失败，请重试'})});
 await pending;
 assert.equal(nodes.get('#activityNote').hidden,false);
 assert.equal(nodes.get('#activityNote').textContent,'连接失败，请重试');
 assert.match(nodes.get('#activityHeatmap').innerHTML,/data-activity-retry/);
});


test('current month remains complete even if semester ends midmonth',async()=>{
 const {c,nodes,resolve}=activityLoadState();
 const pending=c.loadTrainingActivity();
 resolve({ok:true,json:async()=>({semester:{end:'2026-11-15'},days:
  ['2026-11-14','2026-11-15','2026-11-16','2026-12-01'].map(date=>({date}))})});
 await pending;
 assert.equal(c.activityPayload.end,'2026-11-30');
 assert.equal(nodes.get('#activityMonth').max,'2026-11');
 assert.deepEqual(Array.from(c.activityPayload.days,d=>d.date),['2026-11-14','2026-11-15','2026-11-16']);
 assert.deepEqual(Array.from(c.activityPayload.neighborDays,d=>d.date),['2026-11-14','2026-11-15','2026-11-16']);
});

test('future requests clamp to the current month',async()=>{
 const {c,nodes,resolve,requests}=activityLoadState();
 c.activityPayload={semester:{end:'2026-11-15'}};
 nodes.get('#activityMonth').value='2027-02';
 const pending=c.loadTrainingActivity();
 assert.equal(nodes.get('#activityMonth').value,'2026-11');
 assert.match(requests[0],/end=2026-11-30/);
 resolve({ok:true,json:async()=>({semester:{end:'2026-11-15'},days:[]})});
 await pending;
 assert.equal(c.activityPayload.end,'2026-11-30');
});

test('month picker disables months and years beyond today',()=>{
 const month={value:'2027-02'},popup={dataset:{}};
 const c={activityPayload:{today:'2027-02-03',semester:{end:'2027-12-14'}},$:selector=>selector==='#activityMonth'?month:popup};
 prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 c.renderActivityMonthPicker(2028);
 assert.equal(popup.dataset.year,2027);
 assert.match(popup.innerHTML,/data-month-value="2027-03" disabled/);
 assert.doesNotMatch(popup.innerHTML,/data-month-value="2027-02" disabled/);
 assert.match(popup.innerHTML,/aria-label="下一年" disabled/);
});


test('month stops allow a multi-month jump while requiring a complete window',()=>{
 const c={};prepare(c);vm.createContext(c);
 const entries=Array.from({length:14},(_,i)=>({month:i}));
 assert.deepEqual(Array.from(c.activityWindowStops(entries,4),v=>v.month),[3,4,5,6,7,8,9,10,11,12,13]);
});

test('wider viewports request more months with unchanged cell size',()=>{
 const track={clientWidth:320};
 const c={$:selector=>selector==='.activity-heat-scroll'?track:{},
  getComputedStyle:()=>({getPropertyValue:name=>name==='--activity-cell'?'12px':'4px'})};
 prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 const small=c.activityVisibleMonthCount();
 track.clientWidth=1200;
 const wide=c.activityVisibleMonthCount();
 assert.ok(wide>small);
 assert.ok(wide>4);
 assert.ok(c.activityMonthBounds('2027-02',wide)[0]<'2026-11-01');
 const ranges=c.activityRequestRanges('2025-01-01','2027-02-14');
 assert.equal(ranges[0][0],'2025-01-01');
 assert.equal(ranges.at(-1)[1],'2027-02-14');
 for(let i=0;i<ranges.length;i++){
  assert.ok((Date.parse(ranges[i][1])-Date.parse(ranges[i][0]))/86400000<365);
  if(i)assert.equal(Date.parse(ranges[i][0])-Date.parse(ranges[i-1][1]),86400000);
 }
});

test('visible month count is cached until viewport width changes',()=>{
 const track={clientWidth:600,dataset:{}};let cell=16;
 const c={$:selector=>selector==='.activity-heat-scroll'?track:{},getComputedStyle:()=>({getPropertyValue:name=>name==='--activity-cell'?String(cell):'4'})};prepare(c);vm.createContext(c);
 const count=c.activityVisibleMonthCount();cell=30;
 assert.equal(c.activityVisibleMonthCount(),count);
 track.clientWidth=300;assert.notEqual(c.activityVisibleMonthCount(),count);
});
test('initial buffer stops at the current month',async()=>{
 const {c,resolve,requests}=activityLoadState();const pending=c.loadTrainingActivity();
 assert.match(requests[0],/start=2026-03-01/);
 assert.match(requests.at(-1),/end=2026-11-30/);
 resolve({ok:true,json:async()=>({days:[],semester:null})});await pending;
});

test('month limit handles leap years and no semester',()=>{
 const c={};prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 assert.equal(c.activityCurrentMonthEnd({today:'2028-02-03'}),'2028-02-29');
 assert.equal(c.activityCurrentMonthEnd({today:'2026-12-01',semester:{end:'2027-06-30'}}),'2026-12-31');
});

for(const present of [false,true])test(`month rendering preserves selected date (cached=${present})`,()=>{
 const selected='2026-11-04',calls=[],nodes=new Map();
 const c={activityPayload:{days:[{date:'2026-08-31'}],neighborDays:present?[{date:selected}]:[{date:'2026-08-31'}],today:selected,end:'2026-08-31'},selectedPulseDate:selected,pulseDays:[],
 $:selector=>{if(!nodes.has(selector))nodes.set(selector,{dataset:{},value:'month'});return nodes.get(selector);},
 renderActivitySlidingMonths:()=>'',wireActivityHeatScroll(){},updatePulseDay(){},selectPulseDay:(date,options)=>calls.push({date,reveal:options.reveal})};
 prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function renderTrainingActivity('),source.indexOf('async function loadTrainingActivity(')),c);
 c.renderTrainingActivity();
 assert.equal(c.selectedPulseDate,selected);
 assert.deepEqual(calls,present?[{date:selected,reveal:false}]:[]);
});

test('gapless browsing stops at this Sunday, including month and year boundaries',()=>{
 const c={document:{documentElement:{dataset:{heatmapMonthGap:'false'}}}};prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 for(const [today,end] of [['2026-11-04','2026-11-08'],['2026-11-08','2026-11-08'],['2026-11-30','2026-12-06'],['2026-12-31','2027-01-03']])assert.equal(c.activityBrowseEnd({today}),end);
 c.document.documentElement.dataset.heatmapMonthGap='true';assert.equal(c.activityBrowseEnd({today:'2026-11-04'}),'2026-11-30');
});
