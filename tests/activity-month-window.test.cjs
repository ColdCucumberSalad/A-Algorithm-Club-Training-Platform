const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
test('monthly swipe advances one month across year boundaries',()=>{
 const c={};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf('function renderActivityMonthPicker(')),c);
 assert.equal(c.shiftActivityMonth('2026-12',1),'2027-01');
 assert.equal(c.shiftActivityMonth('2026-01',-1),'2025-12');
 assert.deepEqual(Array.from(c.activityMonthBounds('2027-01')),['2026-10-01','2027-01-31']);
 assert.deepEqual(Array.from(c.activityMonthBounds('2028-02')),['2027-11-01','2028-02-29']);
});
test('neighbor months map to four-month window endings',()=>{
 const c={renderActivityMonths:()=>'',document:{documentElement:{dataset:{}}}};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf('function activityMonthBounds(')),c);
 const days=['07','08','09','10','11','12'].map(m=>({date:'2026-'+m+'-01'}));
 const html=c.renderActivitySlidingMonths({neighborDays:days,today:'2026-11-03'});
 assert.equal((html.match(/class="activity-slide-month"/g)||[]).length,6);
 assert.match(html,/data-window-end="2026-10"/);
 assert.match(html,/data-window-end="2026-11"/);
 assert.match(html,/data-window-end="2026-12"/);
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
  activityPayload:null, pulseToday:'2026-11-04', clubApi:{request:url=>{requests.push(url);return response;}}, renderTrainingActivity(){}};
 vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf('function renderActivityMonthPicker(')),c);
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


test('semester ending midmonth clips both visible and prefetched heatmap dates',async()=>{
 const {c,nodes,resolve}=activityLoadState();
 const pending=c.loadTrainingActivity();
 resolve({ok:true,json:async()=>({semester:{end:'2026-11-15'},days:
  ['2026-11-14','2026-11-15','2026-11-16','2026-12-01'].map(date=>({date}))})});
 await pending;
 assert.equal(c.activityPayload.end,'2026-11-15');
 assert.equal(nodes.get('#activityMonth').max,'2026-11');
 assert.deepEqual(Array.from(c.activityPayload.days,d=>d.date),['2026-11-14','2026-11-15']);
 assert.deepEqual(Array.from(c.activityPayload.neighborDays,d=>d.date),['2026-11-14','2026-11-15']);
});

test('requests past the semester end clamp to the final month and exact end day',async()=>{
 const {c,nodes,resolve,requests}=activityLoadState();
 c.activityPayload={semester:{end:'2026-11-15'}};
 nodes.get('#activityMonth').value='2027-02';
 const pending=c.loadTrainingActivity();
 assert.equal(nodes.get('#activityMonth').value,'2026-11');
 assert.match(requests[0],/end=2026-11-15/);
 resolve({ok:true,json:async()=>({semester:{end:'2026-11-15'},days:[]})});
 await pending;
 assert.equal(c.activityPayload.end,'2026-11-15');
});

test('month picker disables months and years beyond the semester end',()=>{
 const month={value:'2027-02'},popup={dataset:{}};
 const c={activityPayload:{semester:{end:'2027-02-14'}},$:selector=>selector==='#activityMonth'?month:popup};
 vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function renderActivityMonthPicker('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 c.renderActivityMonthPicker(2028);
 assert.equal(popup.dataset.year,2027);
 assert.match(popup.innerHTML,/data-month-value="2027-03" disabled/);
 assert.doesNotMatch(popup.innerHTML,/data-month-value="2027-02" disabled/);
 assert.match(popup.innerHTML,/aria-label="下一年" disabled/);
});


test('partial final month snaps its last grid to the right edge without resizing cells',()=>{
 let snap,loads=0;
 const month={value:'2027-01'},range={value:'month'};
 const weeks=[5,5,6,5,5,2],cell=12,gap=4;
 const widths=weeks.map((n,i)=>n*cell+(n-1)*gap+(i===weeks.length-1?0:12));
 const track={dataset:{},scrollLeft:0,clientWidth:372,scrollWidth:widths.reduce((a,b)=>a+b,0),
  classList:{toggle(){}},scrollTo({left}){this.scrollLeft=Math.min(left,this.scrollWidth-this.clientWidth);},
  querySelectorAll(){return items;}};
 const months=['2026-09','2026-10','2026-11','2026-12','2027-01','2027-02'];
 const items=weeks.map((n,i)=>({dataset:{windowEnd:months[i]},
  querySelector(){return {getBoundingClientRect(){return {right:widths.slice(0,i).reduce((a,b)=>a+b,0)+n*cell+(n-1)*gap-track.scrollLeft};}};},
  getBoundingClientRect(){return {left:widths.slice(0,i).reduce((a,b)=>a+b,0)-track.scrollLeft,width:widths[i]};}
 }));
 const c={$:selector=>selector==='.activity-heat-scroll'?track:selector==='#activityMonth'?month:range,
  activityPayload:{neighborDays:[],semester:{end:'2027-02-14'}},requestAnimationFrame:fn=>fn(),
  loadTrainingActivity(){loads++;},wireHorizontalDateScroll(t,selector,options){snap=options.snap;return ()=>{};}};
 vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf('function renderActivitySlidingMonths(')),c);
 vm.runInContext(source.slice(source.indexOf('let refreshActivityHeatScroll;'),source.indexOf('function wirePulseAtlas(')),c);
 c.wireActivityHeatScroll();
 track.scrollLeft=track.scrollWidth-track.clientWidth;
 snap();
 assert.equal(month.value,'2027-02');
 assert.equal(loads,1);
 assert.equal(track.clientWidth,372);
 assert.equal(track.scrollLeft,track.scrollWidth-track.clientWidth);
 snap();
 assert.equal(loads,1,'resting at the final edge does not reload again');
 track.clientWidth=650;
 snap();snap();
 assert.equal(month.value,'2027-02','resizing preserves the selected month while data reloads');
 assert.equal(loads,2,'a resize queues only one request for the new width');
});

test('wider viewports request more months with unchanged cell size',()=>{
 const track={clientWidth:320};
 const c={$:selector=>selector==='.activity-heat-scroll'?track:{},
  getComputedStyle:()=>({getPropertyValue:name=>name==='--activity-cell'?'12px':'4px'})};
 vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf('function renderActivityMonthPicker(')),c);
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
