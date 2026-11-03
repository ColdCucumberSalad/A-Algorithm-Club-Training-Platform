/* Global accounts are managed independently of team display identities. */
window.AccountManagement=(()=>{
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function read(url,options){const response=await clubApi.request(url,options);const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error||'操作失败，请重试');return data;}
  const notify=message=>{if(typeof showToast==='function')showToast(message);else{let notice=document.querySelector('#accountNotice');if(!notice){notice=document.createElement('p');notice.id='accountNotice';notice.className='account-notice';notice.setAttribute('role','status');document.body.append(notice);}notice.textContent=message;}};
  const request=(url,data,method='POST')=>read(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  let version=0,next=null,accounts=new Map(),timer,modal,returnFocus,accountDialog,selectedId=null,detailVersion=0;
  const $=selector=>document.querySelector(selector);
  const closureText='注销后无法登录，所有团队身份将停用，头像和平台凭据会清除。已发布的提交内容及交易记录按团队规则保留，作者显示为已注销用户。';
  function initModal(){
    if(modal)return;
    modal=document.createElement('div');modal.id='accountActionModal';modal.className='modal-backdrop account-action-overlay';modal.setAttribute('aria-hidden','true');
    modal.innerHTML='<section class="modal account-action-modal" role="dialog" aria-modal="true" aria-labelledby="accountActionTitle"><div class="modal-header"><h2 id="accountActionTitle"></h2><button type="button" class="close-button" data-account-modal-close aria-label="关闭">×</button></div><div id="accountActionBody"></div></section>';
    document.body.append(modal);modal.querySelector('[data-account-modal-close]').onclick=close;
    document.addEventListener('keydown',event=>{
      if(!modal.classList.contains('open'))return;
      if(event.key==='Escape'&&!modal.querySelector('[aria-busy=true]')){event.preventDefault();close();return;}
      if(event.key!=='Tab')return;
      const controls=[...modal.querySelectorAll('button:not(:disabled),input:not(:disabled)')].filter(el=>el.getClientRects().length),first=controls[0],last=controls.at(-1);
      if(event.shiftKey&&(document.activeElement===first||!modal.contains(document.activeElement))){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&(document.activeElement===last||!modal.contains(document.activeElement))){event.preventDefault();first?.focus();}
    });
  }
  function open(title,content){initModal();returnFocus=document.activeElement;$('#accountActionTitle').textContent=title;$('#accountActionBody').innerHTML=content;modal.classList.add('open');modal.setAttribute('aria-hidden','false');modal.querySelector('input')?.focus();}
  function close(){modal.classList.remove('open');modal.setAttribute('aria-hidden','true');if(returnFocus?.isConnected)returnFocus.focus();}
  function initAccounts(){
    if(accountDialog)return;
    accountDialog=document.createElement('div');accountDialog.id='globalAccountsDialog';accountDialog.className='modal-backdrop global-account-overlay';accountDialog.setAttribute('aria-hidden','true');
    accountDialog.innerHTML=`<section class="modal global-account-modal" role="dialog" aria-modal="true" aria-labelledby="gmTitle"><header class="modal-header"><div><p class="section-label">GLOBAL ACCOUNTS</p><h2 id="gmTitle">全局账号管理</h2></div><button class="close-button" type="button" data-gm-close aria-label="关闭账号管理">×</button></header><div class="gm-layout"><aside class="gm-sidebar"><input id="wbAccountSearch" type="search" placeholder="搜索账号、名字或团队" aria-label="搜索全局账号"><div class="gm-list-tools"><span id="gmTotal" class="muted"></span><button class="text-button" id="wbAccountsRefresh" type="button">刷新</button></div><div id="wbAccountsList"></div><button class="secondary-button" id="wbAccountsMore" type="button" hidden>加载更多</button></aside><main id="gmDetail" class="gm-detail"><p class="muted">选择账号查看资料</p></main></div></section>`;
    document.body.append(accountDialog);accountDialog.querySelector('[data-gm-close]').onclick=closeAccounts;
    accountDialog.addEventListener('change',event=>{if(event.target.matches('[data-pro-action]'))updateProFields(event.target.form);});
    accountDialog.addEventListener('submit',async event=>{
      const form=event.target;if(!form.matches('[data-pro-form]'))return;event.preventDefault();
      const id=Number(form.dataset.user),button=event.submitter;if(button.disabled)return;button.disabled=true;
      form.querySelector('[role=alert]').textContent='';
      try{
        const values=Object.fromEntries(new FormData(form)),payload={action:values.action,reason:values.reason,expected_revision:Number(form.dataset.revision)};
        if(values.action==='extend')payload.days=Number(values.days);
        if(values.action==='set_expiry')payload.expires_at=new Date(values.expires_at).toISOString();
        const signature=JSON.stringify(payload);
        if(form.dataset.command!==signature){form.dataset.command=signature;form.dataset.requestId=crypto.randomUUID();}
        payload.request_id=form.dataset.requestId;
        await request(`/api/management/accounts/${id}/pro`,payload);
        if(id===selectedId)await selectAccount(id);notify('Pro 设置已保存');
      }catch(error){form.querySelector('[role=alert]').textContent=error.message;}
      finally{button.disabled=false;}
    });
    document.addEventListener('keydown',event=>{if(!accountDialog.classList.contains('open')||modal?.classList.contains('open'))return;if(event.key==='Escape'){event.preventDefault();closeAccounts();return;}if(event.key!=='Tab')return;const els=[...accountDialog.querySelectorAll('button:not(:disabled),input,select')].filter(el=>el.getClientRects().length),first=els[0],last=els.at(-1);if(event.shiftKey&&(document.activeElement===first||!accountDialog.contains(document.activeElement))){event.preventDefault();last?.focus();}else if(!event.shiftKey&&(document.activeElement===last||!accountDialog.contains(document.activeElement))){event.preventDefault();first?.focus();}});
    accountDialog.addEventListener('submit',async event=>{
      const form=event.target,action=form.dataset.gmForm;if(!action)return;event.preventDefault();const id=selectedId,button=event.submitter;button.disabled=true;
      try{let url=`/api/management/accounts/${id}`,method='PATCH',payload=Object.fromEntries(new FormData(form));
        if(action==='balance')payload={action:'balance',balance:Number(payload.balance),expected_balance:Number(form.dataset.balance)};
        if(action==='quantity'){url+='/inventory';method='POST';payload={action:'quantity',inventory_id:Number(form.dataset.inventory),item_id:Number(form.dataset.item),quantity:Number(payload.quantity),expected_quantity:Number(form.dataset.quantity)};}
        if(action==='grant'){url+='/inventory';method='POST';form.dataset.requestId ||= crypto.randomUUID();payload={action:'grant',item_id:Number(payload.item),quantity:Number(payload.quantity),request_id:form.dataset.requestId};}
        await request(url,payload,method);if(id===selectedId)await selectAccount(id);notify('已保存');
      }catch(error){notify(error.message);}finally{button.disabled=false;}
    });
  }
  function closeAccounts(){accountDialog.classList.remove('open');accountDialog.setAttribute('aria-hidden','true');document.querySelector('[data-open-global-accounts]')?.focus();}
  async function openAccounts(){initAccounts();accountDialog.classList.add('open');accountDialog.setAttribute('aria-hidden','false');await loadAccounts();$('#wbAccountSearch').focus();}
  async function loadAccounts(page=1){
    initAccounts();const list=$('#wbAccountsList'),current=++version,q=$('#wbAccountSearch').value.trim();$('#wbAccountsMore').disabled=true;
    if(page===1)list.innerHTML='<p class="muted">正在加载账号…</p>';
    try{const data=await read(`/api/management/accounts?q=${encodeURIComponent(q)}&page=${page}`);if(current!==version)return;
      if(page===1){list.replaceChildren();accounts.clear();}
      for(const user of data.accounts){accounts.set(user.id,user);list.insertAdjacentHTML('beforeend',`<button type="button" class="gm-account-choice" data-gm-account="${user.id}" aria-pressed="${selectedId===user.id}"><strong>${esc(user.account)}</strong><small>${user.closed?'已注销':user.system_admin?'系统管理员':user.active?'正常':'已停用'}</small><span class="account-team-identities">${user.teams.length?user.teams.map(team=>`<span>${esc(team.name)}${team.active?'':'（已退出）'}</span>`).join(''):'<span>未加入团队</span>'}</span></button>`);}
      if(!data.accounts.length&&page===1)list.innerHTML='<p class="muted">没有匹配的账号</p>';
      next=data.next_page;$('#wbAccountsMore').hidden=!next;$('#gmTotal').textContent=`${data.total} 个账号`;$('#wbAccountsTotal').textContent=`${data.total} 个账号`;
      if(page===1&&data.accounts.length)await selectAccount(accounts.has(selectedId)?selectedId:data.accounts[0].id);
      else if(!data.accounts.length&&page===1){selectedId=null;detailVersion++;$('#gmDetail').textContent='没有匹配的账号';}
    }catch(error){if(current===version){list.textContent=error.message;notify(error.message);}}finally{if(current===version)$('#wbAccountsMore').disabled=false;}
  }
  async function selectAccount(id){
    selectedId=id;const current=++detailVersion;accountDialog.querySelectorAll('[data-gm-account]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.gmAccount)===id)));$('#gmDetail').innerHTML='<p class="muted">正在加载资料…</p>';
    try{const user=await read(`/api/management/accounts/${id}`);if(current!==detailVersion)return;accounts.set(id,user);const choice=accountDialog.querySelector(`[data-gm-account="${id}"] strong`);if(choice)choice.textContent=user.account;renderAccount(user);}catch(error){if(current===detailVersion)$('#gmDetail').textContent=error.message;}
  }
  function renderAccount(user){
    const editable=!user.closed&&!user.system_admin;
    const states={ready:'待核销',redeemed:'已核销',dispatching:'派发中',delivered:'派送成功',reclaimed:'已收回'};
    $('#gmDetail').innerHTML=`<header class="tm-member-heading"><h3>${esc(user.account)}</h3><span class="account-state">${user.closed?'已注销':user.system_admin?'系统管理员':'全局账号'}</span></header><section class="tm-card"><h4>团队身份</h4><div class="gm-team-list">${user.teams.map(team=>`<div><span><strong>${esc(team.name)}</strong><small>${esc(team.display_name)} · ${team.role==='admin'?'团队管理员':'普通成员'}${team.active?'':' · 已退出'}</small></span>${team.active&&editable?`<button type="button" class="secondary-button" data-gm-team="${team.id}" data-gm-member="${team.member_id}">管理团队身份</button>`:''}</div>`).join('')||'<p class="muted">尚未加入团队</p>'}</div></section>
      ${editable?`<form class="tm-card tm-form" data-gm-form="account"><h4>登录账号</h4><label>账号<input name="account" value="${esc(user.account)}" minlength="3" maxlength="150" required></label><label>设置新密码<input name="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="留空保留当前密码"></label><div class="tm-actions"><button class="primary-button" type="submit">保存账号设置</button></div></form>`:''}
      <form class="tm-card tm-balance" data-gm-form="balance" data-balance="${user.balance}"><div><h4>全局 RBC Coins</h4><p class="muted">所有团队共用此余额；可设置负数，后续收入先抵扣欠额</p></div><label>余额<input name="balance" type="number" min="-2147483648" max="2147483647" step="1" value="${user.balance}" required ${editable?'':'disabled'}></label>${editable?'<button class="secondary-button" type="submit">保存余额</button>':''}</form>
      ${proSection(user,editable&&user.active)}
      <section class="tm-card"><h4>全局背包</h4><div class="tm-inventory">${user.inventory.map(inv=>`<form class="tm-inventory-row" data-gm-form="quantity" data-inventory="${inv.id}" data-item="${inv.item_id}" data-quantity="${inv.quantity}"><div><strong>${esc(inv.item__name)}</strong><small>来源：${esc(inv.team__name)}</small></div><label>保留数量<input name="quantity" type="number" min="0" max="${inv.quantity}" value="${inv.quantity}" required ${editable?'':'disabled'}></label>${editable?'<button class="secondary-button" type="submit">保存</button>':''}</form>`).join('')}${user.units.map(unit=>`<div class="tm-inventory-row"><div><strong>${esc(unit.item_name)}</strong><small>${esc(unit.purchase__team__name)} · ${esc(states[unit.status]||unit.status)}</small></div>${editable&&['ready','dispatching'].includes(unit.status)?`<button class="secondary-button" type="button" data-gm-revoke="${unit.id}">收回</button>`:''}</div>`).join('')}${!user.inventory.length&&!user.units.length?'<p class="muted">背包暂无物品</p>':''}</div>${editable&&user.items.length?`<form class="tm-grant" data-gm-form="grant"><label>发放商品<select name="item" required>${user.items.map(item=>`<option value="${item.id}">${esc(item.team__name)} · ${esc(item.name)}</option>`).join('')}</select></label><label>数量<input name="quantity" type="number" min="1" max="100" value="1" required></label><button class="primary-button" type="submit">发放到背包</button></form>`:''}</section>${editable?`<section class="tm-card"><h4>注销全局账号</h4><button type="button" class="secondary-button" data-global-account-close="${user.id}">注销账号</button></section>`:''}`;
  }
  const proDate=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'未开通';
  function updateProFields(form){
    const action=form.elements.action.value;
    for(const field of form.querySelectorAll('[data-pro-field]')){
      const active=field.dataset.proField===action;field.hidden=!active;
      for(const input of field.querySelectorAll('input')){input.disabled=!active;input.required=active;}
    }
  }
  function proSection(user,editable){
    const pro=user.pro;if(!pro)return '';
    const actions={redeem:'卡密兑换',extend:'手动延长',set_expiry:'设置到期',revoke:'撤销 Pro',revoke_tokens:'撤销 App 登录'};
    return `<section class="tm-card gm-pro"><div class="gm-pro-heading"><h4>RBC Helper Pro</h4><span class="account-state">${pro.active?'已开通':pro.expires_at?'已到期或已撤销':'未开通'}</span></div><p>到期时间：<strong>${esc(proDate(pro.expires_at))}</strong></p><p class="muted">服务器时间：${esc(proDate(pro.server_time))} · 待兑换卡密：${Number(pro.unredeemed_codes)}</p>
      ${editable?`<form class="gm-pro-form" data-pro-form data-user="${user.id}" data-revision="${pro.revision}"><label>操作<select name="action" data-pro-action><option value="extend">手动延长</option><option value="set_expiry">设置到期时间</option><option value="revoke">撤销 Pro</option><option value="revoke_tokens">撤销全部 App 登录</option></select></label><label data-pro-field="extend">延长天数<input name="days" type="number" min="1" max="36500" step="1" value="31" required></label><label data-pro-field="set_expiry" hidden>到期时间（本地时区）<input name="expires_at" type="datetime-local" disabled></label><label>操作原因<input name="reason" maxlength="300" required autocomplete="off"></label><p class="muted">撤销 Pro 立即结束当前权益，已兑换卡密不能再次加时；尚未兑换的卡密仍可使用。撤销 App 登录后需重新登录。</p><p class="account-form-error" role="alert"></p><button type="submit" class="primary-button">保存 Pro 设置</button></form>`:''}
      <details class="gm-pro-audit"><summary>操作审计（最近 50 条）</summary><ol>${pro.audit.map(a=>`<li><strong>${esc(actions[a.action]||a.action)}</strong><span>${esc(proDate(a.created_at))} · ${esc(a.actor||'已删除账号')}</span><span>${esc(proDate(a.before_expires_at))} → ${esc(proDate(a.after_expires_at))}</span>${a.reason?`<p>${esc(a.reason)}</p>`:''}</li>`).join('')||'<li class="muted">暂无记录</li>'}</ol></details></section>`;
  }
  async function openSelf(){
    try{const user=await read('/api/account');if(user.system_admin){notify('系统管理员不能注销自己');return;}showClosure(user,false);}catch(error){notify(error.message);}
  }
  function showClosure(user,admin){
    open('注销全局账号',`<p class="account-closure-copy">${closureText}</p><p>目标账号：<strong>${esc(user.account)}</strong></p><form id="accountClosureForm" class="account-action-form"><label>输入“注销账号”确认<input name="confirmation" required autocomplete="off"></label><label>${admin?'当前管理员密码':'当前账号密码'}<input name="password" type="password" autocomplete="current-password" required></label><p class="account-form-error" role="alert"></p><div class="modal-footer"><button class="secondary-button" type="button" data-account-cancel>取消</button><button class="primary-button" type="submit">确认注销</button></div></form>`);
    $('#accountClosureForm [data-account-cancel]').onclick=close;
    $('#accountClosureForm').onsubmit=async event=>{
      event.preventDefault();const form=event.target,button=event.submitter;button.disabled=true;button.setAttribute('aria-busy','true');
      try{await request(admin?`/api/management/accounts/${user.id}/close`:'/api/account/close',{confirmation:form.elements.confirmation.value,account:user.account,[admin?'admin_password':'password']:form.elements.password.value});if(!admin){location.replace('/auth.html?notice=account-closed');return;}close();document.querySelector('#teamManagementDialog[open]')?.close();await loadAccounts();notify('账号已注销');}
      catch(error){form.querySelector('.account-form-error').textContent=error.message;}
      finally{button.disabled=false;button.removeAttribute('aria-busy');}
    };
  }
  function showEdit(user){
    open('全局账号设置',`<p class="muted">账号和密码在所有团队中通用；各团队展示名字请在成员管理中修改。</p><form id="globalAccountForm" class="account-action-form"><label>登录账号<input name="account" value="${esc(user.account)}" minlength="3" maxlength="150" required autocomplete="off"></label><label>设置新密码<input name="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="留空保留当前密码"></label><p class="account-form-error" role="alert"></p><div class="modal-footer"><button type="submit" class="primary-button">保存账号设置</button></div></form>`);
    $('#globalAccountForm').onsubmit=async event=>{event.preventDefault();const form=event.target,button=event.submitter;button.disabled=true;try{await request(`/api/management/accounts/${user.id}`,Object.fromEntries(new FormData(form)),'PATCH');close();await loadAccounts();notify('全局账号已保存');}catch(error){form.querySelector('.account-form-error').textContent=error.message;}finally{button.disabled=false;}};
  }
  document.addEventListener('click',event=>{
    if(event.target.closest('[data-open-global-accounts]')){openAccounts();return;}
    const accountChoice=event.target.closest('[data-gm-account]');if(accountChoice){selectAccount(Number(accountChoice.dataset.gmAccount));return;}
    const team=event.target.closest('[data-gm-team]');if(team){closeAccounts();TeamManagement.openMember(Number(team.dataset.gmTeam),Number(team.dataset.gmMember));return;}
    const revoke=event.target.closest('[data-gm-revoke]');if(revoke){const id=selectedId;clubDialog.confirm({title:'收回物品',text:'收回这件未使用的物品，不返还 Coins。',confirmText:'确认收回'}).then(async ok=>{if(!ok)return;try{await request(`/api/management/accounts/${id}/inventory`,{action:'revoke',unit_id:Number(revoke.dataset.gmRevoke)});if(id===selectedId)await selectAccount(id);}catch(error){notify(error.message);}});return;}
    if(event.target.closest('[data-close-own-account]')){openSelf();return;}
    const edit=event.target.closest('[data-global-account-edit]'),cancel=event.target.closest('[data-global-account-close]');
    if(edit){const user=accounts.get(Number(edit.dataset.globalAccountEdit));if(user)showEdit(user);}
    if(cancel){const user=accounts.get(Number(cancel.dataset.globalAccountClose));if(user)showClosure(user,true);}
    if(event.target.closest('#wbAccountsMore')&&next)loadAccounts(next);
    if(event.target.closest('#wbAccountsRefresh'))loadAccounts();
  });
  document.addEventListener('input',event=>{if(event.target.id==='wbAccountSearch'){version++;clearTimeout(timer);timer=setTimeout(()=>loadAccounts(),200);}});
  async function closeById(id){try{const user=await read(`/api/management/accounts/${id}`);showClosure(user,true);}catch(error){notify(error.message);}}
  return {loadAccounts,openSelf,openAccounts,closeById};
})();
