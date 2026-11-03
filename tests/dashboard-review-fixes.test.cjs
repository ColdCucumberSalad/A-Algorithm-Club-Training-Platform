const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
test('gapless sliding months share ten columns for October-November and keep exact month anchors',()=>{
 const c={document:{documentElement:{dataset:{heatmapMonthGap:'false'}}},selectedPulseDate:''};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function renderActivitySlidingMonths('),source.indexOf('function activityVisibleMonthCount(')),c);
 vm.runInContext(source.slice(source.indexOf('function renderActivityMonths('),source.indexOf("window.addEventListener('site-heatmap-layout-change'")),c);
 const days=[];for(let d=new Date('2026-10-01Z');d<=new Date('2026-11-30Z');d.setUTCDate(d.getUTCDate()+1))days.push({date:d.toISOString().slice(0,10),ac:0});
 const html=c.renderActivitySlidingMonths({neighborDays:days,today:'2026-11-04'});
 assert.match(html,/--heat-weeks:10/);assert.equal((html.match(/class="activity-heat-grid"/g)||[]).length,1);
 assert.doesNotMatch(html,/class="activity-slide-month"/);assert.equal((html.match(/class="activity-heat-cell/g)||[]).length,61);
 assert.match(html,/data-activity-date="2026-10-31" data-window-end="2026-10"/);
 const partial=c.renderActivitySlidingMonths({neighborDays:days,semester:{end:'2026-11-15'},today:'2026-11-04'});
 assert.match(partial,/data-activity-date="2026-11-15" data-window-end="2026-11"/);assert.doesNotMatch(partial,/2026-11-16/);
});
test('continuous month-end cells align to the right and snap to the next month',()=>{
 let snap,loads=0;const month={value:'2026-10'},range={value:'month'};
 const track={dataset:{},clientWidth:200,scrollWidth:500,scrollLeft:0,classList:{toggle(){}},querySelectorAll:()=>items,scrollTo({left}){this.scrollLeft=left;}};
 const grid={getBoundingClientRect:()=>({left:-track.scrollLeft})};
 const items=['2026-10','2026-11'].map((value,i)=>({dataset:{windowEnd:value,activityDate:value+'-30'},parentElement:grid,getBoundingClientRect:()=>({right:400+i*100-track.scrollLeft})}));
 const c={$:s=>s==='.activity-heat-scroll'?track:s==='#activityMonth'?month:range,activityPayload:{neighborDays:[],semester:{end:'2026-11-15'}},requestAnimationFrame:fn=>fn(),loadTrainingActivity(){loads++;},wireHorizontalDateScroll(t,s,o){snap=o.snap;return ()=>{};}};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf('function renderActivitySlidingMonths(')),c);
 vm.runInContext(source.slice(source.indexOf('let refreshActivityHeatScroll;'),source.indexOf('function wirePulseAtlas(')),c);
 c.wireActivityHeatScroll();assert.equal(track.scrollLeft,200);track.scrollLeft=300;snap();assert.equal(month.value,'2026-11');assert.equal(loads,1);assert.equal(track.scrollLeft,300);
});
function render(bindings){const target={};const c={$:()=>target,escapeHtml:String};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function renderDashboardPlatforms('),source.indexOf('async function loadDashboardPlatforms(')),c);c.renderDashboardPlatforms({platforms:{codeforces:{name:'Codeforces'}},bindings});return target.innerHTML;}
test('multiple bindings select highest rating instead of a new pending account in either response order',()=>{
 const rows=[{id:2,platform:'codeforces',account:'rated',snapshot:{rating:1800,solved:100},synced_at:'2026-11-04'},{id:3,platform:'codeforces',account:'pending',status:'pending'},{id:1,platform:'codeforces',account:'lower',snapshot:{rating:1500}}];
 for(const bindings of [rows,[...rows].reverse()]){const html=render(bindings);assert.match(html,/rated/);assert.match(html,/1,800/);assert.match(html,/>100</);assert.doesNotMatch(html,/pending/);}
});
test('numeric ratings follow ranking tie breaks and ignore boolean or negative ratings',()=>{
 const rows=[{id:5,platform:'codeforces',account:'newer',snapshot:{rating:1900}},{id:2,platform:'codeforces',account:'older',snapshot:{rating:'1900'}},{id:1,platform:'codeforces',account:'invalid',snapshot:{rating:true}},{id:6,platform:'codeforces',account:'negative',snapshot:{rating:-1}}];
 assert.match(render(rows),/older/);assert.doesNotMatch(render(rows),/newer/);
});
test('unrated platforms prefer synced accounts and unbound platforms retain empty state',()=>{
 assert.match(render([{id:2,platform:'codeforces',account:'synced',synced_at:'2026-11-04',snapshot:{solved:10}},{id:1,platform:'codeforces',account:'pending',status:'pending'}]),/synced/);
 assert.match(render([]),/dashboard-platform-card/);
});
