const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Store}=require('../activity-data.js');
const dates=require('../activity-dates.js');

function rows(start,end){
 const result=[];
 for(let date=start;date<=end;date=dates.shiftDate(date,1))result.push({date,ac:0,records:[]});
 return result;
}
test('all views share the same date object when a submission is removed',()=>{
 const store=new Store(()=>{});
 const [pulse]=store.merge([{date:'2026-11-04',submitted:true}],{details:false});
 assert.equal(store.detail(pulse.date),null);
 const [heatmap]=store.merge([{date:pulse.date,submitted:true,ac:1,records:[{kind:'ac'}]}]);
 assert.equal(pulse,heatmap);assert.equal(store.detail(pulse.date),pulse);
 store.merge([{date:pulse.date,submitted:false,hasSubmission:false,ac:0,records:[]}]);
 assert.equal(heatmap.ac,0);assert.deepEqual(pulse.records,[]);
 assert.equal(store.detail(pulse.date).hasSubmission,false);
});
test('loading overlapping windows requests only missing days and reuses complete dates',async()=>{
 const requests=[];
 const store=new Store(async url=>{
  requests.push(url);const p=new URL(url,'http://test').searchParams;
  return {ok:true,json:async()=>({today:'2026-11-04',semester:{name:'term'},days:rows(p.get('start'),p.get('end'))})};
 });
 const first=await store.load('2026-11-01','2026-11-04');
 const second=await store.load('2026-11-03','2026-11-08');
 assert.equal(requests.length,2);assert.match(requests[1],/start=2026-11-05&end=2026-11-08$/);
 assert.equal(first.days[2],second.days[0]);
 const cached=await store.load('2026-11-01','2026-11-08');
 assert.equal(requests.length,2);assert.equal(cached.days.length,8);assert.equal(cached.semester.name,'term');
});
test('refresh invalidates details and rejects old responses without replacing new data',async()=>{
 const pending=[];
 const store=new Store(()=>new Promise(resolve=>pending.push(resolve)));
 const [reference]=store.merge([{date:'2026-11-04',ac:2,records:[{}]}]);
 const old=store.load('2026-11-05','2026-11-05');
 store.invalidate();assert.equal(store.detail(reference.date),null);assert.equal(reference.records,undefined);
 const fresh=store.load('2026-11-05','2026-11-05');
 pending[1]({ok:true,json:async()=>({days:[{date:'2026-11-05',ac:0,records:[]}]})});await fresh;
 pending[0]({ok:true,json:async()=>({days:[{date:'2026-11-05',ac:99,records:[{}]}]})});
 await assert.rejects(old,/已过期/);assert.equal(store.detail('2026-11-05').ac,0);
 await store.load('2026-11-05','2026-11-05');assert.equal(pending.length,2);
});
test('missing ranges preserve internal gaps and the backend one-year limit',()=>{
 const store=new Store(()=>{});
 store.merge(rows('2026-01-03','2026-01-04'));
 assert.deepEqual(store.missing('2026-01-01','2026-01-06'),[['2026-01-01','2026-01-02'],['2026-01-05','2026-01-06']]);
 for(const [start,end] of store.missing('2023-01-01','2025-12-31'))assert.ok((Date.parse(end)-Date.parse(start))/86400000<365);
});
test('calendar module handles leap days and complete weeks across year boundaries',()=>{
 assert.equal(dates.shiftDate('2028-03-01',-1),'2028-02-29');
 assert.equal(dates.weekEnd('2026-12-31'),'2027-01-03');
 assert.deepEqual(dates.monthBounds('2028-02',1),['2028-02-01','2028-02-29']);
});
