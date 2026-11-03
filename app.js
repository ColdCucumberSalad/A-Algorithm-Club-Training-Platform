/* Pick once per page load. Theme changes and view switches retain this copy. */
(() => {
  const headlines=[
    '把这一周，写成你的进步。',
    '让今天的思考，成为明天的底气。',
    '把每一次尝试，都变成积累。',
    '一步步想清楚，一道道做明白。',
    '在不断求解中，找到自己的节奏。',
    '今天多想一步，明天更进一步。',
    '让每一次坚持，都留下答案。',
    '从一道题开始，走向更多可能。',
    '把难题拆开，把进步留下。',
    '慢慢积累，也能走得很远。'
  ];
  const encouragements=[
    '每一次认真求解，都在拓宽你的思路。',
    '走过的题目，会成为下一次思考的线索。',
    '把复杂拆成小步，让进步看得见。',
    '不必每天突破，持续练习就有收获。',
    '今天弄懂的一点，是明天解题的起点。',
    '答案之外，别忘了记录思考的过程。',
    '让每一次复盘，都帮助下一次出发。',
    '遇到卡点也没关系，耐心推演就是训练。',
    '把练习落到每天，把成长留在这里。',
    '按自己的节奏前进，积累终会连成线。'
  ];
  function choose(id,lines){
    const target=document.getElementById(id);if(!target)return;
    const key='club-refresh-copy-v1:'+id;let previous=-1;
    try{const stored=sessionStorage.getItem(key);if(stored!==null)previous=Number(stored);}catch(_){}
    const valid=Number.isInteger(previous)&&previous>=0&&previous<lines.length;
    let index=Math.floor(Math.random()*(lines.length-(valid?1:0)));
    if(valid&&index>=previous)index++;
    target.textContent=lines[index];try{sessionStorage.setItem(key,String(index));}catch(_){}
  }
  choose('trainingHeadline',headlines);choose('trainingEncouragement',encouragements);
})();

let adminTestMode = false;
const rankingData = {};
const rankingKey = (scope, platform='codeforces', period='semester') => scope === 'rating' ? `${scope}:${platform}` : scope === 'solved' ? `${scope}:${period}` : scope;
function rankingSelection(target) {
  const panel = document.querySelector(target)?.closest('.panel');
  return {scope: panel?.querySelector('[data-ranking].active')?.dataset.ranking || 'checkin',
    platform: panel?.querySelector('[data-rating-platform]')?.value || 'codeforces',
    period: panel?.querySelector('[data-solved-period]')?.value || 'semester', panel};
}

const pageTitles = {settings:'设置',extensions:'拓展', dashboard:'总览', submissions:'我的提交', leaderboard:'排行榜', showcase:'团队提交', members:'成员列表', contests:'赛事中心', admin:'管理工作台', rbcshop:'RBC商店'};
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
let canManage = false;
const demoMode = false;
let countdownTimer = null;
let countdownDeadline = 0;
let countdownClosed = false;
let currentView = 'dashboard';
let adminQueueTimer = null;
let adminQueueInFlight = null;
let adminQueueAbortController = null;
let adminQueueRequestVersion = 0;
let mineSubmissionsInFlight = null;
let activityRequestVersion = 0;
let submissionsRequestVersion = 0;
let showcaseRequestVersion = 0;
let membersRequestVersion = 0;
let historyRequestVersion = 0;
const leaderboardInFlight = new Map();
let pulseDays = [];
let selectedPulseDate = '';
let pulseToday = '';
let activityPayload = null, trainingRequestVersion = 0;

function activityMonthBounds(month) {
  const [year, m] = month.split('-').map(Number);
  const first=new Date(year,m-4,1);
  const start=first.getFullYear()+'-'+String(first.getMonth()+1).padStart(2,'0')+'-01';
  return [start, month+'-'+new Date(year,m,0).getDate()];
}
function renderActivityMonthPicker(year){
  const selected=$('#activityMonth').value;
  const popup=$('#activityMonthPopover');
  popup.dataset.year=year;
  popup.innerHTML=`<div class="activity-month-picker-heading"><button type="button" data-month-year="${year-1}" aria-label="上一年" ${year<=2001?'disabled':''}>‹</button><strong>${year} 年</strong><button type="button" data-month-year="${year+1}" aria-label="下一年" ${year>=2199?'disabled':''}>›</button></div><div class="activity-month-picker-grid">${Array.from({length:12},(_,i)=>{const value=year+'-'+String(i+1).padStart(2,'0');return `<button type="button" data-month-value="${value}" aria-pressed="${value===selected}">${i+1}月</button>`;}).join('')}</div>`;
}
$('#activityMonthPopover')?.addEventListener('beforetoggle',event=>{
  if(event.newState!=='open')return;
  renderActivityMonthPicker(Number($('#activityMonth').value.slice(0,4))||new Date().getFullYear());
  const rect=$('#activityMonthTrigger').getBoundingClientRect(),popup=$('#activityMonthPopover');
  const width=Math.min(280,innerWidth-24);
  popup.style.width=width+'px';popup.style.left=Math.max(12,Math.min(rect.right-width,innerWidth-width-12))+'px';
  popup.style.top=Math.max(12,Math.min(rect.bottom+8,innerHeight-250))+'px';
});
$('#activityMonthPopover')?.addEventListener('click',event=>{
  const year=event.target.closest('[data-month-year]');if(year){renderActivityMonthPicker(Number(year.dataset.monthYear));return;}
  const month=event.target.closest('[data-month-value]');if(!month)return;
  $('#activityMonth').value=month.dataset.monthValue;
  $('#activityMonthPopover').hidePopover();
  $('#activityMonth').dispatchEvent(new Event('change',{bubbles:true}));
});
function activityUnit(){return $('#activityMetric')?.value==='daily'?'次':'题';}
function activitySafeLink(url){try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)?u.href:'';}catch(_){return '';}}
function updatePulseDay(day){
  const index=pulseDays.findIndex(item=>item.date===day.date);
  if(index<0)pulseDays.push(day);else pulseDays[index]={...pulseDays[index],...day};
}
function renderActivityDay(day) {
  const container=$('#activityRecords');if(!container)return;
  const metric=$('#activityMetric').value,record=activityPayload?.days.find(d=>d.date===day.date);
  const rows=(record?.records||[]).filter(r=>r.kind===metric);
  const count=record?.[metric]||0;
  const dateLabel=day.date===pulseToday?'今日':'当日';
  const hasSubmission=Boolean(record?.hasSubmission||record?.daily>0);
  $('#pulseFocus').textContent=`${day.date} · ${metric==='ac'?'AC 题目':'每日一题提交'} ${count} ${activityUnit()}`;
  container.innerHTML=rows.length?rows.map((r,index)=>{const url=activitySafeLink(r.url);return `<div class="activity-record"><div><small>第${index+1}题</small>${url?`<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(uiProblemTitle(r.title))} <span aria-hidden="true">↗</span></a>`:`<strong>${escapeHtml(uiProblemTitle(r.title))}</strong>`}</div><span class="activity-record-check" aria-label="已记录">✓</span></div>`;}).join(''):`<p class="activity-empty">${day.date>pulseToday?'这一天还未到来。':!record?'正在加载当天记录…':metric==='ac'&&hasSubmission?`${dateLabel}已有提交，暂无已确认的 AC 记录。`:`${dateLabel}没有提交`}${record?.checkedIn&&!hasSubmission?' 已签到，尚未提交题目。':''}</p>`;
  const submit=$('#activitySubmit'),primary=$('#openSubmission');
  submit.hidden=!primary||primary.hidden||document.body.classList.contains('site-admin-mode');
  submit.disabled=false;submit.textContent='查看历史提交';
  $$('#activityHeatmap [data-activity-date]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.activityDate===day.date));});
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
      return `<button type="button" class="activity-heat-cell${day.isToday?' is-today':''}" data-activity-date="${day.date}" data-level="${level}" aria-pressed="${day.date===selectedPulseDate}" aria-label="${day.date}，${n}${unit}${day.date>today?'，未来日期':''}" title="${day.date} · ${n} ${unit}"></button>`;
    }).join('');
    return `<div class="activity-continuous-months" style="--heat-weeks:${weeks}"><div class="activity-heat-grid">${blanks}${cells}</div><div class="activity-continuous-captions">${captions.join('')}</div></div>`;
  }
  const months=new Map();
  for(const day of days){const key=day.date.slice(0,7);if(!months.has(key))months.set(key,[]);months.get(key).push(day);}
  return `<div class="activity-month-sections">${[...months].map(([month,items])=>{
    const offset=(new Date(items[0].date+'T12:00:00').getDay()+6)%7;
    const weeks=Math.ceil((offset+items.length)/7);
    const blanks=Array.from({length:offset},()=>'<span aria-hidden="true"></span>').join('');
    return `<section class="activity-month-section" aria-label="${month}" style="--heat-weeks:${weeks}"><div class="activity-heat-grid">${blanks}${items.map(day=>{
      const n=day[metric],level=n===0?0:Math.min(4,Math.ceil(Math.log2(n+1)));
      return `<button type="button" class="activity-heat-cell${day.isToday?' is-today':''}" data-activity-date="${day.date}" data-level="${level}" aria-pressed="${day.date===selectedPulseDate}" aria-label="${day.date}，${n}${unit}${day.date>today?'，未来日期':''}" title="${day.date} · ${n} ${unit}"></button>`;
    }).join('')}</div><div class="activity-month-caption">${Number(month.slice(5))}月</div></section>`;
  }).join('')}</div>`;
}
window.addEventListener('site-heatmap-layout-change',()=>{if(activityPayload)renderTrainingActivity();});
function renderTrainingActivity(){
  const data=activityPayload;if(!data)return;
  const metric=$('#activityMetric').value,summary=data[metric],unit=activityUnit(),semester=$('#activityRange').value==='semester';
  $('#activityPeriod').textContent=semester?(data.semester?.name||'当前学期'):'近四个月 · 截至 '+data.end.slice(0,7).replace('-',' 年 ')+' 月';
  $('#activityMonthLabel').hidden=semester;
  $('#activityHeatmap').dataset.range=semester?'semester':'month';
  $('#activityHeatmap').innerHTML=`<div class="activity-weekdays" aria-hidden="true">${['一','二','三','四','五','六','日'].map(n=>`<span>${n}</span>`).join('')}</div>${renderActivityMonths(data.days,'ac','题',data.today)}`;
  wireActivityHeatScroll();
  $('#activityNote').hidden=!data.ac?.undated;
  $('#activityNote').textContent=data.ac?.undated ? `另有 ${data.ac.undated} 题日期未知，仅计入总榜，不计入学期榜和热力图。` : '';
  const day=data.days.find(d=>d.date===selectedPulseDate)||data.days.find(d=>d.isToday)||[...data.days].reverse().find(d=>d.date<=data.today)||data.days[0];
  if(day){updatePulseDay(day);selectPulseDay(day.date);}
}
async function loadTrainingActivity(dashboard=null){
  if(!$('#activityMonth'))return;
  if(dashboard){pulseToday=dashboard.today||new Date().toLocaleDateString('sv-SE');}
  const month=$('#activityMonth');if(!month.value)month.value=(pulseToday||new Date().toLocaleDateString('sv-SE')).slice(0,7);
  $('#activityMonthTrigger').innerHTML=month.value.replace('-',' 年 ')+' 月 <span aria-hidden="true">⌄</span>';
  const requestVersion=++trainingRequestVersion;
  let [start,end]=activityMonthBounds(month.value);
  // The first request supplies actual semester bounds; no fabricated calendar dates.
  if($('#activityRange').value==='semester'&&activityPayload?.semester){start=activityPayload.semester.start;end=activityPayload.semester.end;}
  $('#activityNote').hidden=false;$('#activityNote').textContent='正在加载训练活动…';$('#activityHeatmap').setAttribute('aria-busy','true');
  try{
    const response=await clubApi.request(`/api/training-activity?start=${start}&end=${end}`);
    const data=await response.json();if(requestVersion!==trainingRequestVersion)return;
    if(!response.ok)throw new Error(data.error||'训练活动加载失败');
    activityPayload=data;
    const option=$('#activityRange option[value="semester"]');option.disabled=!data.semester;
    if(!data.semester&&$('#activityRange').value==='semester')$('#activityRange').value='month';
    if($('#activityRange').value==='semester'&&data.semester&&(start!==data.semester.start||end!==data.semester.end)){loadTrainingActivity();return;}
    renderTrainingActivity();
  }catch(error){if(requestVersion!==trainingRequestVersion)return;activityPayload=null;$('#activityHeatmap').innerHTML='<button type="button" class="secondary-button" data-activity-retry>重新加载</button>';$('#activityNote').textContent=error.message;$('#activityRecords').textContent='当天记录暂未加载成功，请重试。';}
  finally{if(requestVersion===trainingRequestVersion)$('#activityHeatmap').removeAttribute('aria-busy');}
}
$('#activityMetric')?.addEventListener('change',renderTrainingActivity);
$('#activityRange')?.addEventListener('change',()=>loadTrainingActivity());
$('#activityMonth')?.addEventListener('change',event=>{if(/^\d{4}-\d{2}$/.test(event.target.value))loadTrainingActivity();});
$('#activitySubmit')?.addEventListener('click',()=>setView('submissions'));
$('#activityHeatmap')?.addEventListener('click',event=>{
  if(event.target.closest('[data-activity-retry]')){loadTrainingActivity();return;}
  const button=event.target.closest('[data-activity-date]');if(!button||!activityPayload)return;
  const day=activityPayload.days.find(d=>d.date===button.dataset.activityDate);if(!day)return;
  updatePulseDay(day);
  selectPulseDay(day.date);
});
document.addEventListener('click', async (event) => { if (event.target.id !== 'logoutButton') return; await clubApi.request('/api/auth/logout', {method:'POST'}); window.location.href = '/auth.html'; });
const liveStyle = document.createElement('style'); liveStyle.textContent = '.my-submissions-live{margin-top:14px;padding:21px}.live-submission-row{display:flex;align-items:center;gap:12px;padding:13px 0;border-top:1px solid #edf0ee}.live-submission-info{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}.live-submission-info strong{font-size:12px}.live-submission-info small{font-size:10px;color:var(--muted)}.submission-thumb{width:44px;height:44px;border-radius:7px;background:#eef7f5;display:grid;place-items:center;overflow:hidden;color:var(--teal);flex:none}.submission-thumb img{width:100%;height:100%;object-fit:cover}.live-submission-row .review-view{color:var(--teal-dark);font-size:11px;font-weight:700;white-space:nowrap}.upload-preview{width:80px;height:55px;object-fit:cover;border-radius:6px;margin-bottom:4px}.status-tag.rejected{color:#b35d55;background:#fbeceb}'; document.head.appendChild(liveStyle);
const accessibilityStyle = document.createElement('style'); accessibilityStyle.textContent = '.toast{transition:transform .25s ease,opacity .25s ease}.search-box input:focus-visible{outline:2px solid var(--teal);outline-offset:2px}'; document.head.appendChild(accessibilityStyle);
const escapeHtml = (value='') => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const memberAvatarSources = new Map();
function memberAvatarSource(memberId) {
  const id = Number(memberId);
  return memberAvatarSources.has(id) ? memberAvatarSources.get(id) : `/api/members/${id}/avatar?size=small`;
}
function memberAvatar(memberId, name, className='leader-avatar', source=undefined) {
  if (source !== undefined) memberAvatarSources.set(Number(memberId), source);
  const url = memberAvatarSource(memberId);
  return `<span class="${className} synced-member-avatar" data-avatar-member="${Number(memberId)}" data-avatar-fallback="${escapeHtml((name || '').slice(0,1))}">${escapeHtml((name || '').slice(0,1))}${url ? `<img src="${escapeHtml(url)}" alt="" loading="lazy" decoding="async" width="96" height="96" onload="this.parentElement.replaceChildren(this)" onerror="this.parentElement.textContent=this.parentElement.dataset.avatarFallback" />` : ''}</span>`;
}

function renderLeaderboard(mode='checkin', target='#leaderboardList') {
  const el = $(target);
  if (!el) return;
  const selection = rankingSelection(target);
  const allRows = rankingData[rankingKey(selection.scope,selection.platform,selection.period)];
  const query=selection.panel?.querySelector('[data-ranking-search]')?.value||'';
  const rows = target === '#leaderboardList' ? allRows?.filter(row => row.isCurrent) : allRows?.filter(row=>window.MemberTitles.matchesMember(row,query));
  const filter = selection.panel?.querySelector('.rating-platform-filter:not(.solved-period-filter)');
  const solvedFilter = selection.panel?.querySelector('.solved-period-filter');
  if (solvedFilter) solvedFilter.hidden = selection.scope !== 'solved';
  if (filter) filter.hidden = selection.scope !== 'rating';
  el.innerHTML = !rows ? '<div class="queue-empty" role="status">正在加载榜单…</div>' : !rows.length
    ? `<div class="queue-empty">${target === '#leaderboardList' ? '你在当前榜单暂无排名' : query.trim() ? '没有匹配的成员或分队' : selection.scope === 'rating' ? '当前团队暂无绑定此平台的成员' : '暂无排行榜数据'}</div>`
    : rows.map(row => `
      <button type="button" class="leader-row ${row.isCurrent ? 'you' : ''}" data-ranking-member="${row.memberId}" aria-label="查看${escapeHtml(uiMemberName(row.name))}的个人信息">
        <span class="leader-rank ${row.rank && row.rank <= 3 ? 'top' : ''}">${row.rank || '—'}</span>
        <span class="leader-member"><span class="leader-avatar-stack">${memberAvatar(row.memberId,row.name,'leader-avatar',row.avatar)}${window.MemberTitles?.cohort(row.cohort,true)||''}</span><span class="leader-name">${window.MemberTitles?.list(row.titles||row.title)||''}${escapeHtml(uiMemberName(row.name))}${row.isCurrent ? '（你）' : ''}</span></span>
        <span class="leader-score">${row.value ?? '—'}<small> ${escapeHtml(row.unit)}</small></span>
        <span class="leader-count">${escapeHtml(row.detail)}${row.value === null ? ' · 暂无评级' : ''}</span>
      </button>`).join('');
  if (target === '#leaderboardList') {
    const current = rows?.find(row => row.isCurrent);
    if ($('#yourRankValue')) $('#yourRankValue').textContent = current?.rank ? `#${current.rank}` : '—';
    if ($('#yourRankChange')) $('#yourRankChange').textContent = {checkin:'当前连续签到',rating:'平台已同步 Rating',solved:'累计过题',wealth:'当前 Coins 余额'}[selection.scope];
  }
}

document.addEventListener('input',event=>{if(event.target.matches('[data-ranking-search]')){const panel=event.target.closest('.full-leaderboard');panel.querySelector('[data-ranking-search-clear]').hidden=!event.target.value;renderLeaderboard(undefined,'#leaderboardListFull');}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-ranking-search-clear]');if(button){const input=button.closest('.ranking-search').querySelector('input');input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();}});

function setView(view, {preserveContent=false}={}) {
  if (view === 'rbcshop' && !window.CurrencyModule?.getCurrencyData().enabled) view = 'dashboard';
  if (view === 'admin' && !canManage) view = 'dashboard';
  if (view === currentView) return;
  const previousView = currentView;
  currentView = view;
  const nextView = $(`#${view}View`);
  $$('.page-view').forEach((el) => el.classList.toggle('active', el === nextView));
  $$('.nav-item[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
  $('#pageTitle').textContent = pageTitles[view] || '总览';
  // Hidden pages have zero-size tabs at startup; measure after making them visible.
  nextView?.querySelectorAll('.segmented').forEach(group => syncSegmented(group));
  // The overview owns its entrance animation; do not stack the route animation.
  if (nextView && view !== 'dashboard') {
    nextView.classList.remove('view-enter');
    void nextView.offsetWidth;
    nextView.classList.add('view-enter');
    const transitionId = String(Date.now());
    nextView.dataset.transitionId = transitionId;
    window.setTimeout(() => {
      if (nextView.dataset.transitionId === transitionId) nextView.classList.remove('view-enter');
    }, 1120);
  }
  window.scrollTo({top:0, behavior:'smooth'});
  if (view === 'dashboard') {const selected=rankingSelection('#leaderboardList');loadLeaderboard(selected.scope,selected.platform,{period:selected.period});}
  if (view === 'leaderboard') { const selected = rankingSelection('#leaderboardListFull'); renderLeaderboard(selected.scope, '#leaderboardListFull'); loadLeaderboard(selected.scope,selected.platform,{period:selected.period}); }
  if (!demoMode && previousView === 'admin' && view !== 'admin') stopAdminQueuePolling();
  if (!demoMode && view === 'admin') startAdminQueuePolling();
  if (!demoMode && view === 'submissions' && !preserveContent) loadMySubmissions();
  if (!demoMode && view === 'showcase' && !preserveContent) loadShowcase();
  if (!demoMode && view === 'members') loadMembersLive();
  if (!demoMode && view === 'rbcshop' && window.CurrencyModule) {
    const shopView = document.getElementById('rbcshopView');
    if (shopView) window.CurrencyModule.renderShopView(shopView);
  }
  window.contestSchedule?.activate(view === 'contests');
  if (view === 'extensions') window.ExtensionResources.load();
}

function updateSubmissionEntry(entry, day, date) {
  if (!entry || !day) return;
  const isFuture = date > pulseToday;
  const historical = date < pulseToday;
  const label = isFuture ? '暂未开放' : historical && day.isMakeup ? '当日已补签'
    : historical && day.submitted ? '当日已签到' : historical ? '补交当日记录' : day.submitted || day.hasSubmission ? '继续提交' : '提交今日记录';
  const disabled = adminTestMode ? isFuture : isFuture || !day.canSubmit || historical && (day.submitted || day.isMakeup);
  entry.innerHTML = `<span>＋</span>${adminTestMode&&!isFuture?(historical?'补交当日记录':day.submitted||day.hasSubmission?'继续提交':'提交今日记录'):label}`;
  entry.disabled = Boolean(disabled);
  entry.classList.toggle('disabled', Boolean(disabled));
  entry.classList.toggle('is-makeup-complete', historical && day.isMakeup);
}

function selectPulseDay(date) {
  const day = pulseDays.find(item => item.date === date);
  if (!day) return;
  selectedPulseDate = date;
  const targetDate=$('#submissionTargetDate');
  if(targetDate){targetDate.dateTime=date;targetDate.textContent=`${date<pulseToday?'补交日期':'提交日期'}：${date}${date===pulseToday?'（今日）':''}`;}
  $$('.pulse-week').forEach(button => {
    const selected = button.dataset.pulseDate === date;
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-selected', String(selected));
  });
  $('#pulseFocus').textContent = `${date} · ${day.isMakeup ? '已补签' : day.makeupOpen ? '已开放补交，待提交' : day.checkedIn && !day.hasSubmission ? '已签到' : day.submitted ? '已有有效提交' : '尚未提交'}`;
  updateSubmissionEntry($('#openSubmission'), day, date);
  updateSubmissionEntry($('#openSubmissionSecondary'), pulseDays.find(item => item.date === pulseToday), pulseToday);
  renderActivityDay(day);
  if(activityPayload&&(date<activityPayload.start||date>activityPayload.end)){
    $('#activityRange').value='month';$('#activityMonth').value=date.slice(0,7);loadTrainingActivity();
  }
}

function wireHorizontalDateScroll(track, itemSelector) {
  if (!track || track.dataset.scrollWired) return;
  track.dataset.scrollWired = 'true';
  let drag = null, frame = 0, suppressClick = false, settleTimer = 0, settling = false;
  let touch = null;
  const contacts = new Set();
  const scheduleSnap = () => {
    if (settling) return;
    clearTimeout(settleTimer);
    if (!contacts.size && !drag) settleTimer = setTimeout(snap, 200);
  };
  const snap = () => {
    if (settling || contacts.size || drag || !track.clientWidth) return;
    clearTimeout(settleTimer);
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
    if (state.active) {
      if (event.type === 'pointerup') snap();
      else scheduleSnap();
    }
  };
  // Touch scrolling belongs to the browser, including momentum and direction locking.
  // A pointercancel during native panning does not mean the finger has lifted.
  track.addEventListener('touchstart', event => {
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
    clearTimeout(settleTimer); settling = false; suppressClick = false;
    track.scrollTo({left:track.scrollLeft,behavior:'instant'});
    drag = {id:event.pointerId,x:event.clientX,y:event.clientY,latestX:event.clientX,scrollLeft:track.scrollLeft,active:false};
  });
  track.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    const distance = Math.abs(event.clientX-drag.x), cross = Math.abs(event.clientY-drag.y);
    if (!drag.active) {
      if (cross > 6 && cross > distance) { drag = null; return; }
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
  track.addEventListener('lostpointercapture', event => {if (event.target === track) finish(event);});
  track.addEventListener('scroll', () => {
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

let refreshActivityHeatScroll;
function wireActivityHeatScroll() {
  if (!refreshActivityHeatScroll) {
    refreshActivityHeatScroll = wireHorizontalDateScroll($('.activity-heat-scroll'),'.activity-month-section, .activity-continuous-months [data-activity-date]');
  }
  requestAnimationFrame(() => refreshActivityHeatScroll?.());
}

function wirePulseAtlas() {
  const track = $('.pulse-track');
  if (!track || track.dataset.wired) return;
  track.dataset.wired = 'true';
  wireHorizontalDateScroll(track,'[data-pulse-date]');
  track.addEventListener('click', event => {
    const day = event.target.closest('[data-pulse-date]');
    if (day) selectPulseDay(day.dataset.pulseDate);
  });
  track.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const items = [...track.querySelectorAll('[data-pulse-date]')];
    const current = items.indexOf(event.target);
    if (current < 0) return;
    event.preventDefault();
    const next = event.key==='Home'?0:event.key==='End'?items.length-1:Math.max(0,Math.min(items.length-1,current+(event.key==='ArrowRight'?1:-1)));
    items[next].focus({preventScroll:true});
    items[next].click();
    items[next].scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
  });
}

function formatRemaining(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${days} 天 ${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function startDeadlineCountdown(seconds, closed) {
  window.clearInterval(countdownTimer);
  countdownTimer = null;
  countdownClosed = Boolean(closed);
  countdownDeadline = Date.now() + Math.max(0, Number(seconds) || 0) * 1000;
  const render = () => {
    const remaining = Math.max(0, Math.ceil((countdownDeadline - Date.now()) / 1000));
    const welcome = $('.welcome-row .muted');
    if (welcome) welcome.textContent = countdownClosed ? '本周已截止' : `距离本周截止还有 ${formatRemaining(remaining)}`;
    const formNote = $('.form-note span:last-child');
    if(formNote && adminTestMode)formNote.textContent='历史日期可提交';
    else if (formNote && $('#submissionForm')?.dataset.makeup === '1') formNote.textContent = '已开放补交 · 学期结束前有效';
    else if (formNote) formNote.textContent = countdownClosed ? '本周已截止' : `距离本周截止还有 ${formatRemaining(remaining)}`;
    if (remaining <= 0 && !countdownClosed) {
      countdownClosed = true;
      window.clearInterval(countdownTimer);
      countdownTimer = null;
      render();
    }
  };
  render();
  if (closed || countdownDeadline <= Date.now()) return;
  countdownTimer = window.setInterval(render, 1000);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    window.clearInterval(countdownTimer);
    countdownTimer = null;
    stopAdminQueuePolling();
    return;
  }
  if (countdownDeadline && !countdownClosed) {
    startDeadlineCountdown(Math.ceil(Math.max(0, countdownDeadline - Date.now()) / 1000), false);
  }
  if (!demoMode && currentView === 'admin') startAdminQueuePolling();
});

function renderPulseDays(dashboard) {
  const track = $('.pulse-track');
  const weekDays = dashboard.pulse || [];
  const selectedHistory=activityPayload?.days.find(day=>day.date===selectedPulseDate)||pulseDays.find(day=>day.date===selectedPulseDate);
  pulseDays = [...weekDays];
  if(selectedHistory&&!pulseDays.some(day=>day.date===selectedHistory.date))pulseDays.push(selectedHistory);
  pulseToday = dashboard.today;
  if (!track || !pulseDays.length) return;
  const rangeKey = `${weekDays[0]?.date}/${weekDays.at(-1)?.date}`;
  const resetScroll = track.dataset.rangeKey !== rangeKey;
  track.dataset.rangeKey = rangeKey;
  if (resetScroll) track.dataset.resetScroll = 'true';
  track.style.setProperty('--pulse-days', String(weekDays.length));
  track.innerHTML = weekDays.map(day => `<button class="pulse-week ${day.submitted ? 'is-complete' : ''} ${day.makeupOpen ? 'is-unlocked' : ''} ${day.isToday ? 'is-current' : ''}" data-pulse-date="${day.date}" type="button" role="tab" aria-selected="false" aria-label="${day.date} ${day.isMakeup ? '已补签' : day.makeupOpen ? '已开放补交，待提交' : day.checkedIn && !day.hasSubmission ? '已签到' : day.submitted ? '已提交' : '未提交'}"><small>${['周日','周一','周二','周三','周四','周五','周六'][new Date(day.date+'T12:00:00').getDay()]}</small><span>${day.isToday ? '今' : day.date.slice(-2)}</span><i aria-hidden="true"></i></button>`).join('');
  const streakDays = Math.max(0, Math.trunc(Number(dashboard.streakDays) || 0));
  if ($('#streakValue')) $('#streakValue').innerHTML = `${streakDays} <small>天</small>`;
  const streakFoot = $('.metric-card[data-metric="streak"] .metric-foot span');
  if (streakFoot) streakFoot.textContent = '保持每天的训练节拍';
  const todayIndex = pulseDays.findIndex(day => day.date === pulseToday);
  const defaultDate = pulseDays.some(day => day.date === selectedPulseDate) ? selectedPulseDate : pulseDays.find(day => day.isToday)?.date || pulseDays[todayIndex >= 0 ? todayIndex : Math.floor(pulseDays.length / 2)].date;
  selectPulseDay(defaultDate);
  if (resetScroll) requestAnimationFrame(() => {
    if (!track.clientWidth) return;
    track.scrollLeft = track.scrollWidth-track.clientWidth;
    delete track.dataset.resetScroll;
  });
}

function applyLiveDashboardState(dashboard, submissions = []) {
  const week = dashboard.current_week;
  const semester = dashboard.semester;
  if (!week || !semester) return;
  const score = Number(dashboard.score || 0);
  const submissionCount = Number(dashboard.submissions || 0);
  const minScore = Number(semester.minScore || 0);
  const minSubmissions = Number(semester.minSubmissions || 0);
  const stats = dashboard.stats || {};
  const scoreGap = Math.max(0, minScore - score);
  const submissionGap = Math.max(0, minSubmissions - submissionCount);
  const currentSubmissions = submissions.filter((item) => Number(item.week) === Number(week.number));
  const parts = currentSubmissions.flatMap((item) => item.parts || []);
  const pending = parts.filter((part) => part.status === 'pending');
  const pendingLabels = [...new Set(pending.map((part) => part.kind === 'proof' ? '截图' : part.kind === 'logic' ? '题解思路' : part.kind === 'code' ? '代码' : 'Blog'))];
  const presentKinds = new Set(parts.map((part) => part.kind));
  const missingLabels = [['proof', '通过截图'], ['logic', '题解思路'], ['blog', 'Blog']].filter(([kind]) => !presentKinds.has(kind)).map(([, label]) => label);
  const requireBoth = semester.requireBoth !== false;
  const isComplete = requireBoth ? scoreGap === 0 && submissionGap === 0 : scoreGap === 0 || submissionGap === 0;
  const focus = isComplete
    ? '保持本周训练节拍，继续记录新题'
    : pendingLabels.length
      ? `等待审核：${pendingLabels.join('、')}`
      : submissionGap > 0 && (requireBoth || scoreGap > 0)
        ? `完成第 ${submissionCount + 1} 次有效提交`
        : `补交${missingLabels[0] || '材料'}，再累积 ${scoreGap} 分`;
  const requirement = isComplete
    ? '本周目标已达成，可继续提交'
    : pendingLabels.length
      ? `审核中 · ${pendingLabels.join(' · ')}`
      : !requireBoth && scoreGap > 0 && submissionGap > 0
        ? `还需 ${submissionGap} 次或 ${scoreGap} 分`
        : submissionGap > 0
          ? `还需 ${submissionGap} 次有效提交`
        : missingLabels.length ? `可补交：${missingLabels.join(' · ')}` : `还差 ${scoreGap} 分`;
  const status = isComplete ? '本周已达标' : week.closed ? '本周已截止' : requireBoth ? scoreGap > 0 && submissionGap > 0 ? `还差 ${scoreGap} 分 · ${submissionGap} 次` : scoreGap > 0 ? `还差 ${scoreGap} 分` : submissionGap > 0 ? `还需 ${submissionGap} 次` : '等待审核' : `还需 ${submissionGap} 次或 ${scoreGap} 分`;
  const tone = isComplete ? 'is-done' : week.closed ? 'is-warning' : 'is-warning';
  renderPulseDays(dashboard);
  startDeadlineCountdown(week.remainingSeconds, week.closed);
  const stageScore = $('#stageScore');
  const stageScoreMax = $('.stage-title span:last-child');
  const stageCaption = $('#stageScoreCaption');
  const stageFocus = $('#stageFocus');
  const stageFocusMeta = $('#stageFocusMeta');
  if (stageScore) stageScore.textContent = String(score).padStart(2, '0');
  if (stageScoreMax) stageScoreMax.textContent = `/${minScore}`;
  if (stageCaption) stageCaption.textContent = isComplete ? '本周已达标' : !requireBoth && submissionGap === 0 ? '提交次数已达标' : `还差 ${scoreGap} 分达标`;
  if (stageFocus) stageFocus.textContent = focus;
  if (stageFocusMeta) stageFocusMeta.textContent = requirement;
  const stageWeek = $('#stageWeek');
  if (stageWeek) stageWeek.textContent = `WEEK ${String(week.number).padStart(2, '0')} / ${String(semester.totalWeeks || 0).padStart(2, '0')}`;
  const streak = Number(stats.streakWeeks || 0);
  if ($('#stageStreak')) $('#stageStreak').textContent = `${String(streak).padStart(2, '0')} 周`;

  if ($('#quickSubmissions')) $('#quickSubmissions').textContent = `${submissionCount} 次提交`;
  if ($('#quickPending')) $('#quickPending').textContent = '提交即计分';
  if ($('#quickRank')) $('#quickRank').textContent = stats.rank ? `训练排名 #${stats.rank}` : '排名 —';
  if ($('#rankValue')) $('#rankValue').innerHTML = stats.rank ? `#${stats.rank} <small>/ ${stats.memberCount || 0} 人</small>` : '— <small>/ — 人</small>';
  const rankDelta = stats.previousRank && stats.rank ? stats.previousRank - stats.rank : 0;
  if ($('#rankChange')) $('#rankChange').textContent = rankDelta ? `${rankDelta > 0 ? '↑' : '↓'} ${Math.abs(rankDelta)}` : '—';
  if ($('#rankChangeLabel')) $('#rankChangeLabel').textContent = rankDelta ? '较上周' : '暂无变化';
  if ($('#rankGap')) $('#rankGap').textContent = '本周排名';
  const featuredValue = $('.metric-card.featured .metric-value');
  const featuredFoot = $('.metric-card.featured .metric-foot span');
  const submissionValue = $('.metric-card:nth-child(2) .metric-value');
  const submissionFoot = $('.metric-card:nth-child(2) .metric-foot span');
  if (featuredValue) featuredValue.innerHTML = `${score} <small>/ ${minScore} 分</small>`;
  if (featuredFoot) featuredFoot.textContent = isComplete ? '本周已达标' : !requireBoth && submissionGap === 0 ? '提交次数已达标' : `还差 ${scoreGap} 分达标`;
  if (submissionValue) submissionValue.innerHTML = `${submissionCount} <small>/ ${minSubmissions} 次</small>`;
  if (submissionFoot) submissionFoot.textContent = submissionGap ? `再完成 ${submissionGap} 次即可` : '本周次数已达标';
  const progress = $('.metric-card.featured .progress-track span');
  if (progress) progress.style.width = `${minScore ? Math.min(100, Math.round(score / minScore * 100)) : 0}%`;
  const scoreProgress=$('.metric-card[data-metric="score"] .score-progress-dots');
  if(scoreProgress){
    const target=Math.max(0,Number(minScore)||0),value=Math.max(0,Number(score)||0);
    const slots=Math.min(30,Math.max(1,target)),filled=target?Math.floor(Math.min(1,value/target)*slots):slots;
    scoreProgress.innerHTML=Array.from({length:slots},(_,index)=>`<i${index<filled?' class="done"':''} aria-hidden="true"></i>`).join('');
    scoreProgress.setAttribute('aria-valuemax',String(Math.max(1,target)));
    scoreProgress.setAttribute('aria-valuenow',String(target?Math.min(value,target):1));
    scoreProgress.setAttribute('aria-valuetext',`${value} / ${target} 分${value>=target?'，已达标':''}`);
  }
  const submissionProgress = $('.metric-card[data-metric="submissions"] .submission-dots');
  if (submissionProgress) {
    const target=Math.max(0,Number(minSubmissions)||0),count=Math.max(0,Number(submissionCount)||0);
    const slots=Math.min(20,Math.max(1,target)),filled=target ? Math.floor(Math.min(1,count/target)*slots) : slots;
    submissionProgress.innerHTML=Array.from({length:slots},(_,index)=>`<i${index<filled?' class="done"':''} aria-hidden="true"></i>`).join('');
    submissionProgress.setAttribute('aria-valuemax',String(Math.max(1,target)));
    submissionProgress.setAttribute('aria-valuenow',String(target?Math.min(count,target):1));
    submissionProgress.setAttribute('aria-valuetext',`${count} / ${target} 次${count>=target?'，已达标':''}`);
  }
}

function applyRoleUi(role) {
  canManage = role === 'admin' || role === 'site_admin';
  document.body.classList.toggle('member-mode', !canManage);
  const adminNav = $('#adminNavItem');
  const adminView = $('#adminView');
  if (adminNav) adminNav.hidden = !canManage;
  if (adminView) adminView.hidden = !canManage;
  // The same content modal is used for history and review. Members may read
  // materials, but never see approval or visibility controls.
  const visibility = $('.visibility-setting');
  const reject = $('#rejectReview');
  const approve = $('#approveReview');
  if (visibility) visibility.hidden = !canManage;
  if (reject) reject.hidden = !canManage;
  if (approve) approve.hidden = !canManage;
}

function showToast(text) {
  $('#toastText').textContent = text;
  $('#toast').classList.add('show');
  window.setTimeout(() => $('#toast').classList.remove('show'), 2800);
}

function syncSegmented(group, selected = $('.segment.active', group)) {
  if (!group || !selected) return;
  let indicator = $('.segment-indicator', group);
  if (!indicator) {
    indicator = document.createElement('i');
    indicator.className = 'segment-indicator';
    indicator.setAttribute('aria-hidden', 'true');
    group.prepend(indicator);
  }
  const buttons = $$('.segment', group);
  if (group.classList.contains('segmented--ranking')) {
    group.classList.remove('ranking-tabs-wrapped');
    if (window.matchMedia('(max-width:760px)').matches) {
      const needsWrap = window.matchMedia('(max-width:360px)').matches || buttons.some(button => button.scrollWidth > button.clientWidth);
      group.classList.toggle('ranking-tabs-wrapped', needsWrap);
    }
    indicator.style.removeProperty('transform');
  }
  buttons.forEach((button) => {
    const isSelected = button === selected;
    button.classList.toggle('active', isSelected);
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-selected', String(isSelected));
    button.tabIndex = isSelected ? 0 : -1;
  });
  group.style.setProperty('--segment-x', `${selected.offsetLeft}px`);
  group.style.setProperty('--segment-width', `${selected.offsetWidth}px`);
  group.style.setProperty('--segment-y', `${selected.offsetTop}px`);
  group.style.setProperty('--segment-height', `${selected.offsetHeight}px`);
}

function initSegmentedControls() {
  const rankingResize = new ResizeObserver(entries => {
    const groups = new Set(entries.map(entry => entry.target.closest('.segmented--ranking')));
    groups.forEach(group => { if (group?.offsetWidth) syncSegmented(group); });
  });
  $$('.segmented').forEach((group) => {
    const selected = $('.segment.active', group) || $('.segment', group);
    syncSegmented(group, selected);
    if (group.classList.contains('segmented--ranking')) {
      rankingResize.observe(group);
      $$('.segment', group).forEach(button => rankingResize.observe(button));
    }
    $$('.segment', group).forEach((button, index) => {
      button.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const items = $$('.segment', group);
        const current = items.indexOf(button);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
        items[next]?.focus();
        items[next]?.click();
      });
    });
  });
  window.addEventListener('resize', () => $$('.segmented').forEach((group) => syncSegmented(group)));
}

let feedbackTimer = null;
function playFeedback(type,modified=false) {
  if (type !== 'submission-success') return;
  const layer = $('#feedbackLayer');
  const card = $('#submissionFeedback');
  if (!layer || !card) return;
  card.querySelector('.feedback-copy strong').textContent=modified?'已修改':'提交成功';
  card.querySelector('.feedback-copy small').textContent=modified?'积分与提交统计已按修改内容重新计算。':'已计分并展示，训练节拍继续保持。';
  card.querySelector('.feedback-kicker').textContent=modified?'UPDATED':'PULSE LOGGED';
  window.clearTimeout(feedbackTimer);
  layer.classList.remove('is-visible');
  card.classList.remove('is-playing');
  void card.offsetWidth;
  layer.classList.add('is-visible');
  card.classList.add('is-playing');
  layer.setAttribute('aria-hidden', 'false');
  feedbackTimer = window.setTimeout(() => {
    card.classList.remove('is-playing');
    layer.classList.remove('is-visible');
    layer.setAttribute('aria-hidden', 'true');
  }, 1700);
}

// Store only text fields. File inputs and object URLs never enter localStorage.
let submissionDraftOwner = null;
let activeSubmissionDraftKey = null;
let submissionDraftStorageWarned = false;
const submissionDraftFields = {
  problemUrl: '#problemUrl', logic: '#logicText', code: '#submissionCodeInput',
  language: '#submissionCodeLanguage', markdown: '#blogMarkdownInput',
};
function saveSubmissionDraft() {
  if (!activeSubmissionDraftKey) return;
  try {
    const fields = Object.fromEntries(Object.entries(submissionDraftFields).map(([name, selector]) => [name, $(selector).value]));
    if (Object.entries(fields).some(([name, value]) => name !== 'language' && value.length)) {
      localStorage.setItem(activeSubmissionDraftKey, JSON.stringify({version: 1, fields}));
    } else localStorage.removeItem(activeSubmissionDraftKey);
  } catch (_) {
    if (!submissionDraftStorageWarned) {
      showToast('本地草稿保存失败，请保留当前页面或自行备份文字内容');
      submissionDraftStorageWarned = true;
    }
  }
}
function startSubmissionDraft(record = null, {edit = false} = {}) {
  activeSubmissionDraftKey = null;
  if (!submissionDraftOwner) return;
  const form = $('#submissionForm');
  const target = record ? [edit ? 'edit' : 'resubmit', record.id] : ['new', form.dataset.weekId, form.dataset.recordDate];
  activeSubmissionDraftKey = 'club-submission-draft-v1:' + JSON.stringify([...submissionDraftOwner, ...target]);
  try {
    const draft = JSON.parse(localStorage.getItem(activeSubmissionDraftKey) || 'null');
    if (draft?.version !== 1 || !draft.fields || !Object.keys(submissionDraftFields).every(name => typeof draft.fields[name] === 'string')) return;
    for (const [name, selector] of Object.entries(submissionDraftFields)) $(selector).value = draft.fields[name];
    if (!$('#submissionCodeLanguage').value) $('#submissionCodeLanguage').value = 'text';
    renderCodeDraft();
    renderSubmissionDraftBlog();
    showToast('已恢复本地草稿，图片如需上传请重新选择');
  } catch (_) { /* Unavailable storage or an invalid draft must not block editing. */ }
}
function clearSubmissionDraft() {
  const key = activeSubmissionDraftKey;
  activeSubmissionDraftKey = null;
  if (key) { try { localStorage.removeItem(key); } catch (_) {} }
}
for (const selector of Object.values(submissionDraftFields)) {
  $(selector)?.addEventListener('input', saveSubmissionDraft);
  $(selector)?.addEventListener('change', saveSubmissionDraft);
}
window.addEventListener('pagehide', saveSubmissionDraft);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveSubmissionDraft(); });

function resetSubmissionForm() {
  saveSubmissionDraft();
  activeSubmissionDraftKey = null;
  $('#proofImage').required = !adminTestMode;
  $('#submissionCodeInput').setAttribute('aria-required',String(!adminTestMode));
  const problemInput = $('#problemUrl');
  problemInput.required = !adminTestMode;
  problemInput.placeholder = adminTestMode ? '可留空，自动创建题目记录' : 'https://题目网址';
  const urlLabel = problemInput.closest('.field-label').querySelector('span');
  if (urlLabel) urlLabel.textContent = adminTestMode ? '可选' : '必填';
  const proofLabel = $('#proofImage').closest('.field-label').querySelector('span');
  if (proofLabel) proofLabel.textContent = adminTestMode ? '可选 · 仍按截图计分' : '必填 · 1 分';
  const form = $('#submissionForm');
  if (!form) return;
  $('#cancelSubmissionEdit').hidden=true;
  form.querySelector('button[type=submit]').textContent='提交记录';
  const preview = $('.upload-preview', form);
  if (preview?.dataset.objectUrl) URL.revokeObjectURL(preview.dataset.objectUrl);
  preview?.remove();
  form.reset();
  const title = $('.upload-box strong');
  const hint = $('#proofHint');
  if (title) { title.textContent = '点击上传或粘贴截图'; title.removeAttribute('title'); }
  if (hint) hint.textContent = adminTestMode ? '可留空；上传时支持 PNG、JPG、WebP，不超过 5MB' : '支持 PNG、JPG、WebP，单张不超过 5MB';
  if (typeof clearBlogEditor === 'function') clearBlogEditor();
  setSubmissionCodeDraft('');
  renderSubmissionDraftBlog();
}
function selectSubmissionMaterial(kind){
  for(const value of ['code','blog']){
    const selected=value===kind;
    $(`#submission${value==='code'?'Code':'Blog'}Pane`).hidden=!selected;
    $(`[data-submission-material="${value}"]`).setAttribute('aria-selected',String(selected));
  }
}
function renderCodeDraft(){
  const input=$('#submissionCodeInput'),language=$('#submissionCodeLanguage');
  const layer=$('#submissionCodeHighlight code');
  layer.textContent=input.value+'\n ';
  window.CodeColors?.colorElement(layer,language.value);
  syncCodeEditorScroll();
}
function setSubmissionCodeDraft(markdown){
  const draft=parseSubmissionCode(markdown);
  $('#submissionCodeInput').value=draft.code;
  const language=$('#submissionCodeLanguage');
  language.value=[...language.options].some(option=>option.value===draft.language)?draft.language:'text';
  renderCodeDraft();selectSubmissionMaterial('code');
}
$$('[data-submission-material]').forEach(button=>button.addEventListener('click',()=>selectSubmissionMaterial(button.dataset.submissionMaterial)));
$('#submissionCodeInput').addEventListener('input',renderCodeDraft);
$('#submissionCodeLanguage').addEventListener('change',renderCodeDraft);
function syncCodeEditorScroll(){
  const input=$('#submissionCodeInput'),layer=$('#submissionCodeHighlight');
  layer.scrollTop=input.scrollTop;layer.scrollLeft=input.scrollLeft;
}
$('#submissionCodeInput').addEventListener('scroll',syncCodeEditorScroll);
$('#submissionCodeInput').addEventListener('keydown',event=>{
  if(event.key!=='Tab'||event.shiftKey)return;
  event.preventDefault();const input=event.target;
  input.setRangeText('    ',input.selectionStart,input.selectionEnd,'end');renderCodeDraft();saveSubmissionDraft();
});
function selectReviewMaterial(kind){
  for(const value of ['code','blog']){
    $(`#review${value==='code'?'Code':'Blog'}Pane`).hidden=value!==kind;
    $(`[data-review-material="${value}"]`).setAttribute('aria-selected',String(value===kind));
  }
}
$$('[data-review-material]').forEach(button=>button.addEventListener('click',()=>selectReviewMaterial(button.dataset.reviewMaterial)));
function renderSubmissionDraftBlog(){
  const preview=$('#submissionBlogPreview');if(!preview)return;
  const content=typeof getBlogEditorContent==='function'?getBlogEditorContent():'';
  if(content&&typeof renderSubmissionBlog==='function')renderSubmissionBlog(preview,content);
  else preview.innerHTML='<p class="muted">尚未填写 Blog，可打开 Markdown 编辑器编写并预览。</p>';
}
document.addEventListener('click',event=>{if(event.target.closest('#blogEditorSave'))renderSubmissionDraftBlog();});
let currentSubmissionWeekId = null;
let makeupInFlight = false;
async function completeMakeup(date) {
  if (makeupInFlight) return null;
  makeupInFlight = true;
  const buttons = ['openSubmission'].map(id => $('#'+id)).filter(Boolean);
  buttons.forEach(button => button.disabled = true);
  try {
    const alreadyOpen = pulseDays.find(day => day.date === date)?.makeupOpen === true;
    const result = await window.CurrencyModule.performMakeupCheckin(date, {alreadyOpen});
    if (result) await refreshAfterMutation();
    return result;
  } finally {
    makeupInFlight = false;
    if (selectedPulseDate) selectPulseDay(selectedPulseDate);
  }
}
async function openModal(forceToday = false, correction = null) {
  const selected = forceToday === true ? pulseDays.find(day => day.date === pulseToday)
    : pulseDays.find(day => day.date === selectedPulseDate);
  const date = correction?.record_date || selected?.date || pulseToday;
  const historical = date < pulseToday;
  if (!correction && !adminTestMode && selected && (!selected.canSubmit || historical && (selected.submitted || selected.isMakeup))) return;
  let weekId = correction?.week_id || selected?.weekId || currentSubmissionWeekId;
  if (historical && !adminTestMode && !correction) {
    const permission = await completeMakeup(date);
    if (!permission) return;
    weekId = permission.week_id;
  }
  loadDailyChallenges(); editingSubmission = null; resubmitting = null;
  $('#modalTitle').textContent = historical ? '补交当日记录' : selected?.submitted || selected?.hasSubmission ? '继续提交' : '提交今日记录'; resetSubmissionForm();
  $('#submissionForm').dataset.recordDate = date || '';
  $('#submissionForm').dataset.makeup = historical && !correction ? '1' : '';
  if (date) $('.form-note span').textContent = `记录日期：${date}`;
  $('#submissionForm').dataset.weekId = weekId || '';
  if(adminTestMode) $('.form-note span:last-child').textContent='无需补签券';
  else if (correction) $('.form-note span:last-child').textContent = '修改被驳回记录 · 保留首次提交时间 · 无需补签券';
  else if (historical) $('.form-note span:last-child').textContent = '已开放补交 · 学期结束前有效';
  if (!correction) startSubmissionDraft();
  showSubmissionEditor();
  return true;
}

let submissionScrollState=null;
function showSubmissionEditor(){
  if(!submissionScrollState){
    const properties=['position','top','left','width','overflow'];
    const shell=$('.app-shell');
    submissionScrollState={x:scrollX,y:scrollY,focus:document.activeElement,
      shell,shellInert:shell?.inert,
      styles:properties.map(name=>[name,document.body.style.getPropertyValue(name),document.body.style.getPropertyPriority(name)])};
    Object.assign(document.body.style,{position:'fixed',top:`-${scrollY}px`,left:`-${scrollX}px`,width:'100%',overflow:'hidden'});
    if(shell)shell.inert=true;
  }
  $('#submissionModal').classList.add('open');
  $('#submissionModal').setAttribute('aria-hidden','false');
  $('#modalTitle').focus({preventScroll:true});
}
function closeModal(){
  saveSubmissionDraft();
  activeSubmissionDraftKey = null;
  $('#submissionModal').classList.remove('open');
  $('#submissionModal').setAttribute('aria-hidden','true');
  const state=submissionScrollState;if(!state)return;
  submissionScrollState=null;
  for(const[name,value,priority] of state.styles){
    if(value)document.body.style.setProperty(name,value,priority);
    else document.body.style.removeProperty(name);
  }
  if(state.shell)state.shell.inert=state.shellInert;
  window.scrollTo({left:state.x,top:state.y,behavior:'instant'});
  state.focus?.focus({preventScroll:true});
}

$$('.nav-item[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
wirePulseAtlas();
$$('[data-view-target]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.viewTarget)));
$('#openSubmission')?.addEventListener('click', () => openModal());
['openSubmissionSecondary','emptyAction'].forEach((id) => { const button = $(`#${id}`); if (button) button.addEventListener('click', () => openModal(true)); });
$('#closeSubmission').addEventListener('click',()=>editingSubmission?cancelSubmissionEdit():closeModal());
$('#cancelSubmissionEdit').addEventListener('click',cancelSubmissionEdit);

document.addEventListener('keydown',event=>{
  const blogOpen=$('#blogEditorOverlay')?.getAttribute('aria-hidden')==='false';
  if(event.key==='Escape'){
    if(imageLightbox?.classList.contains('open'))closeImageLightbox();
    else if(!blogOpen&&$('#submissionModal').classList.contains('open')){event.preventDefault();if(editingSubmission)cancelSubmissionEdit();else closeModal();}
  }
  if(event.key!=='Tab'||blogOpen||!$('#submissionModal').classList.contains('open'))return;
  const controls=$$('button:not([disabled]),input:not([disabled]),textarea:not([disabled]),a[href],select:not([disabled])',$('#submissionModal')).filter(e=>e.getClientRects().length);
  const first=controls[0],last=controls[controls.length-1];
  if(event.shiftKey&&(document.activeElement===first||document.activeElement===$('#modalTitle'))){event.preventDefault();last?.focus();}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
});

const reviewData = {};
function fetchMineSubmissions({force = false} = {}) {
  if (mineSubmissionsInFlight && !force) return mineSubmissionsInFlight;
  const request = clubApi.request('/api/submissions?mine=1').then(async (response) => ({
    ok: response.ok,
    response,
    submissions: response.ok ? ((await response.json()).submissions || []) : [],
  }));
  const tracked = request.finally(() => {
    if (mineSubmissionsInFlight === tracked) mineSubmissionsInFlight = null;
  });
  mineSubmissionsInFlight = tracked;
  return tracked;
}

async function loadRecentActivity({force = false} = {}) {
  const list = $('#submissionList');
  if (!list) return;
  const requestVersion = ++activityRequestVersion;
  try {
    const result = await fetchMineSubmissions({force});
    if (requestVersion !== activityRequestVersion) return;
    if (!result.ok) { list.innerHTML = '<div class="queue-empty">最近提交加载失败，请刷新重试</div>'; return; }
    const submissions = result.submissions;
    if (!submissions.length) { list.innerHTML = '<div class="queue-empty">当前还没有提交记录</div>'; return; }
    list.innerHTML = submissions.flatMap(submission => submission.parts.map(part => ({submission, part}))).slice(0, 2).map(({submission, part}) => {
      const status = part.status === 'approved' ? 'approved' : part.status === 'rejected' ? 'rejected' : 'pending';
      const label = part.kind === 'proof' ? '通过截图' : part.kind === 'logic' ? '题解思路' : part.kind === 'code' ? '代码' : 'Blog';
      const statusText = submission.is_duplicate ? '重复题目 · 奖励已撤回' : status === 'approved' ? '已计分' : status === 'rejected' ? '已退回' : '等待处理';
      return `<div class="submission-row"><div class="status-marker ${status}">${status === 'approved' ? '✓' : status === 'rejected' ? '!' : '◷'}</div><div class="submission-info"><strong>${label} · 第 ${submission.week} 周</strong><span>${new Date(submission.submitted_at).toLocaleString('zh-CN')} · ${statusText}</span></div><span class="score">+${part.points || 0} <small>分</small></span><span class="status-tag ${status}">${status === 'approved' ? '已通过' : status === 'rejected' ? '已退回' : '待审核'}</span></div>`;
    }).join('');
  } catch (error) { if (requestVersion === activityRequestVersion) list.innerHTML = '<div class="queue-empty">最近提交加载失败，请检查网络连接</div>'; }
}
function groupMySubmissions(submissions) {
  const sorted = [...submissions].sort((a, b) => b.record_date.localeCompare(a.record_date)
    || Date.parse(b.submitted_at) - Date.parse(a.submitted_at) || b.id - a.id);
  const groups = new Map();
  for (const item of sorted) {
    if (!groups.has(item.record_date)) groups.set(item.record_date, []);
    groups.get(item.record_date).push(item);
  }
  return [...groups];
}

async function loadMySubmissions({force = false} = {}) {
  const page = $('#submissionsView');
  if (!page) return;
  const requestVersion = ++submissionsRequestVersion;
  try {
    const result = await fetchMineSubmissions({force});
    if (requestVersion !== submissionsRequestVersion) return;
    if (!result.ok) { const empty = $('.empty-state', page); if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">!</div><h2>提交记录加载失败</h2><p>请刷新页面后重试。</p>'; } return; }
    const submissions = result.submissions;
    ownRecords.clear(); submissions.forEach(item => ownRecords.set(item.id, item));
    const empty = $('.empty-state', page);
    page.querySelector('.my-submissions-live')?.remove();
    if (!submissions.length) { if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">□</div><h2>这里会留下你的训练轨迹</h2><p>当前还没有提交记录。</p><button class="secondary-button" id="emptyAction" type="button">提交今日记录</button>'; $('#emptyAction')?.addEventListener('click', () => openModal(true)); } return; }
    const list = document.createElement('div');
    list.className = 'panel my-submissions-live';
    const today = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
    const dateFormat = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', year:'numeric', month:'long', day:'numeric', weekday:'short'});
    list.innerHTML = `<div class="panel-heading"><div><h2>历史提交记录</h2></div><span class="muted">共 ${submissions.length} 条</span></div>` + groupMySubmissions(submissions).map(([day, items]) => {
      const label = `${day === today ? '今天 · ' : ''}${dateFormat.format(new Date(`${day}T12:00:00+08:00`))}`;
      return `<section class="my-submission-day"><h3 class="my-submission-date">${escapeHtml(label)}<small>${items.length} 条</small></h3>` + items.map((item) => {
      const key = `mine-${item.id}`;
      const proof = item.parts.find((part) => part.kind === 'proof');
      const logic = item.parts.find((part) => part.kind === 'logic');
      const blog = item.parts.find((part) => part.kind === 'blog');
      const reviewStatus = item.parts.some((part) => part.status === 'pending') ? 'pending' : item.parts.some((part) => part.status === 'approved') ? 'approved' : 'rejected';
      reviewData[key] = {name:item.member_name, initial:item.member_name.slice(0,1), time:new Date(item.submitted_at).toLocaleString('zh-CN'), logic:logic?.text || '', logicPart:logic || null, visibility:item.visibility || 'team', status:reviewStatus, submissionId:item.id, memberId:item.member_id, problemTitle:item.problem_title || '', problemUrl:item.problem_url || '', upload:proof?.upload, fileName:'通过截图', blog:blog?.text || '', code:item.parts.find(part=>part.kind==='code')?.text || ''};
      const approved = item.parts.filter((part) => part.status === 'approved').reduce((sum, part) => sum + (part.points || 0), 0);
      return `<div class="live-submission-row">${problemPlatformMarkup(item.problem_url)}<div class="live-submission-info"><strong>${escapeHtml(uiProblemTitle(item.problem_title))}</strong><small>提交于 ${new Date(item.submitted_at).toLocaleString('zh-CN')}${item.rejection_note ? (item.is_duplicate ? ' · ' : ' · 退回原因：') + escapeHtml(item.rejection_note) : ''}</small></div><span class="score">+${approved} 分</span><button class="review-view secondary-button" type="button" data-review="${key}">查看内容</button>${item.can_resubmit ? `<button class="secondary-button" data-resubmit="${item.id}">修改重交</button>` : ""}</div>`;
      }).join('') + '</section>';
    }).join('');
    if (empty) empty.hidden = true;
    page.appendChild(list);
    $$('.review-view', list).forEach((button) => button.addEventListener('click', () => openReview(button.dataset.review)));
  } catch (error) { if (requestVersion === submissionsRequestVersion) { const empty = $('.empty-state', page); if (empty) { empty.hidden = false; empty.innerHTML = '<div class="empty-icon">!</div><h2>提交记录加载失败</h2><p>请检查网络连接后重试。</p>'; } } }
}
const reviewModal = $('#reviewModal');
let activeReviewKey = null;
let activeSubmissionId = null;
let reviewReturnsToHistory = false;
function openReview(key, returnToHistory = false) {
  const data = reviewData[key];
  if (!data) return;
  reviewReturnsToHistory = returnToHistory;
  const closeControl = $('#closeReview');
  closeControl.innerHTML = returnToHistory ? '<svg class="ui-chevron" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m15 5-7 7 7 7"/></svg>' : '×';
  closeControl.setAttribute('aria-label', returnToHistory ? '返回个人信息' : '关闭');
  closeControl.title = returnToHistory ? '返回个人信息' : '关闭';
  activeReviewKey = key;
  activeSubmissionId = data.submissionId || null;
  const ownRecord = key.startsWith('mine-') ? ownRecords.get(Number(data.submissionId)) : null;
  $('#ownReviewActions').hidden = !ownRecord;
  $('#editOwnSubmission').disabled = !ownRecord?.can_edit;
  $('#deleteOwnSubmission').disabled = !ownRecord?.can_delete;
  $('#ownReviewHint').textContent = ownRecord && !ownRecord.can_edit ? '该周已截止或学期已归档，无法编辑' : '';

  $('#reviewModalTitle').textContent = uiProblemTitle(data.problemTitle || ownRecord?.problem_title || '查看提交内容');
  $('#reviewMember').textContent = uiMemberName(data.name);
  setDetailAvatar($('#reviewAvatar'),data.memberId,data.name);
  $('#reviewTime').textContent = data.time;
  const originalProblem = $('#reviewOriginalProblem');
  originalProblem.hidden = true;
  originalProblem.removeAttribute('href');
  try {
    const url = new URL(data.problemUrl);
    if (['https:', 'http:'].includes(url.protocol)) {
      originalProblem.href = url.href;
      originalProblem.hidden = false;
    }
  } catch { /* Legacy records without a problem URL have no outbound action. */ }
  const reviewStatus = $('.review-author .status-tag');
  if (reviewStatus) {
    const approved = data.status === 'approved';
    reviewStatus.textContent = approved ? '已通过' : data.status === 'rejected' ? '已退回' : '待审核';
    reviewStatus.className = `status-tag ${approved ? 'approved' : data.status === 'rejected' ? 'rejected' : 'pending'}`;
  }
  const logicPart = data.logicPart;
  const hasLogic = Boolean(data.logic?.trim() || logicPart?.link || logicPart?.upload);
  const logicPoints = hasLogic && logicPart?.status === 'approved' ? Number(logicPart.points) || 0 : 0;
  $('#reviewLogicStatus').textContent = !hasLogic ? '未提交' : logicPart?.status === 'pending' ? '待审核' : logicPart?.status === 'rejected' ? '已退回' : `+${logicPoints} 分`;
  $('#reviewLogicStatus').className = logicPoints > 0 ? 'score-chip' : 'empty-chip';
  $('#reviewLogic').textContent = data.logic || '未提交题解思路。';
  const blog = typeof data.blog === 'string' ? data.blog.trim() : '';
  const hasBlog = Boolean(blog);
  const code=typeof data.code==='string'?data.code:'';
  $('.review-modal').classList.toggle('has-blog', hasBlog||Boolean(code));
  $('#reviewCodeStatus').textContent=code?parseSubmissionCode(code).language:'未提交';
  if(code)renderSubmissionBlog($('#reviewCode'),code);else $('#reviewCode').textContent='未提交代码';
  selectReviewMaterial(code?'code':'blog');
  $('#reviewBlogStatus').textContent = hasBlog ? '已提交' : '未提交';
  $('#reviewBlogStatus').className = hasBlog ? 'score-chip' : 'empty-chip';
  const blogContainer = $('#reviewBlog');
  blogContainer.classList.toggle('blog-rendered', hasBlog);
  if (hasBlog) renderSubmissionBlog(blogContainer, blog);
  else blogContainer.textContent = '未提交 Blog';
  const image = $('#reviewImage');
  const fallback = $('#reviewImageFallback');
  image.onerror = () => { image.classList.remove('visible'); fallback.classList.remove('hidden'); $('#reviewFileMeta').textContent = '图片加载失败，请检查媒体文件服务'; };
  if (data.upload) { image.src = `${data.upload}${data.upload.includes('?') ? '&' : '?'}v=${Date.now()}`; image.classList.add('visible'); fallback.classList.add('hidden'); } else { image.removeAttribute('src'); image.classList.remove('visible'); fallback.classList.remove('hidden'); }
  $('#reviewFileName').textContent = data.fileName || '通过截图';
  $('#reviewFileMeta').textContent = data.upload ? '已上传，可点击放大查看' : '当前记录没有可预览图片';
  reviewModal.classList.add('open');
  reviewModal.setAttribute('aria-hidden','false');
}
function closeReview() { reviewModal.classList.remove('open'); reviewModal.setAttribute('aria-hidden','true'); }
$$('.review-view').forEach((button) => button.addEventListener('click', () => openReview(button.dataset.review)));
function wireShowcaseProofs(root=document) {
  $$('.proof-image-button', root).forEach((button) => {
    if (button.dataset.proofWired) return;
    button.dataset.proofWired = 'true';
    button.addEventListener('click', () => openReview(button.dataset.review));
  });
}
$('#closeReview').addEventListener('click', () => {
  const restoreHistory = reviewReturnsToHistory;
  closeReview();
  reviewReturnsToHistory = false;
  if (restoreHistory) {
    historyModal.classList.add('open'); historyModal.setAttribute('aria-hidden', 'false');
    const origin = [...historyModal.querySelectorAll('.history-view')].find(button => button.dataset.review === activeReviewKey);
    (origin || $('#closeHistory')).focus();
  }
});

const imageLightbox = $('#imageLightbox');
function closeImageLightbox() { imageLightbox.classList.remove('open'); imageLightbox.setAttribute('aria-hidden','true'); $('#lightboxImage').removeAttribute('src'); }
$('#zoomReviewImage').addEventListener('click', () => {
  const source = $('#reviewImage');
  if (!source.classList.contains('visible') || !source.src) { showToast('当前记录没有可预览图片'); return; }
  $('#lightboxImage').src = source.src;
  $('#lightboxImage').alt = source.alt || '放大后的通过截图';
  imageLightbox.classList.add('open');
  imageLightbox.setAttribute('aria-hidden','false');
});
$('#closeImageLightbox').addEventListener('click', closeImageLightbox);

function wireRankingControls(root=document) {
  $$('[data-ranking]', root).forEach(button => button.addEventListener('click', async () => {
    const panel = button.closest('.panel');
    syncSegmented(button.closest('.segmented'), button);
    const target = panel?.classList.contains('full-leaderboard') ? '#leaderboardListFull' : '#leaderboardList';
    const selected = rankingSelection(target);
    renderLeaderboard(selected.scope,target);
    await loadLeaderboard(selected.scope,selected.platform,{period:selected.period});
  }));
  $$('[data-solved-period]', root).forEach(select => select.addEventListener('change',async () => {
    const target = select.closest('.full-leaderboard') ? '#leaderboardListFull' : '#leaderboardList';
    const selected = rankingSelection(target);
    renderLeaderboard('solved',target);
    await loadLeaderboard('solved',selected.platform,{period:select.value});
  }));
  $$('[data-rating-platform]', root).forEach(select => select.addEventListener('change',async () => {
    const target = select.closest('.full-leaderboard') ? '#leaderboardListFull' : '#leaderboardList';
    renderLeaderboard('rating',target);
    await loadLeaderboard('rating',select.value);
  }));
}

wireRankingControls();
initSegmentedControls();

function toggleTeamMenu(open) {
  const menu = $('#teamMenu');
  menu.classList.toggle('open', open);
  menu.inert = !open;
  $('#teamButton').setAttribute('aria-expanded', String(open));
}
$('#teamButton').addEventListener('click', () => toggleTeamMenu(!$('#teamMenu').classList.contains('open')));
$('#teamButton').addEventListener('keydown', event => {
  if (event.key !== 'ArrowDown') return;
  event.preventDefault(); toggleTeamMenu(true); $('#teamMenu button')?.focus();
});
$('#teamMenu').addEventListener('keydown', event => {
  if (event.key === 'Escape') {event.preventDefault();toggleTeamMenu(false);$('#teamButton').focus();return;}
  if (event.key === 'Tab') {toggleTeamMenu(false);return;}
  if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
  event.preventDefault();
  const buttons = $$('#teamMenu button');
  const index = buttons.indexOf(document.activeElement);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
  buttons[next]?.focus();
});
// Team choices are populated from /api/me. Never switch to placeholder teams.
document.addEventListener('click', (event) => { if (!event.target.closest('.team-switcher')) toggleTeamMenu(false); });

$('#submissionForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  if(!adminTestMode&&!$('#submissionCodeInput').value.trim()){selectSubmissionMaterial('code');$('#submissionCodeInput').focus();showToast('请填写解题代码');return;}
  const submitButton = form.querySelector('button[type="submit"]');
  if (submitButton?.disabled) return;
  if (submitButton) { submitButton.disabled = true; submitButton.setAttribute('aria-busy', 'true'); submitButton.dataset.label = submitButton.textContent; submitButton.textContent = '正在提交…'; }
  if (demoMode) {
    clearSubmissionDraft();
    closeModal();
    resetSubmissionForm();
    playFeedback('submission-success');
    showToast('演示提交成功，已计分并展示');
    if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交记录'; }
    return;
  }
  saveSubmissionDraft();
  const wasEditing=Boolean(editingSubmission);
  const formData = new FormData(form);
  formData.set('week_id', form.dataset.weekId || '');
  formData.set('record_date', form.dataset.recordDate || '');
  if ($('#proofImage').files[0]) formData.set('proof', $('#proofImage').files[0]);
  else formData.delete('proof');
  if (editingSubmission) formData.set('version', ownRecords.get(editingSubmission)?.version || '');
  formData.set('logic', $('#logicText').value);
  const blogContent = typeof getBlogEditorContent === 'function' ? getBlogEditorContent() : '';
  formData.set('blog', blogContent);
  try {
    const response = await clubApi.request(editingSubmission ? `/api/submissions/${editingSubmission}/edit` : resubmitting ? `/api/submissions/${resubmitting}/resubmit` : '/api/submissions', {method:'POST', body:formData});
    if (response.status === 401 || response.status === 403) throw new Error('请先登录后再提交');
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || '提交失败，请稍后重试');
    }
  } catch (error) { showToast(error.message || '提交失败，请稍后重试'); if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = submitButton.dataset.label || '提交记录'; } return; }
  clearSubmissionDraft();
  closeModal();
  resetSubmissionForm();
  playFeedback('submission-success',wasEditing);
  showToast(wasEditing?'已修改，积分与统计已重新计算':'提交成功，已计分并展示');
  editingSubmission=null;resubmitting=null;submissionEditReturnState=null;
  refreshAfterMutation({refreshAdmin: canManage});
  if (submitButton) { submitButton.disabled = false; submitButton.removeAttribute('aria-busy'); submitButton.textContent = '提交记录'; }
});
document.addEventListener('paste', (event) => {
  if (!$('#submissionModal').classList.contains('open') || event.defaultPrevented) return;
  if ($('#blogEditorOverlay')?.getAttribute('aria-hidden') === 'false') return;
  const clipboard = event.clipboardData;
  const file = Array.from(clipboard?.files || []).find(file => file.type.startsWith('image/'))
    || Array.from(clipboard?.items || []).find(item => item.kind === 'file' && item.type.startsWith('image/'))?.getAsFile();
  if (!file) return;
  event.preventDefault();
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    showToast('截图仅支持 PNG、JPG、WebP 格式');
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showToast('截图不能超过 5MB');
    return;
  }
  const transfer = new DataTransfer();
  transfer.items.add(file);
  const input = $('#proofImage');
  input.files = transfer.files;
  input.dispatchEvent(new Event('change', {bubbles: true}));
});
$('#proofImage').addEventListener('change', (event) => {
  const file = event.target.files?.[0];
  const box = $('.upload-box');
  if (!file || !box) return;
  let preview = box.querySelector('.upload-preview');
  if (!preview) { preview = document.createElement('img'); preview.className = 'upload-preview'; box.prepend(preview); }
  if (preview.dataset.objectUrl) URL.revokeObjectURL(preview.dataset.objectUrl);
  preview.alt = '已选择的通过截图预览';
  const objectUrl = URL.createObjectURL(file);
  preview.src = objectUrl;
  preview.dataset.objectUrl = objectUrl;
  const title = box.querySelector('strong'); if (title) { title.textContent = file.name; title.title = file.name; }
  const hint = box.querySelector('small'); if (hint) hint.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB`;
});

function clearStaticPreview() {
  const loading = '<div class="queue-empty">正在加载真实数据…</div>';
  Object.keys(rankingData).forEach(key => delete rankingData[key]);
  ['#leaderboardList', '#leaderboardListFull'].forEach((selector) => {
    const element = $(selector);
    if (element) { element.innerHTML = loading; element.setAttribute('aria-live', 'polite'); }
  });
  ['#submissionList', '#showcaseGrid', '#membersGrid', '#reviewList', '#historyList', '#submissionsView .empty-state', '#reportsPlaceholder'].forEach((selector) => {
    const element = $(selector);
    if (element) { element.innerHTML = loading; element.setAttribute('aria-live', 'polite'); }
  });
  const rank = $('.your-rank strong');
  if (rank) rank.textContent = '—';
  const rankChange = $('.your-rank .rank-up');
  if (rankChange) rankChange.textContent = '加载中…';
  const leaderboardLabel = $('#leaderboardWeekLabel');
  const showcaseLabel = $('.showcase-toolbar .filter-chip');
  if (leaderboardLabel) leaderboardLabel.textContent = '加载中…';
  if (showcaseLabel) showcaseLabel.textContent = '加载中…';
  const featuredDelta = $('.metric-card.featured .metric-foot span:nth-child(2)');
  if (featuredDelta) featuredDelta.textContent = '—';
  const demoCallout = $('.mini-callout');
  if (demoCallout) demoCallout.hidden = true;
  const stageScore = $('#stageScore');
  const stageScoreMax = $('.stage-title span:last-child');
  const stageCaption = $('#stageScoreCaption');
  const stageFocus = $('#stageFocus');
  const stageFocusMeta = $('#stageFocusMeta');
  if (stageScore) stageScore.textContent = '—';
  if (stageScoreMax) stageScoreMax.textContent = '/—';
  if (stageCaption) stageCaption.textContent = '等待真实数据';
  if (stageFocus) stageFocus.textContent = '等待真实数据';
  if (stageFocusMeta) stageFocusMeta.textContent = '当前周数据加载中';
  if ($('#pulseFocus')) $('#pulseFocus').textContent = '等待真实数据';
  if ($('#pulseStatus')) $('#pulseStatus').textContent = '加载中…';
  $$('.metric-card .metric-value').forEach((element) => { element.innerHTML = '—'; });
  $$('.metric-card .metric-foot span:first-child').forEach((element) => { element.textContent = '等待真实数据'; });
  const welcomeKicker = $('.welcome-row .kicker');
  const welcomeNote = $('.welcome-row .muted');
  if (welcomeKicker) welcomeKicker.textContent = '当前学期 · 当前周次';
  if (welcomeNote) welcomeNote.textContent = '正在加载本周截止时间…';
  const search = $('#memberSearch');
  if (search) { search.name = 'member_search'; search.autocomplete = 'off'; search.placeholder = '搜索成员姓名…'; search.setAttribute('aria-label', '搜索成员姓名'); }
  $$('.inline-count').forEach((element) => { element.textContent = '—'; });
  $$('.count-badge').forEach((element) => { element.textContent = '—'; });
  $$('.admin-stat strong').forEach((element) => { element.textContent = '—'; });
  if ($('#lastWeekIncompleteTitle')) $('#lastWeekIncompleteTitle').textContent = '上周未达标成员';
  if ($('#lastWeekIncompleteList')) $('#lastWeekIncompleteList').innerHTML = '<div class="queue-empty">等待真实数据…</div>';
  const formNote = $('.form-note');
  if (formNote) {
    const weekLabel = formNote.querySelector('span:first-child');
    const deadlineLabel = formNote.querySelector('span:last-child');
    if (weekLabel) weekLabel.textContent = '当前周次加载中…';
    if (deadlineLabel) deadlineLabel.textContent = '截止时间加载中…';
  }
  ['#quickSubmissions', '#quickPending', '#quickRank', '#stageWeek', '#stageStreak', '#rankValue', '#rankChange', '#rankGap', '#streakValue', '#yourRankValue', '#yourRankChange'].forEach((selector) => { const element = $(selector); if (element) element.textContent = '—'; });
  if ($('#teamName')) $('#teamName').textContent = '正在加载…';
  const profile = $('.profile-chip');
  if (profile) { profile.querySelector('strong').textContent = '正在加载…'; profile.querySelector('small').textContent = '正在验证登录状态'; }
}

async function loadDashboardSummary({forceMine = false} = {}) {
  const dashboardResponse = await clubApi.request('/api/dashboard');
  if (!dashboardResponse.ok) return null;
  const dashboard = await dashboardResponse.json();
  await loadTrainingActivity(dashboard);
  const scoreValue = $('.metric-card.featured .metric-value');
  const scoreFoot = $('.metric-card.featured .metric-foot span');
  const submissionValue = $('.metric-card:nth-child(2) .metric-value');
  if (scoreValue && dashboard.semester) scoreValue.innerHTML = `${dashboard.score} <small>/ ${dashboard.semester.minScore} 分</small>`;
  if (scoreFoot && dashboard.semester) scoreFoot.textContent = dashboard.score >= dashboard.semester.minScore ? '本周已达标' : `还差 ${Math.max(0, dashboard.semester.minScore - dashboard.score)} 分达标`;
  if (submissionValue && dashboard.semester) submissionValue.innerHTML = `${dashboard.submissions} <small>/ ${dashboard.semester.minSubmissions} 次</small>`;
  currentSubmissionWeekId = dashboard.current_week?.id || null;
  if (dashboard.current_week) {
    const select = $('#historyWeek');
    if (select) select.innerHTML = [dashboard.current_week.number, dashboard.current_week.number - 1, dashboard.current_week.number - 2].filter((number) => number > 0).map((number) => `<option value="${number}">第 ${String(number).padStart(2, '0')} 周</option>`).join('');
    const note = $('.form-note span');
    if (note) note.textContent = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周`;
    const kicker = $('.welcome-row .kicker');
    if (kicker) kicker.textContent = `${dashboard.semester?.name || '当前学期'} · 第 ${String(dashboard.current_week.number).padStart(2, '0')} 周`;
    const label = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周 · ${dashboard.semester?.name || '当前学期'}`;
    const leaderboardLabel = $('#leaderboardWeekLabel');
    if (leaderboardLabel) leaderboardLabel.textContent = '当前团队 · 最新数据';
    const showcaseLabel = $('.showcase-toolbar .filter-chip');
    if (showcaseLabel) showcaseLabel.textContent = `第 ${String(dashboard.current_week.number).padStart(2, '0')} 周⌄`;
  }
  const mineResult = await fetchMineSubmissions({force: forceMine});
  if (mineResult.ok) applyLiveDashboardState(dashboard, mineResult.submissions);
  return dashboard;
}

async function loadLeaderboard(scope = 'checkin', platform='codeforces', {force=false,period='semester'} = {}) {
  const key = rankingKey(scope,platform,period);
  if (!force && leaderboardInFlight.has(key)) return leaderboardInFlight.get(key);
  const request = (async () => {
    try {
      const response = await clubApi.request(`/api/leaderboard?scope=${encodeURIComponent(scope)}&platform=${encodeURIComponent(platform)}&period=${encodeURIComponent(period)}`);
      const payload = await response.json();
      if (leaderboardInFlight.get(key) !== request) return false;
      if (!response.ok) throw new Error(payload.error || '榜单加载失败');
      rankingData[key] = payload.rows || [];
      for (const target of ['#leaderboardList','#leaderboardListFull']) {
        const selected = rankingSelection(target);
        if (rankingKey(selected.scope,selected.platform,selected.period) === key) renderLeaderboard(scope,target);
      }
      return true;
    } catch (error) {
      for (const target of ['#leaderboardList','#leaderboardListFull']) {
        const selected = rankingSelection(target);
        if (rankingKey(selected.scope,selected.platform,selected.period) === key && !rankingData[key]) $(target).innerHTML = `<div class="queue-empty" role="alert">${escapeHtml(error.message)}</div>`;
      }
      return false;
    }
  })();
  leaderboardInFlight.set(key,request);
  request.finally(() => {if (leaderboardInFlight.get(key) === request) leaderboardInFlight.delete(key);});
  return request;
}

async function refreshAfterMutation({refreshAdmin = false} = {}) {
  const selections=new Map(['#leaderboardList','#leaderboardListFull'].map(target=>{
    const selected=rankingSelection(target);return [rankingKey(selected.scope,selected.platform,selected.period),selected];
  }));
  const tasks = [
    window.CurrencyModule?.init(),
    loadRecentActivity({force: true}),
    loadDashboardSummary({forceMine:true}),
    ...[...selections.values()].map(selected=>loadLeaderboard(selected.scope,selected.platform,{force:true,period:selected.period})),
  ];
  if (currentView === 'submissions') tasks.push(loadMySubmissions());
  if (refreshAdmin && currentView === 'admin') tasks.push(loadAdminQueue());
  await Promise.allSettled(tasks);
  renderLeaderboard();
  renderLeaderboard('checkin','#leaderboardListFull');
}

window.addEventListener('platform-solved-updated', () => refreshAfterMutation());
window.addEventListener('personal-profile-saved', event => {
  const id = Number(event.detail?.memberId);
  const source = event.detail?.avatar;
  if (id && source !== undefined) memberAvatarSources.set(id, source);
  document.querySelectorAll('.synced-member-avatar').forEach(holder => {
    if (!id || Number(holder.dataset.avatarMember) !== id || source === undefined) return;
    if (holder.querySelector('img')?.getAttribute('src') === source) return;
    holder.querySelector('img')?.remove();
    if (!source) return;
    const image = document.createElement('img');
    image.alt = ''; image.decoding = 'async';
    image.onload = () => { if (image.parentElement === holder) holder.replaceChildren(image); };
    image.onerror = () => { if (image.parentElement === holder) holder.textContent = holder.dataset.avatarFallback || ''; };
    image.src = source;
    holder.append(image);
  });
  refreshAfterMutation();
  if (currentView === 'members') loadMembersLive();
});

async function loadLiveData() {
  try {
    const meResponse = await clubApi.request('/api/me');
    if (meResponse.status === 401) { window.location.href = '/auth.html'; return; }
    if (!meResponse.ok) { showToast('账户信息加载失败，请刷新重试'); return; }
    if (!(meResponse.headers.get('content-type') || '').includes('application/json')) {
      if (meResponse.url.includes('/auth.html')) window.location.href = '/auth.html';
      return;
    }
    const me = await meResponse.json();
    submissionDraftOwner = me.account && (me.test_target_team?.id || me.team?.id)
      ? [me.account, me.test_target_team?.id || me.team.id, !!me.test_mode] : null;
    adminTestMode=!!me.test_mode;
    if(adminTestMode)me.name=uiMemberName(me.name);
    if(me.site_admin||adminTestMode){
      let toggle=document.querySelector('#adminTestToggle');
      if(!toggle){toggle=document.createElement('button');toggle.id='adminTestToggle';toggle.type='button';toggle.className='secondary-button';document.querySelector('.topbar-actions').prepend(toggle);}
      toggle.textContent=adminTestMode?'退出测试模式':'开启测试模式';toggle.setAttribute('aria-pressed',String(adminTestMode));
      toggle.onclick=async()=>{toggle.disabled=true;try{const response=await clubApi.request('/api/admin-test-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!adminTestMode})});const result=await response.json();if(!response.ok)throw Error(result.error);location.href=adminTestMode?'/?view=admin':'/';}catch(error){showToast(error.message);toggle.disabled=false;}};
    }
    window.PersonalProfile?.init(me);
    await window.CurrencyModule?.init();
    initWorkbench(me);
    applyRoleUi(me.site_admin ? 'site_admin' : me.is_team_manager ? 'admin' : me.role);
    if (!me.team && !me.site_admin) { window.location.href = '/team-select.html'; return; }
    document.body.classList.toggle('site-admin-mode', me.site_admin && !me.can_submit);
    if (!me.can_submit) ['openSubmission','openSubmissionSecondary','emptyAction','pulseJump'].forEach(id => { if ($('#'+id)) $('#'+id).hidden=true; });

    if (me.team?.name) { $('#teamName').textContent = me.test_target_team?.name||me.team.name; const subtitle = $('.team-button-copy small'); if (subtitle) subtitle.textContent = adminTestMode?'当前团队':me.team.code || '当前团队'; }
    if (Array.isArray(me.teams)) {
      const menu = $('#teamMenu');
      menu.innerHTML = '<div class="team-menu-options" role="group"></div>';
      const options = $('.team-menu-options', menu);
      me.teams.forEach(team => {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.teamId = team.team_id;
        button.setAttribute('role', 'menuitemradio');
        button.setAttribute('aria-checked', String(String(team.team_id) === String(me.test_target_team?.id||me.team?.id)));
        button.innerHTML = `<span class="team-avatar small">${escapeHtml((team.team__name || '').slice(0,1))}</span><span class="team-menu-name">${escapeHtml(team.team__name)}</span>`;
        button.addEventListener('click', async () => {
          if (button.disabled) return;
          button.disabled = true;
          try {
            const response = await clubApi.request('/api/team/select', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({team_id:team.team_id})});
            if (response.ok) location.reload(); else showToast('无权进入该团队');
          } catch(error) {showToast('团队切换失败，请重试');}
          finally {button.disabled=false;}
        });
        options.append(button);
      });
      const join = document.createElement('button');
      join.type = 'button'; join.className = 'team-menu-join'; join.setAttribute('role','menuitem');
      join.innerHTML = '<svg class="ui-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span>加入团队</span>';
      join.addEventListener('click', () => {toggleTeamMenu(false);window.openJoinTeamDialog();});
      if(!adminTestMode)menu.append(join);
    }
    const profile = $('.profile-chip');
    if (profile) { const avatar = profile.querySelector('.profile-avatar'); const name = profile.querySelector('strong'); const role = profile.querySelector('small'); if (avatar) avatar.textContent = (me.name || '').slice(0, 1); if (name) name.textContent = me.name || '当前账号'; if (role) role.textContent = me.site_admin ? '系统管理员' : me.is_team_manager ? '团队管理员' : '普通用户'; }
    window.PersonalProfile?.updateHeader(me);
    if (!me.team) {
      $('#teamName').textContent = '尚未创建团队';
      $('#dashboardView').innerHTML = '<div class="page-heading"><h1>欢迎回来，系统管理员</h1></div><div class="panel empty-state"><h2>从创建第一个团队开始</h2><p>点击左下角管理工作台，配置团队、成员和题目解析。</p><button class="primary-button" id="openEmptyWorkbench">打开管理工作台</button></div>';
      $('#openEmptyWorkbench').onclick = () => setView('admin');
      const requestedView = new URLSearchParams(location.search).get('view');
      if (pageTitles[requestedView]) setView(requestedView);
      return;
    }
    await Promise.allSettled([loadRecentActivity(), loadDashboardSummary(), loadLeaderboard('checkin')]);
    renderLeaderboard();
    const requestedView = new URLSearchParams(location.search).get('view');
    if (pageTitles[requestedView]) setView(requestedView);
  } catch (error) { showToast(error.message || '页面数据加载失败，请刷新重试'); }
}
async function loadMembersLive() {
  const grid = $('#membersGrid');
  if (!grid) return;
  const requestVersion = ++membersRequestVersion;
  // Never leave the built-in preview members visible while the real team
  // roster is loading. Otherwise the demo cards can appear to overwrite data.
  grid.innerHTML = '<div class="queue-empty">正在加载团队成员…</div>';
  try {
    const response = await clubApi.request('/api/members');
    if (requestVersion !== membersRequestVersion) return;
    if (!response.ok) {
      grid.innerHTML = '<div class="queue-empty">成员列表加载失败，请刷新重试</div>';
      return;
    }
    const payload = await response.json();
    if (requestVersion !== membersRequestVersion) return;
    const members = payload.members || [];
    if (!members.length) {
      grid.innerHTML = '<div class="queue-empty">当前团队暂无成员数据</div>';
      return;
    }
grid.innerHTML = members.map((member) => `<article class="member-card" data-member="${escapeHtml(uiMemberName(member.name))}"><div class="member-card-head"><button type="button" class="member-identity-entry" data-member-history="${member.id}">${memberAvatar(member.id,member.name,'member-avatar dark',member.avatar)}<span><strong>${escapeHtml(uiMemberName(member.name))}</strong><small>${member.is_system_admin ? '系统管理员' : member.role === 'admin' ? '团队管理员' : '普通用户'}</small></span></button><span class="member-status">活跃</span></div><div class="member-card-stats"><div><span>本周提交</span><strong>${member.submissions} <small>次</small></strong></div><div><span>本周积分</span><strong>${member.score}</strong></div><div><span>本周 AC 题数</span><strong>${member.ac_problems ?? 0} <small>题</small></strong></div></div><div class="member-card-actions">${member.can_kick ? `<button class="member-action-button danger" type="button" data-member-kick="${member.id}" data-team-id="${member.team_id}" data-name="${escapeHtml(uiMemberName(member.name))}" data-team-name="${escapeHtml(payload.team_name)}">踢出用户</button>` : ''}${member.can_manage_role ? `<button class="member-action-button" type="button" data-member-role="${member.role === 'admin' ? 'member' : 'admin'}" data-team-id="${member.team_id}" data-account="${escapeHtml(member.account)}">${member.role === 'admin' ? '取消团队管理' : '设置团队管理'}</button>` : ''}</div></article>`).join('');
    members.forEach((member,index) => {
      if (!Object.hasOwn(member,'currency_balance')) return;
      const button=document.createElement('button'); button.type='button'; button.className='member-currency-button';
      button.textContent=`${member.currency_balance} RBC · 调整`;
      button.setAttribute('aria-label',`调整${member.name}的 RBC 余额`);
      grid.children[index].querySelector('.member-card-head').append(button);
      button.onclick=()=>window.CurrencyAdminModule.showBalanceAdjustment(member);
    });
    $$('.member-identity-entry', grid).forEach((button) => button.addEventListener('click', () => openMemberHistory(button.dataset.memberHistory)));
  } catch (error) {
    grid.innerHTML = '<div class="queue-empty">成员列表加载失败，请检查网络连接</div>';
  }
}
clearStaticPreview(); loadLiveData();
const historyModal = $('#memberHistoryModal');
let activeHistoryMemberId = null;
let historyFromMemberList = false;
let memberProfileNextPage = null;
let memberProfileBusy = false;
let memberProfileReturnFocus = null;
function openMemberHistory(key) {
  if (!/^\d+$/.test(String(key))) { showToast('请从成员列表打开个人信息'); return; }
  historyFromMemberList = true;
  activeHistoryMemberId = Number(key);
  memberProfileReturnFocus = document.activeElement;
  openLiveMemberHistory(Number(key));
}
function memberPlatformCards(payload) {
  const number = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—';
  const bindings = new Map((payload.bindings || []).map(binding => [binding.platform,binding]));
  $('#memberPlatformGrid').innerHTML = Object.entries(payload.platforms).map(([platform,meta]) => {
    const binding = bindings.get(platform), stats = binding?.snapshot || {};
    const history = Array.isArray(stats.rating_history) ? stats.rating_history : [];
    let homepage = '';
    try { const url = new URL(stats.profile_url); if (url.protocol === 'https:') homepage = url.href; } catch (_) {}
    const status = !binding ? '未绑定' : binding.status === 'pending' ? '同步中' : binding.status === 'failed' ? '同步未完成' : '已绑定';
    return `<article class="member-platform-card" data-platform="${escapeHtml(platform)}"><div class="member-platform-head"><span class="member-platform-mark">${escapeHtml(meta.short)}</span><div><h4>${escapeHtml(meta.name)}</h4><small>${escapeHtml(binding?.account || '暂未绑定账号')}</small></div><span class="member-platform-state">${status}</span></div>${binding ? `<details class="member-platform-details"><summary><span>数据概览</span><small>${number(stats.rating)} Rating · 通过 ${number(stats.solved)}</small><svg class="member-disclosure-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg></summary><div class="member-platform-metrics"><div><span>当前 Rating</span><strong>${number(stats.rating)}</strong></div><div><span>最高 Rating</span><strong>${number(stats.max_rating)}</strong></div><div><span>${escapeHtml(stats.solved_label || '通过题数')}</span><strong>${number(stats.solved)}</strong></div></div><div class="member-platform-extra">${stats.rank ? `<span>${escapeHtml(stats.rank)}</span>` : ''}${typeof stats.contests==='number'?`<span>${number(stats.contests)} 场 Rated 比赛</span>`:''}${(Array.isArray(stats.difficulty)?stats.difficulty:[]).map(item=>`<span>${escapeHtml(item.label)} ${number(item.count)}</span>`).join('')}</div>${history.length?`<details class="member-rating-history"><summary><span>近期比赛</span><small>${history.length} 场</small><svg class="member-disclosure-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg></summary><ol>${history.slice(-20).reverse().map(item=>`<li><span>${escapeHtml(item.name)}</span><strong>${number(item.rating)}</strong></li>`).join('')}</ol></details>`:''}${(Array.isArray(stats.notes)?stats.notes:[]).map(note=>`<p class="muted member-platform-note">${escapeHtml(note)}</p>`).join('')}<div class="member-platform-footer"><small>${binding.synced_at?'更新于 '+escapeHtml(new Date(binding.synced_at).toLocaleString('zh-CN')):'暂无同步数据'}</small>${homepage?`<a href="${escapeHtml(homepage)}" target="_blank" rel="noopener noreferrer">平台主页 ↗</a>`:''}</div></details>`:''}</article>`;
  }).join('');
}
function renderMemberRecent(items, append = false) {
  const list = $('#historyList');
  if (!append) list.innerHTML = '';
  for (const item of items) {
    const key = `history-${item.id}`;
    if (append && list.querySelector(`[data-member-submission="${item.id}"]`)) continue;
    const proof = item.parts.find(part=>part.kind==='proof');
    const logic = item.parts.find(part=>part.kind==='logic');
    const blog = item.parts.find(part=>part.kind==='blog');
    reviewData[key] = {name:item.member_name,initial:item.member_name.slice(0,1),time:new Date(item.submitted_at).toLocaleString('zh-CN'),logic:logic?.text || '', logicPart:logic || null,status:'approved',submissionId:item.id,memberId:item.member_id,problemTitle:item.problem_title || '',problemUrl:item.problem_url || '',upload:proof?.upload,fileName:'通过截图',blog:blog?.text || '',code:item.parts.find(part=>part.kind==='code')?.text || ''};
    const points = item.parts.reduce((sum,part)=>sum+(part.points || 0),0);
    list.insertAdjacentHTML('beforeend',`<article class="history-item" data-member-submission="${item.id}"><div class="history-item-icon approved">✓</div><div class="member-recent-copy"><strong>${escapeHtml(uiProblemTitle(item.problem_title || '题目记录'))}</strong><small>${escapeHtml(item.semester_name)} · 第 ${item.week} 周 · 提交于 ${escapeHtml(new Date(item.submitted_at).toLocaleString('zh-CN'))}</small></div><span>${points} 分</span><button class="history-view secondary-button" type="button" data-review="${key}">查看内容</button></article>`);
  }
  if (!list.children.length) list.innerHTML='<div class="queue-empty">暂无公开提交记录</div>';
}
async function openLiveMemberHistory(memberId, page = 1) {
  const requestVersion = ++historyRequestVersion;
  memberProfileBusy = true;
  if (page === 1) {
    $('#historyMember').textContent = '正在读取个人信息…';
    $('#historyIdentity').textContent=''; $('#historyMemberTitle').innerHTML=''; $('#historySquad').innerHTML=''; $('#historyMemberSummary').textContent=''; $('#historyAvatar').replaceChildren();
    $('#memberPlatformGrid').innerHTML='<p class="muted">正在加载平台数据…</p>';
    $('#historyList').innerHTML=''; $('#memberRecentTotal').textContent='';
    memberProfileNextPage=null; $('#memberRecentMore').hidden=true;
    historyModal.classList.add('open'); historyModal.setAttribute('aria-hidden','false');
    $('.member-profile-scroll',historyModal).scrollTop=0; $('#closeHistory').focus();
  }
  $('#memberRecentMore').disabled = true;
  try {
    const response = await clubApi.request(`/api/members/${memberId}/profile?page=${page}`);
    const payload = await response.json();
    if (requestVersion !== historyRequestVersion) return;
    if (!response.ok) throw new Error(payload.error || '无法查看该成员个人信息');
    if (page===1) {
      $('#historyMember').textContent = payload.member.name;
      $('#historyMemberTitle').innerHTML=MemberTitles.list(payload.member.titles||payload.member.title);
      $('#historySquad').innerHTML=MemberTitles.cohort(payload.member.cohort);
      $('#historyMemberSummary').textContent=`已绑定 ${payload.bindings.length} / 5 个平台 · ${payload.total} 条提交`;
      $('#historyIdentity').textContent = payload.member.role==='admin'?'团队管理员':'普通成员';
      setDetailAvatar($('#historyAvatar'),memberId,payload.member.name,payload.member.avatar);
      memberPlatformCards(payload);
    }
    renderMemberRecent(payload.submissions || [],page>1);
    $('#memberRecentTotal').textContent=`共 ${payload.total} 条`;
    memberProfileNextPage=payload.next_page;
    $('#memberRecentMore').hidden=!memberProfileNextPage;
  } catch(error) {
    if (requestVersion===historyRequestVersion) {
      if(page===1) { $('#historyMember').textContent='个人信息暂不可用'; $('#memberPlatformGrid').textContent=error.message; }
      showToast(error.message || '个人信息加载失败');
    }
  } finally {
    if (requestVersion===historyRequestVersion) { memberProfileBusy=false; $('#memberRecentMore').disabled=false; }
  }
}
function closeMemberHistory() {
  historyRequestVersion++; memberProfileBusy=false;
  historyModal.classList.remove('open'); historyModal.setAttribute('aria-hidden','true');
  if (memberProfileReturnFocus?.isConnected) memberProfileReturnFocus.focus();
}
$('#closeHistory').addEventListener('click',closeMemberHistory);
$('#memberRecentMore').addEventListener('click',()=>{ if(memberProfileNextPage&&!memberProfileBusy) openLiveMemberHistory(activeHistoryMemberId,memberProfileNextPage); });
$('#historyList').addEventListener('click',event=>{ const button=event.target.closest('[data-review]'); if(button){closeMemberHistory();openReview(button.dataset.review,true);} });
document.addEventListener('keydown',event=>{
  if(!historyModal.classList.contains('open'))return;
  if(event.key==='Escape'){event.preventDefault();closeMemberHistory();return;}
  if(event.key!=='Tab')return;
  const controls=[...historyModal.querySelectorAll('button:not(:disabled),a[href],summary')].filter(el=>el.getClientRects().length);
  const first=controls[0],last=controls.at(-1);
  if(event.shiftKey&&(document.activeElement===first||!historyModal.contains(document.activeElement))){event.preventDefault();last?.focus();}
  else if(!event.shiftKey&&(document.activeElement===last||!historyModal.contains(document.activeElement))){event.preventDefault();first?.focus();}
});

$('#memberSearch').addEventListener('input', (event) => {
  $('#memberSearchClear').hidden = !event.target.value;
  const query = event.target.value.trim().toLowerCase();
  $$('#membersGrid .member-card').forEach((card) => { card.style.display = !query || card.dataset.member.toLowerCase().includes(query) ? '' : 'none'; });
});

$('#memberSearchClear').addEventListener('click', () => {
  const input = $('#memberSearch');
  input.value = '';
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.focus();
});

// Resolve the current platform challenge without delaying the submission form.
let dailyChallengesRequest = null;
let dailyChallengesLoadedAt = 0;
async function loadDailyChallenges() {
  if (dailyChallengesRequest || Date.now() - dailyChallengesLoadedAt < 60000) return dailyChallengesRequest;
  const link = $('#dailyLeetcode');
  const status = $('#dailyChallengeStatus');
  if (!link || !status) return;
  link.removeAttribute('href');
  link.setAttribute('aria-disabled', 'true');
  status.textContent = '正在获取力扣今日题目…';
  dailyChallengesRequest = (async () => {
    try {
      const data = await communityRequest('/api/daily-challenges');
      if (!data.leetcode?.url || !/^https:\/\/leetcode\.cn\/problems\/[a-z0-9-]+\/$/.test(data.leetcode.url)) throw new Error(data.leetcode?.error || '力扣每日一题暂时无法获取，请稍后重试');
      link.href = data.leetcode.url;
      link.removeAttribute('aria-disabled');
      link.title = `${data.date} · 力扣每日一题`;
      status.textContent = '';
    } catch (error) {
      status.textContent = error.message || '力扣每日一题暂时无法获取，请稍后重试';
    } finally {
      dailyChallengesLoadedAt = Date.now();
      dailyChallengesRequest = null;
    }
  })();
  return dailyChallengesRequest;
}
$('#dailyLeetcode')?.addEventListener('click', event => {
  if (!event.currentTarget.hasAttribute('href')) {
    event.preventDefault();
    showToast($('#dailyChallengeStatus').textContent || '正在获取今日题目，请稍候');
    loadDailyChallenges();
  }
});

$('#editOwnSubmission').addEventListener('click', () => {
  if (activeReviewKey?.startsWith('mine-')) editOwnSubmission(activeSubmissionId);
});
$('#deleteOwnSubmission').addEventListener('click', async () => {
  if (!activeReviewKey?.startsWith('mine-')) return;
  const key = activeReviewKey;
  const record = ownRecords.get(Number(activeSubmissionId));
  if (!record?.can_delete) return;
  closeReview();
  try {
    const preview=await confirmSubmissionReversal(record.id,'delete',{alwaysConfirm:true});
    if(!preview){openReview(key);return;}
    await communityRequest(`/api/submissions/${record.id}`, {method:'DELETE', body:JSON.stringify({version:record.version,recovery_token:preview.token}), headers:{'Content-Type':'application/json'}});
    delete reviewData[key]; ownRecords.delete(record.id);
    await refreshAfterMutation({refreshAdmin:canManage});
    showToast('记录已删除，积分、签到、奖励及过题量已重新计算');
  } catch (error) { showToast(error.message); }
});

document.addEventListener('click', event => {
  const member = event.target.closest('[data-ranking-member]');
  if (member?.dataset.rankingMember && member.dataset.rankingMember !== 'undefined') openMemberHistory(member.dataset.rankingMember);
});
