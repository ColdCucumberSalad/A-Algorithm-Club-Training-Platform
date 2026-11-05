/* Personal page: enters from and returns to the right; keeps the main view intact. */
(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => typeof value === 'number' ? value.toLocaleString('zh-CN') : '—';
  let page, backdrop, data, opened = false, closing = false, poll, objectURL, allowed = false, generation = 0;
  let solvedBaselineSignature = null;
  const adding = new Set();
  const entry = document.getElementById('openProfile');
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  let scrollState;
  function motion(element,frames,duration){
    if(reduced()||document.documentElement.dataset.siteMotion==='off'||!element.animate)return Promise.resolve();
    const animation=element.animate(frames,{duration,easing:'cubic-bezier(.2,.75,.25,1)'});
    return animation.finished.catch(()=>{});
  }

  async function request(url, options = {}) {
    const response = await window.clubApi.request(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || '请求失败，请稍后重试');
    return payload;
  }
  function updateHeader(info) {
    if (!entry) return;
    entry.querySelector('strong').textContent = info.name;
    const avatar = entry.querySelector('.profile-avatar');
    avatar.textContent = (info.name || '').slice(0, 1);
    const source = info.avatar_small || info.avatar;
    if (source) {
      const image = document.createElement('img'); image.src = source; image.alt = ''; image.decoding='async';
      image.onload=()=>{if(image.parentElement===avatar)avatar.replaceChildren(image);};
      image.onerror=()=>{if(image.parentElement===avatar)avatar.textContent=(info.name||'').slice(0,1);};
      avatar.append(image);
    } else avatar.textContent = (info.name || '').slice(0, 1);
    window.MemberTitles?.frameElement?.(avatar,info.avatar_frame);
  }
  function updateFrame(frame) {
    if (data) data.avatar_frame = frame;
    window.MemberTitles?.frameElement?.(entry?.querySelector('.profile-avatar'),frame);
  }
  function message(text, bad = false) {
    const target = page.querySelector('#profileMessage');
    target.textContent = text; target.classList.toggle('is-error', bad);
  }
  function avatarPreview(url, name) {
    const target = page.querySelector('#personalAvatar'); target.textContent = (name || '').slice(0, 1);
    if (url) {
      const image = document.createElement('img'); image.src = url; image.alt = '头像预览'; image.decoding='async';
      image.onload=()=>{if(image.parentElement===target)target.replaceChildren(image);};
      image.onerror=()=>{if(image.parentElement===target)target.textContent=(name||'').slice(0,1);};
      target.append(image);
    }
    else target.textContent = (name || '').slice(0, 1);
  }
  function renderIdentity() {
    window.MemberTitles?.frameElement?.(page.querySelector('#personalAvatar'),data.avatar_frame);
    page.querySelector('#personalGrade').textContent = data.cohort?.squad_label || (data.read_only ? '系统管理员' : '未分队');
    page.querySelector('#personalMemberTitle').innerHTML=window.MemberTitles?.list(data.titles||data.title,data.badge)||'';
    let wardrobe=page.querySelector('#titleWardrobe');if(!wardrobe){wardrobe=document.createElement('section');wardrobe.id='titleWardrobe';wardrobe.className='personal-basics title-wardrobe';page.querySelector('.personal-password').before(wardrobe);}
    const awarded=data.awarded_titles||[];wardrobe.hidden=data.read_only||!awarded.length;
    const selected=data.titles?.length===1?data.titles[0].text:null;
    wardrobe.innerHTML='<h2>佩戴称号</h2><div class="title-wardrobe-options"><button type="button" class="secondary-button" data-wear-none aria-pressed="'+(!data.titles?.length)+'">不佩戴</button>'+awarded.map((title,i)=>'<button type="button" class="title-wear-choice" data-wear-index="'+i+'" aria-pressed="'+(selected===title.text)+'">'+MemberTitles.markup(title)+'</button>').join('')+'</div>';
    wardrobe.onclick=async event=>{const button=event.target.closest('button');if(!button)return;const title=button.hasAttribute('data-wear-none')?null:awarded[Number(button.dataset.wearIndex)]?.text;if(title===undefined)return;button.disabled=true;try{const result=await request('/api/profile/titles/wear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title})});window.SpecialThemes?.invalidate?.();data.titles=result.titles;renderIdentity();if(typeof refreshCosmeticRankings==='function')refreshCosmeticRankings();message('称号佩戴已更新');}catch(error){message(error.message,true);}finally{button.disabled=false;}};
    let badgeWardrobe=page.querySelector('#badgeWardrobe');
    if(!badgeWardrobe){badgeWardrobe=document.createElement('section');badgeWardrobe.id='badgeWardrobe';badgeWardrobe.className='personal-basics title-wardrobe';wardrobe.after(badgeWardrobe);}
    const badges=data.cosmetics?.badges||[];badgeWardrobe.hidden=data.read_only||!badges.length;
    badgeWardrobe.innerHTML='<h2>佩戴徽章</h2><div class="title-wardrobe-options"><button type="button" class="secondary-button" data-badge-key="" aria-pressed="'+(!data.badge)+'">不佩戴</button>'+badges.map(b=>'<button type="button" class="title-wear-choice" data-badge-key="'+escape(b.key)+'" aria-pressed="'+(data.badge?.key===b.key)+'">'+MemberTitles.badgeMarkup(b)+' '+escape(b.name)+'</button>').join('')+'</div>';
    badgeWardrobe.querySelectorAll('[data-badge-key]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const result=await SpecialThemes.select('badge',button.dataset.badgeKey);data.badge=result.badge;data.cosmetics=result;renderIdentity();if(typeof refreshCosmeticRankings==='function')refreshCosmeticRankings();message('徽章佩戴已更新');}catch(error){message(error.message,true);}finally{button.disabled=false;}});
    let frames=page.querySelector('#frameWardrobe');if(!frames){frames=document.createElement('section');frames.id='frameWardrobe';frames.className='personal-basics title-wardrobe';badgeWardrobe.after(frames);}
    const ownedFrames=data.cosmetics?.frames||[];frames.hidden=data.read_only||!ownedFrames.length;
    frames.innerHTML='<h2>佩戴头像框</h2><div class="title-wardrobe-options"><button type="button" class="secondary-button" data-frame-key="" aria-pressed="'+(!data.avatar_frame)+'">不佩戴</button>'+ownedFrames.map(frame=>'<button type="button" class="title-wear-choice" data-frame-key="'+escape(frame.key)+'" aria-pressed="'+(data.avatar_frame?.key===frame.key)+'">'+MemberTitles.frameAvatar('<span class="cosmetic-demo-avatar">'+escape((data.name||'').slice(0,1))+'</span>',frame)+' '+escape(frame.name)+'</button>').join('')+'</div>';
    frames.querySelectorAll('[data-frame-key]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const result=await SpecialThemes.select('frame',button.dataset.frameKey);data.avatar_frame=result.avatar_frame;data.cosmetics=result;renderIdentity();updateHeader(data);if(typeof refreshCosmeticRankings==='function')refreshCosmeticRankings();message('头像框佩戴已更新');}catch(error){message(error.message,true);}finally{button.disabled=false;}});
  }
  function buildPage() {
    page = document.createElement('section'); page.id = 'personalPage'; page.className = 'personal-page';
    page.hidden = true; page.setAttribute('role', 'dialog'); page.setAttribute('aria-modal', 'true');
    page.setAttribute('aria-labelledby', 'personalTitle');
    page.innerHTML = `
      <div class="personal-top"><button id="profileBack" class="personal-back" aria-label="返回主页面" type="button"><svg class="ui-chevron" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m9 5 7 7-7 7"/></svg></button><span>个人空间</span><small>PROFILE & ACCOUNTS</small></div>
      <main class="personal-content">
        <header class="personal-heading"><p class="kicker">YOUR ALGORITHM JOURNEY</p><h1 id="personalTitle">个人信息</h1></header>
        <p id="profileMessage" class="profile-message" role="status" aria-live="polite"></p>
        <div id="profileLoading" class="personal-loading">正在读取个人资料…</div>
        <div id="profileBody" hidden>
          <section class="personal-basics" aria-labelledby="basicsTitle">
            <div class="personal-section-copy"><span class="personal-step">01 / ABOUT YOU</span><h2 id="basicsTitle">基本资料</h2><p id="personalAccount"></p></div>
            <form id="personalForm" class="personal-form">
              <div class="personal-avatar-field"><span id="personalAvatar" class="personal-avatar"></span><label class="avatar-picker">更换头像<input id="personalAvatarFile" name="avatar" type="file" accept="image/png,image/jpeg,image/webp"></label><small>PNG / JPEG / WebP · 最大 3 MB</small></div>
              <div class="personal-name-field"><div class="personal-identity-row"><label class="personal-inline-field" for="personalName"><span>昵称</span><input id="personalName" name="name" required maxlength="40" autocomplete="nickname"></label><div class="personal-inline-field"><span id="personalGradeLabel">分队</span><output id="personalGrade" aria-labelledby="personalGradeLabel"></output></div></div><div id="personalMemberTitle" class="member-title-row"></div><button type="submit" class="primary-button">保存个人资料</button></div>
            </form>
          </section>
          <section class="personal-basics personal-password" aria-labelledby="passwordTitle"><div><h2 id="passwordTitle">修改密码</h2><p class="muted">验证当前密码后设置新密码。</p></div><form id="personalPasswordForm" class="personal-name-field"><label>当前密码<input type="password" name="old_password" autocomplete="current-password" required></label><label>新密码<input type="password" name="new_password" autocomplete="new-password" minlength="8" maxlength="128" required></label><label>确认新密码<input type="password" name="confirm_password" autocomplete="new-password" minlength="8" maxlength="128" required></label><button type="submit" class="primary-button">修改密码</button><p id="passwordMessage" role="status"></p></form></section>
          <section class="personal-platform-section" aria-labelledby="platformTitle"><div class="personal-platform-heading"><div><span class="personal-step">02 / CONNECT YOUR PLATFORMS</span><h2 id="platformTitle">算法平台</h2></div><div class="platform-heading-actions"><span id="bindingCount" class="binding-count"></span><button id="claimPlatformRewards" class="primary-button" type="button" hidden>领取过题奖励</button><button id="syncAllPlatforms" class="secondary-button" type="button">同步全部账号</button></div></div>
            <div id="platformGrid" class="platform-grid"></div>
          </section>
          <section class="personal-basics account-close-section"><div><h2>注销全局账号</h2><p class="muted">注销会停用所有团队身份，请先核对影响。</p></div><button type="button" class="secondary-button" data-close-own-account>注销账号</button></section>
        </div>
      </main>`;
    backdrop = document.createElement('div'); backdrop.className = 'personal-backdrop'; backdrop.hidden = true;
    backdrop.setAttribute('aria-hidden', 'true'); backdrop.onclick = back;
    document.body.append(backdrop, page);
    page.querySelector('#claimPlatformRewards').onclick=async event=>{
      event.target.disabled=true;
      try {
        const result=await request('/api/profile/platform-rewards/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keys:data.rewards.keys})});
        data=await request('/api/profile');renderBindings();
        await window.CurrencyModule?.init();message(`已领取 ${result.total} Coins`);
        window.dispatchEvent(new Event('platform-rewards-updated'));
      } catch(error){message(error.message,true);}
      finally{event.target.disabled=false;}
    };
    page.querySelector('#syncAllPlatforms').onclick = async event => {
      const ids = data.bindings.filter(b => b.status !== 'pending').map(b => b.id);
      if (!ids.length) return;
      event.target.disabled = true;
      try {
        await request('/api/profile/platform-accounts/sync', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
        data = await request('/api/profile'); renderBindings(); schedulePoll();
      } catch (error) { message(error.message, true); }
      finally { event.target.disabled = false; }
    };
    page.querySelector('#platformGrid').addEventListener('focusout', () => {
      setTimeout(() => { if (opened && data) renderBindings(); }, 0);
    });
    page.querySelector('#profileBack').onclick = back;
    page.querySelector('#personalAvatarFile').onchange = event => {
      const file = event.target.files[0];
      if (objectURL) URL.revokeObjectURL(objectURL);
      objectURL = null;
      if (!file) { avatarPreview(data.avatar, data.name); return; }
      if (file.size > 3 * 1024 * 1024 || !['image/png','image/jpeg','image/webp'].includes(file.type)) {
        event.target.value = ''; avatarPreview(data.avatar, data.name); message('请选择不超过 3 MB 的 PNG、JPEG 或 WebP 图片', true); return;
      }
      objectURL = URL.createObjectURL(file); avatarPreview(objectURL, data.name); message('头像已预览，点击“保存个人资料”后生效');
    };
    page.querySelector('#personalPasswordForm').onsubmit=async event=>{
      event.preventDefault();const form=event.target,button=form.querySelector('button'),status=page.querySelector('#passwordMessage');button.disabled=true;
      try{await request('/api/profile/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(form)))});form.reset();status.textContent='密码已修改，当前登录已保留。';}catch(error){status.textContent=error.message;}finally{button.disabled=false;}
    };
    page.querySelector('#personalForm').onsubmit = async event => {
      event.preventDefault();
      const button = event.target.querySelector('button[type="submit"]'); button.disabled = true;
      try {
        const result = await request('/api/profile', {method:'POST', body:new FormData(event.target)});
        data = result; renderIdentity(); updateHeader(result); message('个人资料已保存');
        window.dispatchEvent(new CustomEvent('personal-profile-saved',{detail:{memberId:result.member_id,avatar:result.member_avatar}}));
        page.querySelector('#personalName').value = result.name;
        page.querySelector('#personalAvatarFile').value = '';
        if (objectURL) URL.revokeObjectURL(objectURL); objectURL = null;
        avatarPreview(result.avatar, result.name);
      } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    };
    page.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); back(); }
      if (event.key === 'Tab') {
        const items = [...page.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href],summary')].filter(el => el.getClientRects().length);
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    });
  }
  function metrics(binding) {
    const stats = binding.snapshot || {};
    if (!Object.keys(stats).length) return '';
    const history = stats.rating_history || [];
    const difficulty = stats.difficulty || [];
    return `<div class="platform-metrics"><div><span>当前 Rating</span><strong>${number(stats.rating)}</strong></div><div><span>最高 Rating</span><strong>${number(stats.max_rating)}</strong></div><div><span>${escape(stats.solved_label || '通过题数')}</span><strong>${number(stats.solved)}</strong></div></div>
      <div class="platform-extra">${stats.rank ? `<span>${escape(stats.rank)}</span>` : ''}${typeof stats.contests === 'number' ? `<span>${number(stats.contests)} 场 Rated 比赛</span>` : ''}${difficulty.map(d => `<span>${escape(d.label)} ${number(d.count)}</span>`).join('')}</div>
      ${history.length ? `<details class="rating-details"><summary>最近比赛 Rating <span>${history.length} 场</span></summary><ol>${history.slice().reverse().map(r => `<li><span>${escape(r.name)}</span><strong>${number(r.rating)}</strong></li>`).join('')}</ol></details>` : ''}
      `;
  }
  function renderCard(card, platform, binding) {
    const meta = data.platforms[platform];
    const busy = binding?.status === 'pending';
    const status = !binding ? '新账号' : busy ? '同步中' : binding.status === 'failed' ? '待重试' : '已绑定';
    const key = `${platform}-${binding?.id || 'new'}`;
    const credentialFields = platform === 'codeforces' ? `<label for="key-${key}">API Key<input id="key-${key}" type="password" name="api_key" autocomplete="off"></label><label for="secret-${key}">API Secret<input id="secret-${key}" type="password" name="api_secret" autocomplete="off"></label>` : ['nowcoder','leetcode','qoj'].includes(platform) ? `<label for="cookie-${key}">Cookie<input id="cookie-${key}" type="password" name="cookie" maxlength="16000" autocomplete="off"></label>` : '';
    card.innerHTML = `<div class="platform-card-head"><span class="platform-monogram" data-platform="${platform}">${escape(meta.short)}</span><div class="platform-card-identity"><h3>${escape(meta.name)}</h3><small>${escape(binding?.account || '添加账号')}</small></div><span class="platform-status ${busy ? 'pending' : binding?.status || ''}">${status}</span></div>
      ${binding ? metrics(binding) : ''}
      ${binding?.error ? `<p class="platform-error" role="status">${escape(binding.error)}</p>` : ''}
      ${busy ? `<p class="platform-updated">已读取 ${number(binding.sync_progress?.count || 0)} 题</p>` : binding?.synced_at ? `<p class="platform-updated">${escape(new Date(binding.synced_at).toLocaleString('zh-CN'))}</p>` : ''}
      <form class="platform-bind-form"><label for="account-${key}">${escape(meta.hint)}</label><div><input id="account-${key}" name="account" required maxlength="100" value="${escape(binding?.account || '')}" autocomplete="off"><button class="secondary-button" type="submit" ${busy ? 'disabled' : ''}>${binding ? '更新绑定' : '添加'}</button></div>
      ${credentialFields ? `<details class="platform-credentials"><summary>凭据${binding?.has_credentials ? ' · 已保存' : ''}</summary><div class="credential-fields">${credentialFields}${binding?.has_credentials ? '<label class="credential-clear"><input type="checkbox" name="clear_credentials" value="1">清除已保存凭据</label>' : ''}</div></details>` : ''}</form>
      ${binding ? `<div class="platform-actions"><button type="button" class="secondary-button" data-refresh ${busy ? 'disabled' : ''}>↻ 同步资料</button><button type="button" data-full ${busy ? 'disabled' : ''}>完整同步</button>${binding.snapshot?.profile_url ? `<a href="${escape(binding.snapshot.profile_url)}" target="_blank" rel="noopener noreferrer">主页 ↗</a>` : ''}<button type="button" class="secondary-button" data-unbind>解绑</button></div>` : data.bindings.some(b=>b.platform===platform) ? `<div class="platform-actions"><button type="button" data-cancel>取消</button></div>` : ''}
      <p class="platform-action-message" role="status"></p>`;
    card.querySelector('form').onsubmit = event => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(event.target));
      payload.clear_credentials = payload.clear_credentials === '1';
      act(card, platform, binding ? 'PATCH' : 'CREATE', payload, binding);
    };
    card.querySelector('[data-refresh]')?.addEventListener('click', () => act(card, platform, 'SYNC', {}, binding));
    card.querySelector('[data-full]')?.addEventListener('click', () => act(card, platform, 'SYNC', {full:true}, binding));
    card.querySelector('[data-unbind]')?.addEventListener('click', () => {
      if (confirm(`解绑 ${binding.account}？`)) act(card, platform, 'DELETE', {}, binding);
    });
    card.querySelector('[data-cancel]')?.addEventListener('click', () => { adding.delete(platform); card.remove(); renderBindings(); });
    card.dataset.signature = JSON.stringify(binding || null);
  }
  function renderBindings() {
    const signature=JSON.stringify(data.bindings.map(binding=>[binding.id,binding.platform,binding.synced_at,binding.sync_progress?.count,binding.solved_baseline?.captured_at]));
    if(solvedBaselineSignature!==null && solvedBaselineSignature!==signature)
      window.dispatchEvent(new Event('platform-solved-updated'));
    solvedBaselineSignature=signature;
    const grid = page.querySelector('#platformGrid');
    for (const platform of Object.keys(data.platforms)) {
      let group = grid.querySelector(`[data-platform-group="${platform}"]`);
      const meta = data.platforms[platform];
      if (!group) {
        group = document.createElement('section'); group.className = 'platform-group platform-card'; group.dataset.platformGroup = platform;
        group.setAttribute('aria-label',meta.name);
        group.innerHTML = `<div class="platform-account-list"></div><button type="button" class="secondary-button platform-add-account" data-add-account>＋ 添加账号</button>`;
        group.querySelector('[data-add-account]').onclick = () => {
          adding.add(platform); renderBindings(); group.querySelector('[data-new-account] input')?.focus();
        };
        grid.append(group);
      }
      const list = group.querySelector('.platform-account-list');
      const bindings = data.bindings.filter(b => b.platform === platform);
      for (const card of list.querySelectorAll('[data-binding-id]')) {
        if (!bindings.some(b => String(b.id) === card.dataset.bindingId)) card.remove();
      }
      for (const binding of bindings) {
        let card = list.querySelector(`[data-binding-id="${binding.id}"]`);
        if (!card) { card = document.createElement('article'); card.className = 'platform-account'; card.dataset.bindingId = binding.id; list.append(card); }
        if (!card.querySelector('form')?.contains(document.activeElement) && card.dataset.signature !== JSON.stringify(binding)) renderCard(card, platform, binding);
      }
      if ((adding.has(platform) || !bindings.length) && !list.querySelector('[data-new-account]')) {
        const card = document.createElement('article'); card.className = 'platform-account platform-new-card'; card.dataset.newAccount = 'true'; list.append(card); renderCard(card, platform, null);
      }
      group.querySelector('[data-add-account]').hidden=!bindings.length || adding.has(platform);
    }
    page.querySelector('#bindingCount').textContent = `${data.bindings.length} 个账号`;
    const all = page.querySelector('#syncAllPlatforms');
    if (all) all.disabled = !data.bindings.some(b => b.status !== 'pending');
    const rewards=page.querySelector('#claimPlatformRewards');
    if(rewards){rewards.hidden=!data.rewards?.total;rewards.textContent=`领取 ${data.rewards?.total || 0} Coins`;}
  }
  async function act(card, platform, method, payload = {}, binding) {
    card.querySelectorAll('button').forEach(button => button.disabled = true);
    const output = card.querySelector('.platform-action-message'); output.textContent = '正在保存…';
    try {
      const url = method === 'CREATE' ? `/api/profile/platforms/${platform}/accounts` : method === 'SYNC' ? '/api/profile/platform-accounts/sync' : `/api/profile/platform-accounts/${binding.id}`;
      const body = method === 'SYNC' ? {...payload,ids:[binding.id]} : payload;
      await request(url, {method:['CREATE','SYNC'].includes(method) ? 'POST' : method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
      if (method === 'CREATE') { adding.delete(platform); card.remove(); }
      data = await request('/api/profile');
      if (method !== 'CREATE' && method !== 'DELETE') renderCard(card, platform, data.bindings.find(b => b.id === binding.id));
      renderBindings(); schedulePoll();
      window.dispatchEvent(new Event('platform-accounts-updated'));
    } catch (error) {
      output.textContent = error.message; card.querySelectorAll('button').forEach(button => button.disabled = false);
    }
  }
  function schedulePoll() {
    clearTimeout(poll);
    if (!opened || !data?.bindings.some(b => b.status === 'pending')) return;
    const version = generation;
    poll = setTimeout(async () => {
      try {
        const result = await request('/api/profile');
        if (!opened || version !== generation) return;
        data.bindings = result.bindings; data.rewards=result.rewards; renderBindings(); schedulePoll();
      } catch (error) { if (opened) message('同步状态读取失败，请重新打开个人页查看', true); }
    }, 3000);
  }
  async function open(push = true) {
    if (!allowed || opened || closing) return;
    if (!page) buildPage();
    opened = true; generation++;
    if (push && location.hash !== '#profile') history.pushState({...history.state, personalPage:true}, '', '#profile');
    const shell=document.querySelector('.app-shell');
    scrollState={x:scrollX,y:scrollY,inert:shell.inert,styles:['position','top','left','width','overflow'].map(key=>[key,document.body.style.getPropertyValue(key),document.body.style.getPropertyPriority(key)])};
    Object.assign(document.body.style,{position:'fixed',top:`-${scrollState.y}px`,left:`-${scrollState.x}px`,width:'100%',overflow:'hidden'});
    backdrop.hidden = false; page.hidden = false; document.querySelector('.app-shell').inert = true; document.body.classList.add('personal-open');
    page.style.transform='none';page.style.opacity='1';
    motion(backdrop,[{opacity:0},{opacity:1}],320);
    motion(page,[{transform:'translateX(100%)'},{transform:'translateX(0)'}],320);
    page.querySelector('#profileBack').focus({preventScroll:true});
    const version = generation;
    try {
      const result = await request('/api/profile');
      if (!opened || version !== generation) return;
      data = result;
      page.querySelector('#personalForm').hidden=!!result.read_only;
      page.querySelector('.personal-platform-section').hidden=!!result.read_only;
      renderIdentity();
      page.querySelector('#profileLoading').hidden = true; page.querySelector('#profileBody').hidden = false;
      // Keep unsaved edits when returning to the page.
      if (!page.dataset.loaded) {
        page.querySelector('#personalName').value = data.name; avatarPreview(data.avatar, data.name); page.dataset.loaded = 'true';
      }
      page.querySelector('#personalAccount').textContent = `登录账号：${data.account}`;
      renderBindings(); schedulePoll();
    } catch (error) { if (opened) { page.querySelector('#profileLoading').hidden = true; message(error.message, true); } }
  }
  async function close() {
    if (!opened || closing) return;
    opened = false; closing = true; generation++; clearTimeout(poll);
    motion(backdrop,[{opacity:1},{opacity:0}],260);
    await motion(page,[{transform:'translateX(0)'},{transform:'translateX(100%)'}],260);
    page.hidden = true; backdrop.hidden = true; backdrop.getAnimations().forEach(animation => animation.cancel());page.getAnimations().forEach(animation=>animation.cancel());closing = false;
    const state=scrollState;scrollState=null;
    document.querySelector('.app-shell').inert = state?.inert||false; document.body.classList.remove('personal-open');
    if(state){for(const[key,value,priority]of state.styles){if(value)document.body.style.setProperty(key,value,priority);else document.body.style.removeProperty(key);}window.scrollTo({left:state.x,top:state.y,behavior:'instant'});}
    entry.focus({preventScroll:true});
    if (location.hash === '#profile') open(false);
  }
  function back() {
    if (closing) return;
    if (history.state?.personalPage) history.back();
    else { history.replaceState(history.state, '', location.pathname + location.search); close(); }
  }
  addEventListener('popstate', () => { if (location.hash === '#profile') open(false); else close(); });
  entry?.addEventListener('click', () => open());
  window.addEventListener('club:cosmetics-expired',async()=>{
    const version=window.SpecialThemes?.version?.();
    try{
      const result=await request('/api/profile');
      if(window.SpecialThemes?.isCurrent?.(version)===false)return;
      if(data&&page){data=result;renderIdentity();}
      updateHeader(result);
    }catch{}
  });
  window.PersonalProfile = {
    init(me) { allowed = Boolean(me.account || me.name); entry.disabled = !allowed; updateHeader(me); if (location.hash === '#profile') open(false); },
    updateHeader,updateFrame,
  };
})();
