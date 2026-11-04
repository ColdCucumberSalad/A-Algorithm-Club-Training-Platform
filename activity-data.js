/* One canonical object per date. Views hold references, never independent copies. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./activity-dates.js'));
  else root.ActivityData=factory(root.ActivityDates);
})(globalThis,(dates)=>{
class Store {
  constructor(request){this.request=request;this.days=new Map();this.loaded=new Set();this.pending=new Map();this.epoch=0;this.metadata={};}
  get(date){return this.days.get(date);}
  detail(date){return this.loaded.has(date)?this.get(date):null;}
  merge(rows,{details=true}={}){
    return rows.map(row=>{
      let cached=this.days.get(row.date);
      if(!cached){cached={date:row.date};this.days.set(row.date,cached);}
      Object.assign(cached,row);
      if(details&&Array.isArray(row.records))this.loaded.add(row.date);
      return cached;
    });
  }
  invalidate(){
    this.epoch++;this.pending.clear();this.loaded.clear();this.metadata={};
    for(const day of this.days.values())delete day.records;
  }
  missing(start,end){
    const ranges=[];let first=null;
    for(let date=start;date<=end;date=dates.shiftDate(date,1)){
      if(!this.loaded.has(date)){first ||= date;}
      else if(first){ranges.push(...dates.requestRanges(first,dates.shiftDate(date,-1)));first=null;}
    }
    if(first)ranges.push(...dates.requestRanges(first,end));
    return ranges;
  }
  fetch(start,end){
    const key=`${start}/${end}`;
    if(this.pending.has(key))return this.pending.get(key);
    const epoch=this.epoch;
    const pending=(async()=>{
      const response=await this.request(`/api/training-activity?start=${start}&end=${end}`);
      const payload=await response.json();
      if(!response.ok)throw new Error(payload.error||'训练活动加载失败');
      if(epoch!==this.epoch)throw new Error('训练活动请求已过期');
      const {days,...metadata}=payload;
      this.merge(days);
      for(const day of days)this.loaded.add(day.date);
      this.metadata={...this.metadata,...metadata};
      return payload;
    })();
    this.pending.set(key,pending);
    const release=()=>{if(this.pending.get(key)===pending)this.pending.delete(key);};
    pending.then(release,release);
    return pending;
  }
  async load(start,end){
    const epoch=this.epoch;
    await Promise.all(this.missing(start,end).map(([from,to])=>this.fetch(from,to)));
    if(epoch!==this.epoch)throw new Error('训练活动请求已过期');
    const days=[...this.days.values()].filter(day=>this.loaded.has(day.date)&&day.date>=start&&day.date<=end).sort((a,b)=>a.date.localeCompare(b.date));
    return {...this.metadata,start,end,days};
  }
}
return {Store};
});
