const {prepare}=require('./activity-fixture.cjs');
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
test('gapless sliding months share ten columns for October-November and keep exact month anchors',()=>{
 const c={document:{documentElement:{dataset:{heatmapMonthGap:'false'}}},selectedPulseDate:''};prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf("\n$('#activityMonthPopover')?.addEventListener")),c);
 const days=[];for(let d=new Date('2026-10-01Z');d<=new Date('2026-11-30Z');d.setUTCDate(d.getUTCDate()+1))days.push({date:d.toISOString().slice(0,10),ac:0});
 const html=c.renderActivitySlidingMonths({neighborDays:days,today:'2026-11-30'});
 assert.match(html,/--heat-weeks:10/);assert.equal((html.match(/class="activity-heat-grid"/g)||[]).length,1);
 assert.doesNotMatch(html,/class="activity-slide-month"/);assert.equal((html.match(/class="activity-heat-cell/g)||[]).length,61);
 assert.match(html,/data-activity-date="2026-10-31" data-window-end="2026-10"/);
 const partial=c.renderActivitySlidingMonths({neighborDays:days,semester:{end:'2026-11-15'},today:'2026-11-30'});
 assert.match(partial,/data-activity-date="2026-11-30" data-window-end="2026-11"/);
 assert.equal((html.match(/<span aria-hidden="true"><\/span>/g)||[]).length,9,'leading and trailing blanks fill ten whole weeks');
});
function render(bindings){const target={};const c={$:()=>target,escapeHtml:String};prepare(c);vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function renderDashboardPlatforms('),source.indexOf('async function loadDashboardPlatforms(')),c);c.renderDashboardPlatforms({platforms:{codeforces:{name:'Codeforces'}},bindings});return target.innerHTML;}
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
 const target={},c={$:()=>target,escapeHtml:s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;')};prepare(c);vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function renderDashboardPlatforms('),source.indexOf('async function loadDashboardPlatforms(')),c);
 c.renderDashboardPlatforms({platforms:{codeforces:{name:'Codeforces'}},bindings:[{platform:'codeforces',account:'<script>bad</script>'}]});
 assert.doesNotMatch(target.innerHTML,/<script>/);assert.match(target.innerHTML,/&lt;script&gt;/);
});
