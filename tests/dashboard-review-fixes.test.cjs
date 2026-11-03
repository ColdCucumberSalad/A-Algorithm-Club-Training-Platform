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
test('every bound account keeps its own statistics and sync status regardless of order',()=>{
 const rows=[{id:2,platform:'codeforces',account:'rated',snapshot:{rating:1800,solved:100},synced_at:'2026-11-04'},{id:3,platform:'codeforces',account:'pending',status:'pending'},{id:1,platform:'codeforces',account:'lower',snapshot:{rating:1500,solved:42}}];
 for(const bindings of [rows,[...rows].reverse()]){
 const html=render(bindings),cards=html.match(/<article[\s\S]*?<\/article>/g);
 assert.equal(cards.length,3);
 assert.match(cards.find(card=>card.includes('>pending<')),/\u540c\u6b65\u4e2d/);
 assert.doesNotMatch(cards.find(card=>card.includes('>rated<')),/\u540c\u6b65\u4e2d/);
 assert.match(cards.find(card=>card.includes('>rated<')),/1,800/);
 assert.match(cards.find(card=>card.includes('>rated<')),/>100</);
 assert.match(cards.find(card=>card.includes('>lower<')),/1,500/);
 assert.match(cards.find(card=>card.includes('>lower<')),/>42</);
 assert.doesNotMatch(cards.find(card=>card.includes('>pending<')),/1,800|1,500/);
 }
});
test('unbound platforms still show one empty summary',()=>{
 const html=render([]);assert.equal((html.match(/dashboard-platform-card/g)||[]).length,1);
});
test('binding account names are escaped before rendering',()=>{
 const target={},c={$:()=>target,escapeHtml:s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;')};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function renderDashboardPlatforms('),source.indexOf('async function loadDashboardPlatforms(')),c);
 c.renderDashboardPlatforms({platforms:{codeforces:{name:'Codeforces'}},bindings:[{platform:'codeforces',account:'<script>bad</script>'}]});
 assert.doesNotMatch(target.innerHTML,/<script>/);assert.match(target.innerHTML,/&lt;script&gt;/);
});
