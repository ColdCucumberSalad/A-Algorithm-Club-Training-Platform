function uiProblemTitle(title){if(/^https?:\/\//i.test(title||''))return '题目名称待解析';return adminTestMode&&title==='测试题目'?'未命名题目':title||'未命名题目';}
function uiMemberName(name){return adminTestMode&&/^管理员测试用户(?:（测试）)?$/.test(name||'')?'管理员':name||'成员';}
function problemPlatformMarkup(url){
  let host='';try{host=new URL(url).hostname.toLowerCase();}catch{}
  const matches=domain=>host===domain||host.endsWith('.'+domain);
  let label='其他',short='题',icon='';
  if(matches('leetcode.cn')||matches('leetcode.com')){label='力扣';icon='leetcode.ico';}
  else if(matches('nowcoder.com')){label='牛客';icon='nowcoder.ico';}
  else if(matches('codeforces.com')){label='Codeforces';short='CF';}
  else if(matches('luogu.com.cn')){label='洛谷';short='洛';}
  else if(matches('atcoder.jp')){label='AtCoder';short='At';}
  else if(matches('acwing.com')){label='AcWing';short='Ac';}
  else if(matches('qoj.ac')){label='QOJ';short='Q';}
  return `<span class="problem-platform-badge" title="${label}" aria-label="题目平台：${label}">${icon?`<img src="/static/platforms/${icon}" alt="${label}" width="26" height="26">`:`<span>${short}</span>`}</span>`;
}
function parseSubmissionCode(markdown){
  const match=(markdown||'').match(/^(`{3,})([a-z0-9_+-]*)\n([\s\S]*?)\n\1$/i);
  return match?{language:match[2]||'text',code:match[3]}:{language:'text',code:markdown||''};
}

let gallerySearchTimer;
function galleryQuery(){return encodeURIComponent($('#gallerySearch')?.value.trim()||'');}

let galleryProblem = null;
let galleryDetailPlatform = '';
let galleryRequest = 0;
let reportRequest = 0;
let resubmitting = null;
let editingSubmission = null;
let submissionEditReturnState=null;
function captureEditReturn(){
 return {key:activeReviewKey,history:reviewReturnsToHistory,open:$('#reviewModal').classList.contains('open'),tab:$('#reviewCodeTab').getAttribute('aria-selected')==='true'?'code':'blog',scroll:[...document.querySelectorAll('#reviewModal .review-modal,#reviewCode,#reviewBlog,#reviewModal .review-supporting-materials')].map(el=>[el,el.scrollLeft,el.scrollTop])};
}
function restoreEditReturn(state){
 if(!state?.open)return;
 openReview(state.key,state.history);selectReviewMaterial(state.tab);
 requestAnimationFrame(()=>{for(const[el,x,y]of state.scroll){el.scrollLeft=x;el.scrollTop=y;}$('#editOwnSubmission').focus({preventScroll:true});});
}
function cancelSubmissionEdit(){
 const state=submissionEditReturnState;submissionEditReturnState=null;
 closeModal();editingSubmission=null;resubmitting=null;resetSubmissionForm();restoreEditReturn(state);
}
function setDetailAvatar(holder,id,name,explicitSource=undefined){
 holder.textContent=(name||'').slice(0,1);holder.classList.add('synced-member-avatar');
  delete holder.dataset.avatarMember;
 if(!id)return;holder.dataset.avatarMember=String(id);
 const source=explicitSource===undefined?memberAvatarSource(id):explicitSource;if(!source)return;
 holder.dataset.avatarFallback=(name||'').slice(0,1);
 const image=document.createElement('img');image.src=source;image.alt='';image.decoding='async';
 image.onload=()=>{if(image.parentElement===holder)holder.replaceChildren(image);};
 image.onerror=()=>{if(image.parentElement===holder)holder.textContent=holder.dataset.avatarFallback;};holder.append(image);
}
const ownRecords = new Map();
let rejectionResolver = null;

function rejectionNote() {
  $('#rejectionReason').value = '';
  $('#reportDecisionModal').classList.add('open');
  $('#reportDecisionModal').setAttribute('aria-hidden', 'false');
  $('#rejectionReason').focus();
  return new Promise(resolve => { rejectionResolver = resolve; });
}

function finishRejection(value = null) {
  $('#reportDecisionModal').classList.remove('open');
  $('#reportDecisionModal').setAttribute('aria-hidden', 'true');
  rejectionResolver?.(value);
  rejectionResolver = null;
}

async function communityRequest(url, options) {
  const response = await clubApi.request(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || '加载失败，请重试');
    error.status = response.status;
    throw error;
  }
  return data;
}

async function confirmSubmissionReversal(id, action, {alwaysConfirm=false} = {}) {
  const preview=await communityRequest(`/api/submissions/${id}/reversal-preview?action=${action}`);
  const lines=[action==='delete'?'将删除整条提交及其材料，此操作无法恢复。':'将驳回该提交，并重新计算关联积分和签到。'];
  if(preview.reward_reversal)lines.push(`将撤回签到及连签奖励 ${preview.reward_reversal} Coins。`);
  for(const item of preview.items||[])lines.push(`该操作会导致“${item.name}”被回收（${item.quantity} 件），按原价返还 ${item.refund} Coins。`);
  const debt=preview.reward_reversal>0&&preview.balance_after<0;
  if(debt)lines.push(`回收后仍有 ${-preview.balance_after} Coins 待抵扣，将记为负余额。`);
  if(alwaysConfirm||preview.items?.length||debt){
    if(!await window.clubDialog.confirm({title:action==='delete'?'删除提交记录':'确认驳回与物品回收',
      text:lines.join('\n\n'),confirmText:action==='delete'?'确认删除':'确认驳回'}))return null;
  }
  return preview;
}

const showcaseRecords=new Map();
function openShowcaseDetails(id){
  const item=showcaseRecords.get(Number(id));if(!item)return;
  const part=kind=>item.parts.find(p=>p.kind===kind);
  const key=(item.own?'mine-':'showcase-')+item.id;
  if(item.own)ownRecords.set(Number(item.id),item);
  reviewData[key]={name:uiMemberName(item.member_name),initial:uiMemberName(item.member_name).slice(0,1),time:new Date(item.submitted_at).toLocaleString('zh-CN'),logic:part('logic')?.text||'未提交题解思路。',status:'approved',submissionId:item.id,memberId:item.member_id,problemTitle:item.problem_title||$('#problemHeading').textContent,problemUrl:item.problem_url||$('#problemOriginal').href,upload:part('proof')?.upload,fileName:'通过截图',blog:part('blog')?.text||'',code:part('code')?.text||''};
  openReview(key);
}
function submissionCard(item, moderation = false) {
  const proof = item.parts.find(p => p.kind === 'proof');
  const logic = item.parts.find(p => p.kind === 'logic');
  const blog = item.parts.find(p => p.kind === 'blog');
  const code = item.parts.find(p => p.kind === 'code');
  if(!moderation){
    const language=code?.text?.trim()?parseSubmissionCode(code.text).language:null;
    const languageLabel=language?([...($('#submissionCodeLanguage')?.options||[])].find(option=>option.value===language)?.textContent.trim()||language):'';
    const languageTag=languageLabel?`<span class="submission-language-tag" aria-label="代码语言：${escapeHtml(languageLabel)}" title="代码语言：${escapeHtml(languageLabel)}">${escapeHtml(languageLabel)}</span>`:'';
    showcaseRecords.set(Number(item.id),item);
    return `<article class="solution-card solution-summary panel" data-submission="${item.id}"><div class="member-line">${memberAvatar(item.member_id,uiMemberName(item.member_name))}<div class="submission-member-info"><strong>${escapeHtml(uiMemberName(item.member_name))}</strong><small>提交于 ${new Date(item.submitted_at).toLocaleString('zh-CN')}</small></div>${languageTag}</div><section class="solution-reasoning"><h3>题解思路</h3><p>${escapeHtml(logic?.text||'暂未填写题解思路。')}</p></section><button type="button" class="secondary-button solution-detail-button" data-solution-detail="${item.id}">查看详情</button><div class="solution-actions"><button class="secondary-button ${item.liked?'is-liked':''}" data-like="${item.id}" data-liked="${item.liked}" aria-pressed="${Boolean(item.liked)}" ${item.own?'disabled':''}>赞 ${item.likes}</button>${item.can_tip?`<button class="secondary-button" data-tip="${item.id}">打赏</button>`:''}<button class="text-button" data-report="${item.id}" ${item.own||item.reported?'disabled':''}>${item.reported?'已举报':'举报'}</button>${item.can_reject?`<button class="text-button" data-direct-reject="${item.id}" data-version="${item.version}">驳回</button>`:''}</div></article>`;
  }
  return `<article class="solution-card panel" data-submission="${item.id}">
    <div class="member-line">${memberAvatar(item.member_id,uiMemberName(item.member_name))}<div><strong>${escapeHtml(uiMemberName(item.member_name))}</strong><small>${escapeHtml(item.semester_name)} · 第${item.week}周<br>归属日期：${escapeHtml(item.record_date || '')}<br>上传：${new Date(item.submitted_at).toLocaleString('zh-CN')}</small></div></div>
    ${moderation ? `<h3>${escapeHtml(item.problem_title)}</h3><small>${escapeHtml(item.team_name || '')}</small><p class="muted">${item.reports} 人举报 · 版本 ${item.version}</p>` : ''}
    <div class="solution-excerpt">
    ${code?.text ? `<div class="shared-content blog-content"><strong>代码 · ${escapeHtml(parseSubmissionCode(code.text).language)}</strong><div class="blog-rendered" data-markdown="${escapeHtml(code.text)}"></div></div>` : ''}
    ${blog?.text ? `<div class="shared-content blog-content"><strong>Blog</strong><div class="blog-rendered" data-markdown="${escapeHtml(blog.text)}"></div></div>` : ''}
    <div class="solution-attachments">
    ${proof?.upload ? `<button class="solution-proof" data-zoom="${escapeHtml(proof.upload)}" aria-label="放大通过截图"><img loading="lazy" src="${escapeHtml(proof.upload)}" alt="${escapeHtml(uiMemberName(item.member_name))}的通过截图"><span>通过截图 · 点击放大</span></button>` : ''}
    ${logic?.text ? `<div class="shared-content"><strong>题解思路</strong><p class="solution-text">${escapeHtml(logic.text)}</p></div>` : ''}
    </div>
    </div>
    <div class="solution-actions">${moderation ? item.can_resolve ? `<button class="secondary-button" data-resolve="dismiss" data-id="${item.id}" data-version="${item.version}">驳回举报</button><button class="secondary-button" data-resolve="reject" data-id="${item.id}" data-version="${item.version}">整条退回</button>` : '<span class="muted">请其他管理员处理自己的记录</span>' : `<button class="secondary-button ${item.liked ? 'is-liked' : ''}" data-like="${item.id}" data-liked="${item.liked}" aria-pressed="${item.liked}" ${item.own ? 'disabled' : ''}>赞 ${item.likes}</button>${item.can_tip ? `<button class="secondary-button" data-tip="${item.id}">打赏</button>` : ""}<button class="text-button" data-report="${item.id}" ${item.own || item.reported ? 'disabled' : ''}>${item.reported ? '已举报' : '举报'}</button>${item.can_reject ? `<button class="text-button" data-direct-reject="${item.id}" data-version="${item.version}">驳回</button>` : ''}`}</div>
  </article>`;
}

async function loadShowcase(page = 1) {
  galleryProblem = null;
  $('#problemAllPlatforms').hidden = true;
  $('#gallerySearch').closest('.gallery-search').hidden = false;
  $('#galleryPlatformFilter').hidden = false;
  const version = ++galleryRequest;
  const host = $('#showcaseGrid');
  const more = $('#galleryMore');
  $('#problemBack').hidden = true;
  $('#problemHeading').textContent = '全部题目';
  $('#problemOriginal').hidden = true;
  if (page === 1) host.innerHTML = '<div class="queue-empty">正在加载题目…</div>';
  more.hidden = true;
  more.textContent = '加载更多';
  host.className = 'problem-list';
  try {
    const data = await communityRequest(`/api/showcase?all=1&cursor=${encodeURIComponent(page === 1 ? '' : page)}&q=${galleryQuery()}&platform=${encodeURIComponent($('#galleryPlatform').value)}`);
    if (version !== galleryRequest) return;
    $('#problemHeading').textContent = '全部题目';
    if(page===1)host.replaceChildren();
    const platformSelect = $('#galleryPlatform');
    const selectedPlatform = platformSelect.value;
    platformSelect.innerHTML = '<option value="">全部平台</option>' + data.platforms.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join('');
    if (selectedPlatform && !data.platforms.some(p => p.id === selectedPlatform)) {
      const option = new Option('当前平台（暂无题解）', selectedPlatform);
      platformSelect.add(option);
    }
    platformSelect.value = selectedPlatform;
    $('#problemHeading').textContent = selectedPlatform ? platformSelect.selectedOptions[0].textContent + '题目' : '全部题目';
    for(const p of data.problems){
      const html = `<button class="problem-row panel" data-problem="${p.id}">${problemPlatformMarkup(p.url)}<span class="problem-row-content"><strong>${escapeHtml(uiProblemTitle(p.title))}</strong><small title="${escapeHtml(p.members.map(uiMemberName).join('、'))}">${p.count} 条题解 · ${p.member_count} 人参与 · ${p.members.slice(0,3).map(uiMemberName).map(escapeHtml).join('、')}${p.members.length>3?' 等':''}</small></span><span class="problem-arrow" aria-label="查看题目详情">›</span></button>`;
      host.insertAdjacentHTML('beforeend',html);
    }
    if(page===1&&!data.problems.length)host.innerHTML='<div class="queue-empty">暂无匹配的题目。</div>';
    more.hidden = !data.next;
    more.onclick = () => loadShowcase(data.next);
  } catch (error) { if (version === galleryRequest) { host.innerHTML = `<div class="queue-empty">${escapeHtml(error.message)}</div>`; more.hidden = false; more.textContent = '刷新列表'; more.onclick = () => loadShowcase(); } }
}

async function openProblem(id, page = 1, platform = galleryDetailPlatform) {
  galleryDetailPlatform = platform;
  $('#problemAllPlatforms').hidden = !platform;
  galleryProblem = id;
  $('#galleryMore').textContent = '加载更多';
  $('#gallerySearch').closest('.gallery-search').hidden = true;
  $('#galleryPlatformFilter').hidden = true;
  const version = ++galleryRequest;
  const host = $('#showcaseGrid');
  const more = $('#galleryMore');
  $('#problemBack').hidden = false;
  $('#problemOriginal').hidden = true;
  $('#problemOriginal').removeAttribute('href');
  host.className = 'submission-days';
  if (page === 1) host.innerHTML = '<div class="queue-empty">正在加载全部历史题解…</div>';
  more.hidden = true;
  try {
    const data = await communityRequest(`/api/problems/${id}/submissions?cursor=${encodeURIComponent(page === 1 ? '' : page)}&platform=${encodeURIComponent(platform)}`);
    if (version !== galleryRequest) return;
    $('#problemHeading').textContent = uiProblemTitle(data.problem.title);
    const link = $('#problemOriginal');
    link.hidden = false; link.href = data.problem.url;
    if (page === 1) host.replaceChildren();
    host.insertAdjacentHTML('beforeend', data.submissions.map(item => submissionCard(item)).join(''));

    renderSubmissionBlogs(host);

    more.hidden = !data.next;
    more.onclick = () => openProblem(id, data.next);
  } catch (error) {
    if (version !== galleryRequest) return;
    if (error.status === 404) { await loadShowcase(); return; }
    host.innerHTML = `<div class="queue-empty">${escapeHtml(error.message)}</div>`;
    more.hidden = false; more.textContent = '重新加载题解'; more.onclick = () => openProblem(id, 1, platform);
  }
}

async function loadAdminQueue({append = false, page = 1} = {}) {
  if (!canManage || currentView !== 'admin') return;
  const version = ++reportRequest;
  const host = $('#reviewList');
  try {
    const data = await communityRequest(`/api/admin/reports?page=${page}`);
    if (version !== reportRequest || currentView !== 'admin') return;
    const html = data.submissions.map(item => submissionCard(item, true)).join('');
    if (!append) host.innerHTML = html || '<div class="queue-empty">当前没有待处理举报</div>';
    else host.insertAdjacentHTML('beforeend', html);
    renderSubmissionBlogs(host);
    const more = $('#reportsMore'); more.hidden = !data.next;
    more.onclick = () => loadAdminQueue({append: true, page: data.next});
  } catch (error) { if (version === reportRequest) host.innerHTML = `<div class="queue-empty">${escapeHtml(error.message)}</div>`; }
}

function stopAdminQueuePolling() { reportRequest++; }
function startAdminQueuePolling() { loadWorkbench(); }

async function beginResubmit(id, {edit = false} = {}) {
  const record = ownRecords.get(Number(id));
  if (!record) return;
  if (!(edit ? record.can_edit : record.can_resubmit)) {
    showToast(edit ? '该记录已截止或学期已归档' : '该记录当前不能重新提交');
    return false;
  }
  if (!await openModal(false, record)) return false;
  resubmitting = edit ? null : record.id;
  $('#submissionForm').dataset.weekId = record.week_id;
  $('#submissionForm').dataset.recordDate = record.record_date;
  $('.form-note span').textContent = `记录日期：${record.record_date}`;
  $('#problemUrl').value = record.problem_url;
  $('#logicText').value = record.parts.find(p => p.kind === 'logic')?.text || '';
  const blogPart = record.parts.find(p => p.kind === 'blog');
  if (typeof setBlogEditorContent === 'function' && blogPart?.text) {
    setBlogEditorContent(blogPart.text);
  }
  $('#modalTitle').textContent = uiProblemTitle(record.problem_title || '修改并重新提交');
  setSubmissionCodeDraft(record.parts.find(p=>p.kind==='code')?.text||'');
  renderSubmissionDraftBlog();
  return true;
}

document.addEventListener('DOMContentLoaded', () => {
  $('#problemAllPlatforms').addEventListener('click', () => openProblem(galleryProblem, 1, ''));
  $('#galleryPlatform').addEventListener('change', () => loadShowcase());
  $('#gallerySearch').addEventListener('input',()=>{clearTimeout(gallerySearchTimer);gallerySearchTimer=setTimeout(()=>galleryProblem?openProblem(galleryProblem):loadShowcase(),250);});
  $('#problemBack').addEventListener('click', () => loadShowcase());
  $('#refreshReports').addEventListener('click', () => loadWorkbench());
  $('#closeReportDecision').addEventListener('click', () => finishRejection());
  $('#reportDecisionForm').addEventListener('submit', event => {
    event.preventDefault();
    const note = $('#rejectionReason').value.trim();
    if (note) finishRejection(note);
  });
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && rejectionResolver) { event.stopImmediatePropagation(); finishRejection(); }
}, true);

document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button) return;
  if(button.dataset.solutionDetail){openShowcaseDetails(button.dataset.solutionDetail);return;}
  if(button.dataset.toggleSolution){const card=button.closest('.solution-card');const expanded=card.classList.toggle('is-expanded');button.setAttribute('aria-expanded',String(expanded));button.textContent=expanded?'收起题解':'展开题解';return;}
  if (button.dataset.problem) { openProblem(button.dataset.problem, 1, $('#galleryPlatform').value); return; }
  if (button.dataset.resubmit) { beginResubmit(button.dataset.resubmit); return; }
  if (button.dataset.zoom) {
    $('#lightboxImage').src = button.dataset.zoom;
    $('#imageLightbox').classList.add('open');
    $('#imageLightbox').setAttribute('aria-hidden', 'false'); return;
  }
  if(button.dataset.tip){openTipDialog(button.dataset.tip);return;}
  if (!button.dataset.like && !button.dataset.report && !button.dataset.resolve && !button.dataset.directReject) return;
  let note = '';
  if (button.dataset.resolve === 'reject' || button.dataset.directReject) {
    note = await rejectionNote();
    if (!note) return;
  }
  button.disabled = true;
  try {
    if (button.dataset.like) {
      const data = await communityRequest(`/api/submissions/${button.dataset.like}/like`, {method: button.dataset.liked === 'true' ? 'DELETE' : 'PUT'});
      button.dataset.liked = String(data.liked); button.textContent = `赞 ${data.likes}`;
      button.classList.toggle('is-liked', data.liked); button.setAttribute('aria-pressed', String(data.liked));
    } else if (button.dataset.report) {
      await communityRequest(`/api/submissions/${button.dataset.report}/report`, {method: 'POST'});
      button.textContent = '已举报'; button.dataset.done = 'true'; showToast('举报已交由管理员处理');
    } else if (button.dataset.directReject) {
      const preview=await confirmSubmissionReversal(button.dataset.directReject,'reject');if(!preview)return;
      await communityRequest(`/api/submissions/${button.dataset.directReject}/reject`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note,version:Number(button.dataset.version),recovery_token:preview.token})});
      showToast('已驳回，积分、签到奖励与过题量已重新计算');
      if (galleryProblem) await openProblem(galleryProblem);
      await refreshAfterMutation();
    } else {
      const preview=button.dataset.resolve==='reject'?await confirmSubmissionReversal(button.dataset.id,'reject'):null;
      if(button.dataset.resolve==='reject'&&!preview)return;
      await communityRequest(`/api/admin/reports/${button.dataset.id}/resolve`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:button.dataset.resolve, note, version:Number(button.dataset.version),recovery_token:preview?.token})});
      showToast(button.dataset.resolve === 'reject' ? '已退回，积分、签到奖励与过题量已重新计算' : '已驳回举报');
      await loadWorkbench(); await refreshAfterMutation();
    }
  } catch (error) { showToast(error.message); }
  finally { if (button.dataset.done !== 'true') button.disabled = false; }
});

// Tokenize math before Markdown can insert <br> or interpret TeX underscores.
// Code fences and code spans remain Marked tokens and are never processed as math.
function parseBlogMarkdown(source) {
  const escape = text => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const display = /^(\${2,3})(?!\$)([\s\S]+?)\1(?!\$)/;
  const bracket = /^\\\[([\s\S]+?)\\\]/;
  const token = (src, block) => {
    const match = display.exec(src) || bracket.exec(src);
    if (match) return {type:block?'blogMathBlock':'blogMathInline',raw:match[0],text:match[2] ?? match[1],display:true};
    if (block) return;
    const inline = /^\$(?!\$)((?:\\[^\n]|[^$\\\n])+?)\$(?!\$)/.exec(src) || /^\\\(([^\n]+?)\\\)/.exec(src);
    if (inline) return {type:'blogMathInline',raw:inline[0],text:inline[1],display:false};
  };
  const renderer = item => {
    const delimiter = item.display ? '$$' : '$';
    const tag = item.type === 'blogMathBlock' ? 'div' : 'span';
    return `<${tag}>${escape(delimiter + item.text + delimiter)}</${tag}>`;
  };
  const parser = new marked.Marked({breaks:true,gfm:true}, {extensions:[
    {name:'blogMathBlock',level:'block',start:src=>src.search(/^(?:\${2,3}(?!\$)|\\\[)/m),tokenizer:src=>token(src,true),renderer},
    {name:'blogMathInline',level:'inline',start:src=>src.search(/\$|\\[([]/),tokenizer:src=>token(src,false),renderer}
  ]});
  return parser.parse(source);
}

// Viewing uses the editor's stored Markdown; only the rendered output is filtered.
function renderSubmissionBlog(element, markdown) {
  const source = String(markdown || '');
  if (typeof marked === 'undefined') { element.textContent = source; return; }
  try {
    const template = document.createElement('template');
    template.innerHTML = parseBlogMarkdown(source);
    const tags = new Set(['P','BR','HR','H1','H2','H3','H4','H5','H6','STRONG','EM','DEL','S','B','I','U','BLOCKQUOTE','PRE','CODE','UL','OL','LI','TABLE','THEAD','TBODY','TR','TH','TD','A','IMG','DETAILS','SUMMARY','DIV','SPAN','SUP','SUB']);
    const blocked = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','TEMPLATE','FORM','INPUT','BUTTON','LINK','META','BASE']);
    template.content.querySelectorAll('*').forEach(node => {
      if (blocked.has(node.tagName)) { node.remove(); return; }
      if (!tags.has(node.tagName)) { node.replaceWith(...node.childNodes); return; }
      const href = node.getAttribute('href');
      const src = node.getAttribute('src');
      const alt = node.getAttribute('alt');
      const title = node.getAttribute('title');
      const language=node.tagName==='CODE'?(node.className.match(/(?:^|\s)language-([a-z0-9_+-]+)(?:\s|$)/i)?.[1]||'text'):null;
      for (const attr of [...node.attributes]) node.removeAttribute(attr.name);
      if (title) node.setAttribute('title', title);
      if(language)node.className='language-'+language;
      const safeUrl = (value, image = false) => {
        if (!value || /[\u0000-\u001f\u007f]/.test(value)) return null;
        try {
          const url = new URL(value, location.href);
          return (image ? ['http:', 'https:'] : ['http:', 'https:', 'mailto:']).includes(url.protocol) ? url.href : null;
        } catch { return null; }
      };
      if (node.tagName === 'A' && safeUrl(href)) {
        node.href = safeUrl(href); node.target = '_blank'; node.rel = 'noopener noreferrer';
      }
      if (node.tagName === 'IMG') {
        if (!safeUrl(src, true)) { node.remove(); return; }
        node.src = safeUrl(src, true); node.alt = alt || ''; node.loading = 'lazy';
      }
    });
    element.replaceChildren(template.content);
    element.querySelectorAll('pre code').forEach(code=>{
      window.CodeColors?.colorElement(code,code.className.replace('language-','')||'text');
      const pre=code.parentElement,wrap=document.createElement('div');wrap.className='code-block-shell';pre.before(wrap);wrap.append(pre);
      const button=document.createElement('button');button.type='button';button.className='code-copy-button';
      const copyIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/></svg>';
      const status=(label,icon=copyIcon)=>{button.innerHTML=icon;button.setAttribute('aria-label',label);button.title=label;};status('复制代码');
      button.onclick=async()=>{try{const text=code.textContent;if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(text);else{const input=document.createElement('textarea');input.value=text;input.style.position='fixed';input.style.opacity='0';wrap.append(input);input.select();const copied=document.execCommand('copy');input.remove();if(!copied)throw Error('copy');}status('已复制','<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>');setTimeout(()=>status('复制代码'),1500);}catch{status('复制失败，请重试');}};
      wrap.append(button);
    });
    if (typeof renderMathInElement !== 'undefined') {
      renderMathInElement(element, {delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},{left:'\\[',right:'\\]',display:true},{left:'\\(',right:'\\)',display:false}],throwOnError:false,trust:false});
    }
  } catch { element.textContent = source; }
}

function renderSubmissionBlogs(root) {
  root.querySelectorAll('.blog-rendered[data-markdown]').forEach(element => renderSubmissionBlog(element, element.dataset.markdown));
  requestAnimationFrame(()=>root.querySelectorAll('.solution-card').forEach(card=>{const body=card.querySelector('.solution-excerpt'),button=card.querySelector('.solution-expand');if(body&&button&&!card.classList.contains('is-expanded'))button.hidden=body.scrollHeight<=body.clientHeight+2;}));
}

async function editOwnSubmission(id) {
  const record = ownRecords.get(Number(id));
  if (!record?.can_edit) { showToast('该记录已截止或学期已归档'); return; }
  const returnState=captureEditReturn();
  closeReview();
  if(!await beginResubmit(id, {edit:true})){restoreEditReturn(returnState);return;}
  submissionEditReturnState=returnState;
  editingSubmission = Number(id);
  resubmitting = null;
  $('.form-note span:last-child').textContent = '编辑原提交 · 不消耗补签券';
  $('#proofImage').required = false;
  $('.upload-box strong').textContent = '保留原截图，点击可更换';
  $('#proofHint').textContent = '未选择新图片时保留原截图';
  $('#modalTitle').textContent = uiProblemTitle(record.problem_title || '编辑提交记录');
  $('#cancelSubmissionEdit').hidden=false;
  $('#submissionForm button[type=submit]').textContent='修改并提交';
}

function openTipDialog(id){
 const dialog=document.createElement('dialog');dialog.className='contest-reward-summary';
 dialog.innerHTML='<h2>打赏这条提交</h2><form><label>RBC Coins 数量<input name="amount" type="number" min="1" max="2147483647" step="1" required autofocus style="display:block;width:100%;padding:12px;margin:12px 0"></label><p>打赏将从你的余额扣除，并全额转给提交者。</p><p role="status"></p><button type="button" class="secondary-button">取消</button> <button type="submit" class="primary-button">确认打赏</button></form>';
 const token=clubApi.requestId();let pending=false;
 dialog.querySelector('button[type=button]').onclick=()=>dialog.close();
 dialog.addEventListener('cancel',event=>{if(pending)event.preventDefault();});dialog.addEventListener('close',()=>dialog.remove());
 dialog.querySelector('form').onsubmit=async event=>{
  event.preventDefault();if(pending)return;const form=event.target,amount=Number(form.elements.amount.value);
  if(!Number.isSafeInteger(amount)||amount<=0)return;pending=true;form.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{const result=await communityRequest(`/api/submissions/${id}/tip`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount,request_id:token})});dialog.close();await window.CurrencyModule?.init();showToast(`打赏成功：${result.amount} RBC Coins`);}catch(error){form.querySelector('[role=status]').textContent=error.message;}finally{pending=false;form.querySelectorAll('button').forEach(b=>b.disabled=false);}
 };
 document.body.append(dialog);dialog.showModal();
}
