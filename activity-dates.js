/* Calendar-only operations; ISO dates are calculated independently of browser timezone. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ActivityDates=factory();})(globalThis,()=>{
function shiftMonth(month, offset) {
  const [year,m]=month.split('-').map(Number),date=new Date(year,m-1+offset,1);
  return date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0');
}
function shiftDate(date, offset) {
  const value=new Date(date+'T12:00:00Z');value.setUTCDate(value.getUTCDate()+offset);
  return value.toISOString().slice(0,10);
}
function monthBounds(month, count=4) {
  const [year, m] = month.split('-').map(Number);
  const first=new Date(year,m-count,1);
  const start=first.getFullYear()+'-'+String(first.getMonth()+1).padStart(2,'0')+'-01';
  return [start, month+'-'+new Date(year,m,0).getDate()];
}
function requestRanges(start,end){
  const last=Date.parse(end+'T00:00:00Z'),day=86400000,ranges=[];
  for(let cursor=Date.parse(start+'T00:00:00Z');cursor<=last;cursor+=365*day){
    ranges.push([new Date(cursor).toISOString().slice(0,10),new Date(Math.min(last,cursor+364*day)).toISOString().slice(0,10)]);
  }
  return ranges;
}
function weekEnd(today){const day=new Date(today+'T12:00:00Z');return shiftDate(today,(7-day.getUTCDay())%7);}
return {shiftMonth,shiftDate,monthBounds,requestRanges,weekEnd};
});
