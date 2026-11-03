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
 const c={renderActivityMonths:()=>'',};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function shiftActivityMonth('),source.indexOf('function activityMonthBounds(')),c);
 const days=['07','08','09','10','11','12'].map(m=>({date:'2026-'+m+'-01'}));
 const html=c.renderActivitySlidingMonths({neighborDays:days,today:'2026-11-03'});
 assert.equal((html.match(/class="activity-slide-month"/g)||[]).length,6);
 assert.match(html,/data-window-end="2026-10"/);
 assert.match(html,/data-window-end="2026-11"/);
 assert.match(html,/data-window-end="2026-12"/);
});
