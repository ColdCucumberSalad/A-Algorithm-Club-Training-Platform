/* Heatmap rendering and scrolling. Selection is read-only; browsing updates only the window. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ActivityView=factory();})(globalThis,()=>{
function create(env,platform=globalThis){
const {$,$$}=env;
const {document,getComputedStyle,ResizeObserver,requestAnimationFrame,cancelAnimationFrame,matchMedia,setTimeout,clearTimeout}=platform;
let refreshActivityHeatScroll;
function renderActivitySlidingMonths(data){
  const months=new Map();
  const browseEnd=env.activityBrowseEnd(data);
  for(const day of data.neighborDays||data.days){if(day.date>browseEnd)continue;const key=day.date.slice(0,7);if(!months.has(key))months.set(key,[]);months.get(key).push(day);}
  if(document.documentElement.dataset.heatmapMonthGap==='false'){
    const days=[...months.values()].flat();
    const endings=new Map([...months].map(([month,items])=>[items.at(-1).date,month]));
    return renderActivityMonths(days,'ac','题',data.today).replace(/data-activity-date="([^"]+)"/g,(attribute,date)=>
      endings.has(date)?`${attribute} data-window-end="${endings.get(date)}"`:attribute);
  }
  return `<div class="activity-sliding-months">${[...months].map(([month,days])=>`<div class="activity-slide-month" data-window-end="${month}">${renderActivityMonths(days,'ac','题',data.today)}</div>`).join('')}</div>`;
}
function activityVisibleMonthCount() {
  const track=$('.activity-heat-scroll');
  if(!track?.clientWidth)return 4;
  if(track.dataset?.monthCountWidth===String(track.clientWidth))return Number(track.dataset.monthCount);
  const style=getComputedStyle($('#activityHeatmap'));
  const originalSize=Math.min(28,Math.max(10,((track.parentElement?.clientWidth||track.clientWidth)-130)/22));
  const cell=parseFloat(style.getPropertyValue('--activity-cell'))||originalSize;
  const gap=parseFloat(style.getPropertyValue('--activity-gap'))||4;
  // Consecutive months share the available space; do not reserve six weeks for each.
  const count=Math.max(1,Math.floor((track.clientWidth+12)/(5.5*cell+4.5*gap+12)));
  if(track.dataset){track.dataset.monthCountWidth=String(track.clientWidth);track.dataset.monthCount=String(count);}
  return count;
}
function renderActivityMonthPicker(year){
  const maxMonth=env.activityCurrentMonthEnd(env.activityPayload).slice(0,7);
  const maxYear=maxMonth?Number(maxMonth.slice(0,4)):2199;
  year=Math.min(year,maxYear);
  const selected=$('#activityMonth').value;
  const popup=$('#activityMonthPopover');
  popup.dataset.year=year;
  popup.innerHTML=`<div class="activity-month-picker-heading"><button type="button" data-month-year="${year-1}" aria-label="上一年" ${year<=2001?'disabled':''}>‹</button><strong>${year} 年</strong><button type="button" data-month-year="${year+1}" aria-label="下一年" ${year>=maxYear?'disabled':''}>›</button></div><div class="activity-month-picker-grid">${Array.from({length:12},(_,i)=>{const value=year+'-'+String(i+1).padStart(2,'0');return `<button type="button" data-month-value="${value}" ${maxMonth&&value>maxMonth?'disabled':''} aria-pressed="${value===selected}">${i+1}月</button>`;}).join('')}</div>`;
}
function activitySafeLink(url){try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)?u.href:'';}catch(_){return '';}}
function renderActivityDay(day) {
  const container=$('#activityRecords');if(!container)return;
  const record=env.activityStore.detail(day.date);
  const rows=(record?.records||[]).filter(r=>r.kind==='ac');
  const count=record?.ac||0;
  const dateLabel=day.date===env.pulseToday?'今日':'当日';
  const hasSubmission=Boolean(record?.hasSubmission||record?.daily>0);
  $('#pulseFocus').textContent=`${day.date} · AC 题目 ${count} 题`;
  container.innerHTML=rows.length?rows.map((r,index)=>{const url=activitySafeLink(r.url);return `<div class="activity-record"><div><small>第${index+1}题</small>${url?`<a href="${env.escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${env.escapeHtml(env.uiProblemTitle(r.title))} <span aria-hidden="true">↗</span></a>`:`<strong>${env.escapeHtml(env.uiProblemTitle(r.title))}</strong>`}</div><span class="activity-record-check" aria-label="已记录">✓</span></div>`;}).join(''):`<p class="activity-empty">${day.date>env.pulseToday?'这一天还未到来。':!record?'正在加载当天记录…':hasSubmission?`${dateLabel}已有提交，暂无已确认的 AC 记录。`:`${dateLabel}没有提交`}${record?.checkedIn&&!hasSubmission?' 已签到，尚未提交题目。':''}</p>`;
  const submit=$('#activitySubmit'),primary=$('#openSubmission');
  submit.hidden=!primary||primary.hidden||document.body.classList.contains('site-admin-mode');
  submit.disabled=false;submit.textContent='查看历史提交';
  $$('#activityHeatmap [data-activity-date]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.activityDate===day.date));});
  if(!record&&day.date<=env.pulseToday)env.loadActivitySelectedDay(day.date);
}
function renderActivityMonths(days,metric,unit,today){
  if(document.documentElement.dataset.heatmapMonthGap==='false'){
    if(!days.length)return '';
    const offset=(new Date(days[0].date+'T12:00:00').getDay()+6)%7;
    const weeks=Math.ceil((offset+days.length)/7);
    const blanks=Array.from({length:offset},()=>'<span aria-hidden="true"></span>').join('');
    const captions=[];
    let previousCaptionColumn=0;
    const cells=days.map((day,index)=>{
      if(index===0||day.date.slice(0,7)!==days[index-1].date.slice(0,7)){
        const column=Math.max(previousCaptionColumn+1,Math.floor((offset+index)/7)+1);
        previousCaptionColumn=column;
        captions.push(`<span style="grid-column:${column};grid-row:1">${Number(day.date.slice(5,7))}月</span>`);
      }
      const n=day[metric],level=n===0?0:Math.min(4,Math.ceil(Math.log2(n+1)));
      return `<button type="button" class="activity-heat-cell${day.isToday?' is-today':''}" data-activity-date="${day.date}" data-level="${level}" aria-pressed="${day.date===env.selectedPulseDate}" aria-label="${day.date}，${n}${unit}${day.date>today?'，未来日期':''}" title="${day.date} · ${n} ${unit}"></button>`;
    }).join('');
    const tail=Array.from({length:weeks*7-offset-days.length},()=>'<span aria-hidden="true"></span>').join('');
    return `<div class="activity-continuous-months" style="--heat-weeks:${weeks}"><div class="activity-heat-grid">${blanks}${cells}${tail}</div><div class="activity-continuous-captions">${captions.join('')}</div></div>`;
  }
  const months=new Map();
  for(const day of days){const key=day.date.slice(0,7);if(!months.has(key))months.set(key,[]);months.get(key).push(day);}
  return `<div class="activity-month-sections">${[...months].map(([month,items])=>{
    const offset=(new Date(items[0].date+'T12:00:00').getDay()+6)%7;
    const weeks=Math.ceil((offset+items.length)/7);
    const blanks=Array.from({length:offset},()=>'<span aria-hidden="true"></span>').join('');
    return `<section class="activity-month-section" aria-label="${month}" style="--heat-weeks:${weeks}"><div class="activity-heat-grid">${blanks}${items.map(day=>{
      const n=day[metric],level=n===0?0:Math.min(4,Math.ceil(Math.log2(n+1)));
      return `<button type="button" class="activity-heat-cell${day.isToday?' is-today':''}" data-activity-date="${day.date}" data-level="${level}" aria-pressed="${day.date===env.selectedPulseDate}" aria-label="${day.date}，${n}${unit}${day.date>today?'，未来日期':''}" title="${day.date} · ${n} ${unit}"></button>`;
    }).join('')}</div><div class="activity-month-caption">${Number(month.slice(5))}月</div></section>`;
  }).join('')}</div>`;
}
function wireHorizontalDateScroll(track, itemSelector, options = {}) {
  if (!track || track.dataset.scrollWired) return;
  track.dataset.scrollWired = 'true';
  let drag = null, frame = 0, suppressClick = false, settleTimer = 0, settling = false;
  let touch = null, scrollFrame = 0;
  const contacts = new Set();
  const scheduleSnap = () => {
    if (settling) return;
    clearTimeout(settleTimer);
    if (!contacts.size && !drag) settleTimer = setTimeout(snap, 200);
  };
  const snap = () => {
    if (settling || contacts.size || drag || !track.clientWidth) return;
    track.dataset.interacting='false';
    clearTimeout(settleTimer);
    if(options.snap?.(track))return;
    const maxLeft = track.scrollWidth-track.clientWidth;
    // Keep the right edge reachable when the final month is narrower than the viewport.
    if (track.scrollLeft >= maxLeft-1) return;
    const items = [...track.querySelectorAll(itemSelector)];
    const origin = items[0]?.getBoundingClientRect().left || 0;
    const stops = items.map(item => item.getBoundingClientRect().left-origin);
    // Align the first partially visible date/month without changing the selection.
    const first = stops.filter(left => left <= track.scrollLeft+1).at(-1);
    if (first === undefined) return;
    const left = Math.min(first, maxLeft);
    if (Math.abs(left-track.scrollLeft) < 1) return;
    settling = true;
    track.scrollTo({left, behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    settleTimer = setTimeout(() => { settling = false; }, 500);
  };
  const paint = () => {
    frame = 0;
    if (drag?.active) track.scrollLeft = drag.scrollLeft+drag.x-drag.latestX;
  };
  const finish = event => {
    if (!drag || event.pointerId !== drag.id) return;
    cancelAnimationFrame(frame); frame = 0;
    const state = drag;
    if (state.active) {
      paint();
      suppressClick = true;
      event.preventDefault();
    }
    drag = null;
    track.classList.remove('is-dragging');
    if (track.hasPointerCapture(state.id)) track.releasePointerCapture(state.id);
    // Let ordinary clicks finish before a pending prefetch can rebuild the grid.
    if (state.active && event.type === 'pointerup') snap();
    else scheduleSnap();
  };
  // Touch scrolling belongs to the browser, including momentum and direction locking.
  // A pointercancel during native panning does not mean the finger has lifted.
  track.addEventListener('touchstart', event => {
    track.dataset.interacting='true';
    clearTimeout(settleTimer); settling = false; suppressClick = false;
    track.scrollTo({left:track.scrollLeft,behavior:'instant'});
    for (const contact of event.changedTouches) contacts.add(contact.identifier);
    const first = event.touches[0];
    touch = first ? {id:first.identifier,x:first.clientX,y:first.clientY} : null;
  }, {passive:true});
  track.addEventListener('touchmove', event => {
    const current = [...event.touches].find(contact => contact.identifier === touch?.id);
    if (current && Math.hypot(current.clientX-touch.x,current.clientY-touch.y) > 6) suppressClick = true;
  }, {passive:true});
  const finishTouch = event => {
    for (const contact of event.changedTouches) contacts.delete(contact.identifier);
    if (!contacts.size) { touch = null; scheduleSnap(); }
  };
  track.addEventListener('touchend', finishTouch, {passive:true});
  track.addEventListener('touchcancel', finishTouch, {passive:true});
  track.addEventListener('pointerdown', event => {
    if (event.pointerType === 'touch' || track.scrollWidth <= track.clientWidth+1) return;
    if (event.button !== 0 || event.isPrimary === false || drag) return;
    track.dataset.interacting='true';
    clearTimeout(settleTimer); settling = false; suppressClick = false;
    track.scrollTo({left:track.scrollLeft,behavior:'instant'});
    drag = {id:event.pointerId,x:event.clientX,y:event.clientY,latestX:event.clientX,scrollLeft:track.scrollLeft,active:false};
  });
  track.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    const distance = Math.abs(event.clientX-drag.x), cross = Math.abs(event.clientY-drag.y);
    if (!drag.active) {
      if (cross > 6 && cross > distance) { drag = null; scheduleSnap(); return; }
      if (distance < 6) return;
      drag.active = true;
      track.classList.add('is-dragging');
      track.setPointerCapture(drag.id);
    }
    event.preventDefault();
    drag.latestX = event.clientX;
    if (!frame) frame = requestAnimationFrame(paint);
  }, {passive:false});
  track.addEventListener('pointerup', finish);
  track.addEventListener('pointercancel', finish);
  track.addEventListener('pointerleave', event => {if(drag&&!drag.active)finish(event);});
  track.addEventListener('lostpointercapture', event => {if (event.target === track) finish(event);});
  track.addEventListener('scroll', () => {
    track.dataset.interacting='true';
    if(options.scroll&&!scrollFrame)scrollFrame=requestAnimationFrame(()=>{scrollFrame=0;options.scroll(track);});
    scheduleSnap();
  }, {passive:true});
  track.addEventListener('scrollend', () => {
    if (!settling) snap();
  }, {passive:true});
  const refresh = () => {
    track.classList.toggle('is-scrollable',track.scrollWidth > track.clientWidth+1);
    if (!track.clientWidth) return;
    if (track.dataset.resetScroll) {
      track.scrollLeft = track.scrollWidth-track.clientWidth;
      delete track.dataset.resetScroll;
    } else snap();
  };
  new ResizeObserver(refresh).observe(track);
  track.addEventListener('click', event => {
    if (suppressClick) {
      suppressClick = false;
      if (event.detail > 0) {event.preventDefault();event.stopImmediatePropagation();return;}
    }
  }, {capture:true});
  return refresh;
}

function activityWindowStops(items, count) {
  return items.slice(count - 1);
}
function updateActivityWindow(month) {
  const data=env.activityPayload;
  const [start,end]=env.activityMonthBounds(month,activityVisibleMonthCount());
  data.start=start;data.end=end>env.activityBrowseEnd(data)?env.activityBrowseEnd(data):end;
  data.days=data.neighborDays.filter(day=>day.date>=start&&day.date<=data.end);
  $('#activityMonth').value=month;
  $('#activityPeriod').textContent='截至 '+month.replace('-',' 年 ')+' 月';
}
function updateActivityEdgeVisibility(track) {
  const geometry=activityScrollGeometry(track);
  const left=track.scrollLeft+geometry.paddingLeft+.5,right=track.scrollLeft+track.clientWidth-geometry.paddingRight-.5;
  const cells=geometry.cells;
  // Cached positions are sorted by column. Scrolling only changes cells entering
  // or leaving the viewport; it never measures every day's rectangle again.
  const lowerBound=(value,key)=>{
    let low=0,high=cells.length;
    while(low<high){const mid=(low+high)>>>1;if(cells[mid][key]<=value)low=mid+1;else high=mid;}
    return low;
  };
  const first=lowerBound(left,'right'),end=lowerBound(right-.001,'left');
  const visible=new Set(cells.slice(first,end).map(item=>item.cell));
  if(!geometry.visible){for(const {cell} of cells)cell.style.visibility=visible.has(cell)?'':'hidden';}
  else{
    for(const cell of geometry.visible)if(!visible.has(cell))cell.style.visibility='hidden';
    for(const cell of visible)if(!geometry.visible.has(cell))cell.style.visibility='';
  }
  geometry.visible=visible;
}
function activityScrollGeometry(track) {
  if(track.activityGeometry?.width===track.clientWidth)return track.activityGeometry;
  const rect=track.getBoundingClientRect(),style=getComputedStyle(track),offset=track.scrollLeft-rect.left;
  const cells=[...track.querySelectorAll('.activity-heat-grid > *')].map(cell=>{
    const bounds=cell.getBoundingClientRect();return {cell,left:bounds.left+offset,right:bounds.right+offset};
  }).sort((a,b)=>a.left-b.left);
  const entries=[...track.querySelectorAll('[data-window-end]')];
  const first=entries[0],origin=first?(first.dataset.activityDate?first.parentElement:first).getBoundingClientRect().left:0;
  const months=entries.map(item=>({month:item.dataset.windowEnd,right:item.getBoundingClientRect().right-origin}));
  return track.activityGeometry={width:track.clientWidth,cells,months,paddingLeft:parseFloat(style.paddingLeft)||0,paddingRight:parseFloat(style.paddingRight)||0};
}
function activityViewportPadding(track) {
  const style=getComputedStyle(track);
  return (parseFloat(style.paddingLeft)||0)+(parseFloat(style.paddingRight)||0);
}
function layoutActivityMonthGaps(track, month) {
  delete track.activityGeometry;
  const entries=[...track.querySelectorAll('.activity-slide-month')];
  if(!entries.length)return;
  entries.forEach(entry=>entry.style.removeProperty('margin-right'));
  const end=entries.findIndex(entry=>entry.dataset.windowEnd===month);
  const count=activityVisibleMonthCount();
  const visible=entries.slice(Math.max(0,end-count+1),end+1);
  if(visible.length<2)return;
  const widths=visible.map(entry=>entry.getBoundingClientRect().width);
  const spare=Math.max(0,track.clientWidth-activityViewportPadding(track)-widths.reduce((sum,width)=>sum+width,0));
  // Shorter months can have more breathing room. Only the gaps change.
  const weights=widths.slice(0,-1).map(width=>1/Math.max(1,width));
  const total=weights.reduce((sum,weight)=>sum+weight,0);
  visible.slice(0,-1).forEach((entry,index)=>entry.style.marginRight=`${spare*weights[index]/total}px`);
}
function activityWeekMetrics(track) {
  const grid=track.querySelector('.activity-continuous-months .activity-heat-grid');
  const cell=grid?.querySelector('.activity-heat-cell');
  if(!cell)return null;
  const gap=parseFloat(getComputedStyle(grid).columnGap)||0;
  const width=cell.getBoundingClientRect().width;
  return {grid,gap,width,pitch:width+gap,children:[...grid.children]};
}
function sizeActivityWeekViewport(track) {
  const metrics=activityWeekMetrics(track);
  if(!metrics||!metrics.width)return;
  const parent=track.parentElement,style=getComputedStyle(parent);
  const available=parent.getBoundingClientRect().right-track.getBoundingClientRect().left-(parseFloat(style.paddingRight)||0)-(parseFloat(style.borderRightWidth)||0);
  if(available<=0)return;
  const weeks=Math.max(1,Math.floor((available-activityViewportPadding(track)+metrics.gap)/metrics.pitch));
  track.style.width=`${Math.min(available,weeks*metrics.pitch-metrics.gap+activityViewportPadding(track))}px`;
  track.dataset.visibleWeeks=String(weeks);
}
function snapActivityWeeks(track, anchorDate=null) {
  const metrics=activityWeekMetrics(track);
  if(!metrics)return;
  const {children,pitch}=metrics;
  const count=Number(track.dataset.visibleWeeks)||1,total=children.length/7;
  const anchor=anchorDate?children.findIndex(cell=>cell.dataset.activityDate===anchorDate):-1;
  const column=anchor>=0?Math.floor(anchor/7)-count+1:Math.round(track.scrollLeft/pitch);
  const first=Math.max(0,Math.min(column,Math.max(0,total-count)));
  track.scrollTo({left:first*pitch,behavior:'instant'});
  const days=children.slice(first*7,(first+count)*7).filter(cell=>cell.dataset.activityDate);
  const start=days[0]?.dataset.activityDate,end=days.at(-1)?.dataset.activityDate;
  if(!start||!end)return;
  track.dataset.weekEnd=end;
  env.activityPayload.start=start;env.activityPayload.end=end;
  env.activityPayload.days=env.activityPayload.neighborDays.filter(day=>day.date>=start&&day.date<=end);
  $('#activityMonth').value=end.slice(0,7);
  $('#activityPeriod').textContent='截至 '+end.slice(0,7).replace('-',' 年 ')+' 月';
}
function wireActivityHeatScroll({anchorDate=null} = {}) {
  const track=$('.activity-heat-scroll');
  if(!track)return;
  delete track.activityGeometry;
  track.classList.toggle('has-month-window',Boolean(env.activityPayload?.neighborDays));
  const alignMonth=month=>{
    const geometry=activityScrollGeometry(track),item=geometry.months.find(item=>item.month===month);
    return item?item.right-track.clientWidth+geometry.paddingLeft+geometry.paddingRight:0;
  };
  const nearestMonth=()=>{
    const geometry=activityScrollGeometry(track),candidates=activityWindowStops(geometry.months,activityVisibleMonthCount());
    if(!candidates.length)return null;
    const edge=track.scrollLeft+track.clientWidth-geometry.paddingLeft-geometry.paddingRight;
    return candidates.reduce((best,item)=>Math.abs(item.right-edge)<Math.abs(best.right-edge)?item:best).month;
  };
  const snapMonthly=()=>{
    if($('#activityRange').value!=='month'||!env.activityPayload?.neighborDays)return false;
    if(track.dataset.positioning==='true')return true;
    if(document.documentElement.dataset.heatmapMonthGap==='false'){
      sizeActivityWeekViewport(track);snapActivityWeeks(track);
      env.applyActivityPrefetch();env.prefetchActivityMonths($('#activityMonth').value);return true;
    }
    if(Number(track.dataset.viewportWidth)!==track.clientWidth){
      if(track.clientWidth&&Number(track.dataset.pendingWidth)!==track.clientWidth){
        track.dataset.pendingWidth=String(track.clientWidth);env.loadTrainingActivity();
      }
      return true;
    }
    const month=nearestMonth();if(!month)return true;
    layoutActivityMonthGaps(track,month);
    track.scrollTo({left:Math.max(0,alignMonth(month)),behavior:'instant'});
    updateActivityWindow(month);
    env.applyActivityPrefetch();
    env.prefetchActivityMonths(month);
    return true;
  };
  if(!refreshActivityHeatScroll)refreshActivityHeatScroll=wireHorizontalDateScroll(track,'[data-window-end]',{
    snap:snapMonthly,
    scroll:()=>{updateActivityEdgeVisibility(track);if($('#activityRange').value==='month'&&track.dataset.positioning!=='true'){const month=nearestMonth();if(month)env.prefetchActivityMonths(month);}}
  });
  track.dataset.positioning='true';
  const weekly=document.documentElement.dataset.heatmapMonthGap==='false'&&$('#activityRange').value==='month'&&Boolean(env.activityPayload?.neighborDays);
  if(weekly)sizeActivityWeekViewport(track);else {track.style.removeProperty('width');delete track.dataset.weekEnd;}
  if(!track.dataset.weekResizeWired){
    track.dataset.weekResizeWired='true';
    let lastWidth=track.parentElement.getBoundingClientRect().width;
    new ResizeObserver(()=>{
      const width=track.parentElement.getBoundingClientRect().width;
      if(width===lastWidth)return;lastWidth=width;
      if(document.documentElement.dataset.heatmapMonthGap==='false'&&$('#activityRange').value==='month'&&track.offsetWidth&&env.activityPayload?.neighborDays)wireActivityHeatScroll({anchorDate:track.dataset.weekEnd});
    }).observe(track.parentElement);
  }
  layoutActivityMonthGaps(track,$('#activityMonth').value);
  requestAnimationFrame(()=>{
    track.dataset.viewportWidth=String(track.clientWidth);delete track.dataset.pendingWidth;
    if(weekly){
      const month=$('#activityMonth').value;
      const lastDay=env.activityPayload.neighborDays.filter(day=>day.date.slice(0,7)===month&&day.date<=env.activityBrowseEnd(env.activityPayload)).at(-1)?.date;
      snapActivityWeeks(track,anchorDate||lastDay);
    }else track.scrollLeft=Math.max(0,alignMonth($('#activityMonth').value));
    refreshActivityHeatScroll?.();track.dataset.positioning='false';
    updateActivityEdgeVisibility(track);
  });
}


return {renderActivitySlidingMonths,activityVisibleMonthCount,renderActivityMonthPicker,activitySafeLink,renderActivityDay,renderActivityMonths,wireHorizontalDateScroll,activityWindowStops,updateActivityWindow,updateActivityEdgeVisibility,activityScrollGeometry,activityViewportPadding,layoutActivityMonthGaps,activityWeekMetrics,sizeActivityWeekViewport,snapActivityWeeks,wireActivityHeatScroll};
}
return {create};
});
