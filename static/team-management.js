/* Team configuration and member maintenance in one bounded, themed dialog. */
window.TeamManagement = (() => {
  const esc = value => escapeHtml(String(value ?? ''));
  const icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  let dialog, overlay, teamId, memberId, rows = [], items = [], revision = 0, listRevision = 0, returnFocus, bodyOverflow;
  const $ = selector => dialog.querySelector(selector);
  const base = () => `/api/management/teams/${teamId}/members`;
  const json = data => ({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function init() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.id = 'teamManagementDialog'; dialog.className = 'team-management-dialog';
    dialog.setAttribute('aria-labelledby','tmTitle');
    dialog.setAttribute('aria-modal','true');
    dialog.innerHTML = `<header class="tm-header"><div><p class="section-label">TEAM MANAGEMENT</p><h2 id="tmTitle">团队设置</h2></div><button type="button" class="close-button" data-tm-close aria-label="关闭团队设置">×</button></header>
      <div class="tm-tabs" role="tablist" aria-label="团队设置分类">${[['config','团队配置'],['members','成员管理'],['currency','Coins 规则'],['notifications','通知配置']].map(([key,label],i)=>`<button type="button" role="tab" id="tmTab-${key}" aria-controls="tmPanel-${key}" aria-selected="${i===0}" tabindex="${i===0?0:-1}" data-tm-tab="${key}">${label}</button>`).join('')}</div>
      <div class="tm-content"><section id="tmPanel-config" role="tabpanel" aria-labelledby="tmTab-config"><div id="tmConfig"></div></section>
      <section id="tmPanel-members" role="tabpanel" aria-labelledby="tmTab-members" hidden><div class="tm-member-layout"><aside class="tm-member-sidebar"><label class="tm-search">搜索成员<input id="tmSearch" type="search" placeholder="名字、登录账号" autocomplete="off"></label><div id="tmMemberList" aria-label="团队成员"></div></aside><div id="tmMemberDetail" aria-live="polite"></div></div></section>
      <section id="tmPanel-currency" role="tabpanel" aria-labelledby="tmTab-currency" hidden><div id="tmCurrency"></div></section><section id="tmPanel-notifications" role="tabpanel" aria-labelledby="tmTab-notifications" hidden><div id="tmNotifications"></div></section></div>`;
    overlay = document.createElement('div'); overlay.className = 'tm-overlay';
    overlay.append(dialog); document.body.append(overlay);
    $('[data-tm-close]').onclick = () => dialog.close();
    dialog.addEventListener('close', () => {
      revision++; listRevision++; overlay.classList.remove('open');
      document.body.style.overflow = bodyOverflow;
      if (returnFocus?.isConnected) returnFocus.focus();
    });
    document.addEventListener('keydown', event => {
      if (!dialog.open || document.querySelector('.swal2-container, #wbConfirmModal.open, #wbRestoreModal.open')) return;
      if(document.querySelector('#accountActionModal.open,#globalAccountsDialog.open'))return;
      if (event.key === 'Escape') { event.preventDefault(); dialog.close(); return; }
      if (event.key !== 'Tab') return;
      const focusable = [...dialog.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')].filter(el => el.getClientRects().length && el.tabIndex >= 0);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
    });
    dialog.addEventListener('click', async event => {
      const tab = event.target.closest('[data-tm-tab]');
      if (tab) { selectTab(tab.dataset.tmTab); return; }
      const member = event.target.closest('[data-tm-member]');
      if (member) { await selectMember(Number(member.dataset.tmMember)); return; }
      if(event.target.closest('[data-title-add]')){const form=event.target.closest('form');if(form.querySelectorAll('[data-title-row]').length>=8){showToast('最多可授予 8 个称号');return;}form.querySelector('[data-title-rows]').insertAdjacentHTML('beforeend',titleRow({}));previewTitles(form);return;}
      if(event.target.closest('[data-title-remove]')){const form=event.target.closest('form');event.target.closest('[data-title-row]').remove();previewTitles(form);return;}
      if(event.target.closest('[data-title-clear]')){const form=event.target.closest('form');form.querySelector('[data-title-rows]').replaceChildren();form.requestSubmit(form.querySelector('[type=submit]'));return;}
      if (event.target.closest('[data-password-eye]')) {
        const input = $('[name="member_password"]'); const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        event.target.closest('button').setAttribute('aria-label',show?'隐藏新密码':'显示新密码');
        return;
      }
      const kick=event.target.closest('[data-tm-kick]');
      if(kick){const selectedTeam=teamId,selectedMember=memberId;if(!await clubDialog.confirm({title:'踢出团队',text:'只停用当前团队身份，账号、全局 Coins 和背包保留。',confirmText:'确认踢出'}))return;if(teamId!==selectedTeam||memberId!==selectedMember)return;try{await communityRequest(`/api/management/teams/${teamId}/members/${memberId}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:kick.dataset.tmKick})});await loadMembers();showToast('已踢出当前团队');}catch(error){showToast(error.message);}return;}
      const closeAccount=event.target.closest('[data-tm-close-account]');if(closeAccount){AccountManagement.closeById(Number(closeAccount.dataset.tmCloseAccount));return;}
      const revoke = event.target.closest('[data-tm-revoke]');
      if (revoke) {
        const selectedTeam = teamId, selectedMember = memberId;
        if (!await clubDialog.confirm({title:'收回物品',text:'收回该件未使用物品，不返还 Coins；卡密预留和可售库存将按规则释放。',confirmText:'确认收回'})) return;
        if (selectedTeam !== teamId || selectedMember !== memberId) return;
        await mutate(revoke, 'inventory', {action:'revoke',unit_id:Number(revoke.dataset.tmRevoke)});
      }
    });
    $('.tm-tabs').addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      const tabs = [...dialog.querySelectorAll('[data-tm-tab]')];
      let i = tabs.indexOf(document.activeElement);
      i = event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
      event.preventDefault(); tabs[i].focus(); selectTab(tabs[i].dataset.tmTab);
    });
    $('#tmSearch').oninput = renderList;
    dialog.addEventListener('input',event=>{const form=event.target.closest('[data-tm-form=title]');if(form)previewTitles(form);});
    dialog.addEventListener('submit', async event => {
      const form = event.target, kind = form.dataset.tmForm;
      if (!kind) return;
      event.preventDefault();
      const button = event.submitter;
      if (kind === 'profile') {
        await mutate(button,'settings',{action:'profile',name:form.elements.member_name.value,
          account:form.elements.member_account.value,role:form.elements.member_role.value,password:form.elements.member_password.value});
      } else if (kind === 'title') {
        await mutate(button,'settings',{action:'titles',titles:collectTitles(form)});
      } else if(kind==='cohort'){
        await mutate(button,'settings',{action:'admission_year',admission_year:Number(form.elements.admission_year.value)});
      } else if (kind === 'balance') {
        await mutate(button,'settings',{action:'balance',balance:Number(form.elements.balance.value),expected_balance:Number(form.dataset.balance)});
      } else if (kind === 'quantity') {
        await mutate(button,'inventory',{action:'quantity',inventory_id:Number(form.dataset.inventory),item_id:Number(form.dataset.item),quantity:Number(form.elements.quantity.value),expected_quantity:Number(form.dataset.quantity)});
      } else if (kind === 'grant') {
        form.dataset.requestId ||= window.clubApi.requestId();
        await mutate(button,'inventory',{action:'grant',item_id:Number(form.elements.item.value),quantity:Number(form.elements.quantity.value),request_id:form.dataset.requestId});
      }
    });
  }
  function selectTab(key) {
    dialog.querySelectorAll('[data-tm-tab]').forEach(tab => {
      const active = tab.dataset.tmTab === key;
      tab.setAttribute('aria-selected',String(active)); tab.tabIndex = active ? 0 : -1;
      $('#tmPanel-'+tab.dataset.tmTab).hidden = !active;
    });
    if (key === 'members' && !rows.length) loadMembers();
  }
  function renderList() {
    const q = $('#tmSearch').value.trim().toLowerCase();
    const matches = rows.filter(m => (m.name+' '+m.account).toLowerCase().includes(q));
    $('#tmMemberList').innerHTML = matches.map(m => `<button type="button" data-tm-member="${m.id}" class="tm-member-choice" aria-pressed="${m.id===memberId}"><span class="tm-avatar">${esc(m.name.slice(0,1))}</span><span><strong>${esc(m.name)}</strong><small>${esc(m.account)} · ${m.role==='admin'?'团队管理员':'普通成员'}</small></span></button>`).join('') || '<p class="tm-empty">没有匹配的成员</p>';
  }
  async function loadMembers() {
    const requestTeam = teamId, version = ++listRevision;
    $('#tmMemberList').innerHTML = '<p class="tm-empty">正在加载成员…</p>';
    try {
      const data = await communityRequest(base());
      if (requestTeam !== teamId || version !== listRevision || !dialog.open) return;
      rows = data.members; items = data.items; renderList();
      if (!rows.length) { $('#tmMemberDetail').innerHTML = '<p class="tm-empty">团队暂无成员</p>'; return; }
      await selectMember(rows.some(m=>m.id===memberId)?memberId:rows[0].id);
    } catch (error) { if (version===listRevision && dialog.open) { $('#tmMemberList').textContent = error.message; showToast(error.message); } }
  }
  async function selectMember(id) {
    memberId = id; const version = ++revision; renderList();
    $('#tmMemberDetail').innerHTML = '<p class="tm-empty">正在加载成员资料…</p>';
    try {
      const data = await communityRequest(`${base()}/${id}/settings`);
      if (version===revision && dialog.open) renderDetail(data);
    } catch (error) { if (version===revision) $('#tmMemberDetail').textContent = error.message; }
  }
  const statuses = {ready:'待核销',redeemed:'已核销',dispatching:'派发中',delivered:'派送成功',consumed:'已消耗',reclaimed:'已收回'};
  const titleFonts={system:'默认黑体',serif:'典雅宋体',kai:'手写楷体',mono:'等宽字体',rounded:'圆润字体'};
  function titleRow(title,fonts=titleFonts){return `<div class="tm-title-edit-row" data-title-row><label>称号文字<input data-title-text maxlength="20" required value="${esc(title.text||'')}" placeholder="例如：算法新星"></label><label>字体<select data-title-font>${Object.entries(fonts).map(([key,label])=>`<option value="${esc(key)}" ${key===(title.font||'system')?'selected':''}>${esc(label)}</option>`).join('')}</select></label><label class="tm-title-color">颜色<input data-title-color type="color" value="${esc(title.color||'#c96c7a')}"></label><label>样式<select data-title-style>${Object.entries(MemberTitles.styles).map(([key,label])=>`<option value="${key}" ${key===(title.style||"plain")?"selected":""}>${label}</option>`).join("")}</select></label><button type="button" class="secondary-button" data-title-remove aria-label="移除此称号">移除</button></div>`;}
  function collectTitles(form){return [...form.querySelectorAll('[data-title-row]')].map(row=>({text:row.querySelector('[data-title-text]').value,color:row.querySelector('[data-title-color]').value,font:row.querySelector('[data-title-font]').value,style:row.querySelector('[data-title-style]').value}));}
  function previewTitles(form){$('#tmTitlePreview').innerHTML=MemberTitles.list(collectTitles(form))+'<strong>'+esc(rows.find(m=>m.id===memberId)?.name||'成员')+'</strong>';}
  function renderDetail(m) {
    $('#tmMemberDetail').innerHTML = `<div class="tm-member-heading"><div><p class="section-label">MEMBER PROFILE</p><h3>${esc(m.name)}</h3></div><span class="tm-role">${m.role==='admin'?'团队管理员':'普通成员'}</span></div>
      <form class="tm-card tm-form" data-tm-form="profile"><h4>身份与账号</h4><label>成员名字<input name="member_name" value="${esc(m.name)}" maxlength="40" required></label><label>登录账号<input name="member_account" value="${esc(m.account)}" maxlength="150" required autocomplete="off"><small>登录账号在该成员加入的所有团队中通用。</small></label><label>团队身份<select name="member_role"><option value="member" ${m.role==='member'?'selected':''}>普通成员</option><option value="admin" ${m.role==='admin'?'selected':''}>团队管理员</option></select></label><label>设置新密码<span class="tm-password"><input name="member_password" type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="留空保留现有密码"><button type="button" data-password-eye aria-label="显示新密码">${icon}</button></span><small>原密码无法查看；重置后需使用新密码登录。</small></label><div class="tm-actions"><button class="primary-button" type="submit">保存成员资料</button></div></form>
      <form class="tm-card tm-form tm-title-form" data-tm-form="title"><h4>成员称号</h4><div data-title-rows class="tm-title-rows">${(m.titles||(m.title?.text?[m.title]:[])).map(title=>titleRow(title,m.title_fonts)).join('')}</div><div class="tm-title-preview" id="tmTitlePreview">${MemberTitles.list(m.titles||m.title)}<strong>${esc(m.name)}</strong></div><div class="tm-actions"><button type="button" class="secondary-button" data-title-add>＋ 添加称号</button><button class="secondary-button" type="button" data-title-clear>清空称号</button><button class="primary-button" type="submit">保存称号</button></div></form>
      <form class="tm-card tm-form" data-tm-form="cohort"><h4>入学年份与分队</h4><label>入学年份（账号通用）<input name="admission_year" type="number" min="2013" max="${new Date().getMonth()>=7?new Date().getFullYear():new Date().getFullYear()-1}" value="${m.cohort?.admission_year||''}" required></label><div class="tm-title-preview">${MemberTitles.cohort(m.cohort)}</div><div class="tm-actions"><button class="secondary-button" type="submit">保存入学年份</button></div></form>
      <form class="tm-card tm-balance" data-tm-form="balance" data-balance="${m.balance}"><div><h4>RBC Coins</h4><p class="muted">当前余额 <strong>${m.balance}</strong> RBC</p></div><label>调整为<input name="balance" type="number" min="-2147483648" max="2147483647" step="1" value="${m.balance}" required></label><button class="secondary-button" type="submit">保存余额</button></form>
      <section class="tm-card"><h4>背包物品</h4><div class="tm-inventory">${m.inventory.map(inv=>`<form class="tm-inventory-row" data-tm-form="quantity" data-item="${inv.item_id}" data-inventory="${inv.id}" data-quantity="${inv.quantity}"><div><strong>${esc(inv.item__name)}</strong><small>当前 ${inv.quantity} 件</small></div><label class="tm-quantity">保留数量<input type="number" name="quantity" min="0" max="${inv.quantity}" value="${inv.quantity}" required></label><button class="secondary-button" type="submit">保存</button></form>`).join('')}${m.units.map(unit=>`<div class="tm-inventory-row"><div><strong>${esc(unit.item_name)}</strong><small>#${unit.id} · ${esc(statuses[unit.status]||unit.status)}</small></div>${['ready','dispatching'].includes(unit.status)?`<button type="button" class="secondary-button" data-tm-revoke="${unit.id}">收回</button>`:''}</div>`).join('')}${!m.inventory.length&&!m.units.length?'<p class="tm-empty">背包暂无物品</p>':''}</div>
      <form class="tm-grant" data-tm-form="grant"><label>发放商品<select name="item" required><option value="">选择当前团队商品</option>${items.map(item=>`<option value="${item.id}">${esc(item.name)}</option>`).join('')}</select></label><label>数量<input name="quantity" type="number" min="1" max="100" value="1" required></label><button class="primary-button" type="submit" ${!items.length?'disabled':''}>发放到全局背包</button><small>管理员发放不扣 Coins，会占用商品库存并保留发放记录。</small></form></section><section class="tm-card tm-account-danger"><h4>账号与团队</h4><div class="tm-actions"><button type="button" class="secondary-button" data-tm-kick="${esc(m.name)}">踢出当前团队</button><button type="button" class="secondary-button" data-tm-close-account="${m.user_id}">注销全局账号</button></div></section>`;
  }
  async function mutate(button, suffix, payload) {
    if (button.disabled) return;
    const selectedTeam = teamId, selectedMember = memberId, version = revision;
    button.disabled = true;
    try {
      const options = json(payload); if (suffix==='settings') options.method='PATCH';
      const data = await communityRequest(`${base()}/${selectedMember}/${suffix}`, options);
      if (selectedTeam===teamId && version===revision && dialog.open) {
        const row = rows.find(m=>m.id===data.id); if(row) Object.assign(row,data);
        renderList(); renderDetail(data);
      }
      showToast('已保存');
    } catch(error) { showToast(error.message); }
    finally { button.disabled = false; }
  }
  function open(data, force) {
    init();
    const changed = teamId !== data.id;
    if (changed) { revision++; listRevision++; teamId=data.id; memberId=null; rows=[]; items=[]; $('#tmSearch').value=''; $('#tmMemberDetail').innerHTML=''; selectTab('config'); }
    $('#tmTitle').textContent = data.name + ' · 团队设置';
    const reopening = !dialog.open;
    if (reopening) {
      returnFocus=document.activeElement; bodyOverflow=document.body.style.overflow;
      overlay.classList.add('open'); dialog.show(); document.body.style.overflow='hidden'; $('[data-tm-close]').focus();
    }
    if ((force || reopening) && $('#tmTab-members').getAttribute('aria-selected')==='true') loadMembers();
    return {config:$('#tmConfig'), currency:$('#tmCurrency'), notifications:$('#tmNotifications')};
  }
  async function openMember(tid,mid){await openTeamSettings(tid);selectTab('members');await loadMembers();if(rows.some(m=>m.id===mid))await selectMember(mid);}
  return {open,openMember};
})();
