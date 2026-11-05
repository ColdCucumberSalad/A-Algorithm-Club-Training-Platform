window.CosmeticBundle=(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function open({item,canPurchase=true,onPurchase,onChange}){
  const overlay=document.createElement('div'),previous=document.activeElement;overlay.className='cosmetic-preview-overlay';
  const components=item.components?.length?item.components:[{...item.cosmetic,key:item.cosmetic_key,kind:item.item_type,duration_days:item.cosmetic_duration_days}];
  let state={},busy=false,checking=true,error='';
  const close=()=>{if(busy)return;overlay.remove();document.removeEventListener('keydown',keyboard,true);previous?.isConnected&&previous.focus();};
  const keyboard=e=>{if(!overlay.isConnected||overlay.hidden)return;if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close();}if(e.key==='Tab'){const bs=[...overlay.querySelectorAll('button:not(:disabled)')];if(e.shiftKey&&(document.activeElement===bs[0]||!overlay.contains(document.activeElement))){e.preventDefault();bs.at(-1)?.focus();}else if(!e.shiftKey&&(document.activeElement===bs.at(-1)||!overlay.contains(document.activeElement))){e.preventDefault();bs[0]?.focus();}}};
  const owned=c=>(state[({theme:'themes',badge:'badges',frame:'frames'})[c.kind]]||[]).find(a=>a.key===c.key);
  const term=c=>c.expires_at?'有效至 '+new Date(c.expires_at).toLocaleString('zh-CN'):c.duration_days?c.duration_days+' 天':'永久';
  function draw(){
   const focusedIndex=[...overlay.querySelectorAll('button')].indexOf(document.activeElement);
   overlay.innerHTML=`<section class="cosmetic-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="bundleTitle"><header><div><p class="section-label">COSMETIC COLLECTION</p><h2 id="bundleTitle">${esc(item.name)}</h2></div><button class="secondary-button" data-close aria-label="关闭装扮详情">×</button></header><p>${esc(item.description)}</p><div class="cosmetic-bundle-grid">${components.map((c,i)=>{const own=owned(c),d=own||c,icon=d.kind==='theme'?d.poster||d.background||d.icon:d.icon;return `<article><div>${d.kind==='frame'?MemberTitles.frameAvatar('<span class="cosmetic-demo-avatar">R</span>',d):d.kind==='badge'?MemberTitles.badgeMarkup(d):CosmeticMedia.safe(icon)?`<img src="${esc(icon)}" alt="">`:'◈'}</div><strong>${esc(d.name||d.key)}</strong><small>${({theme:'整站主题',badge:'电子徽章',frame:'头像框'})[d.kind]} · ${esc(own?own.expires_at?term(own):'永久拥有':term(c))}</small><button class="secondary-button" data-equip="${i}" ${!own||checking||busy?'disabled':''}>${own?(d.kind==='theme'?state.active_theme===d.key?'已启用':'启用主题':(d.kind==='badge'?state.badge:state.avatar_frame)?.key===d.key?'已佩戴':'佩戴'):'尚未拥有'}</button></article>`;}).join('')}</div><footer><div><strong>${Number(item.price||0)} RBC</strong><small>每项独立到期；已拥有的有限期装扮继续累加。</small></div>${!item.inventory_id&&!String(item.id).startsWith('gift-')?`<button class="primary-button" data-buy ${!canPurchase||item.stock===0||item.purchase_blocked||busy||checking?'disabled':''}>${item.purchase_blocked?'已永久拥有 / 不可购买':components.some(owned)?'购买并续期':'购买装扮'}</button>`:''}</footer><p class="cosmetic-status" role="status">${esc(checking?'正在读取拥有状态…':error||item.purchase_block_reason||'')}</p></section>`;
   overlay.querySelector('[data-close]').onclick=close;
   overlay.querySelectorAll('[data-equip]').forEach(button=>button.onclick=async()=>{if(busy)return;busy=true;button.disabled=true;const c=components[Number(button.dataset.equip)];try{state=await SpecialThemes.select(c.kind,c.key,button);if(c.kind==='frame')window.PersonalProfile?.updateFrame?.(state.avatar_frame);if(typeof refreshCosmeticRankings==='function')refreshCosmeticRankings();error='';}catch(e){error=e.message;}finally{busy=false;draw();}});
   overlay.querySelector('[data-buy]')?.addEventListener('click',async()=>{if(busy)return;busy=true;overlay.hidden=true;try{if(await onPurchase()){await refresh();await onChange?.();error='购买成功，可分别选择佩戴。';}}catch(e){error=e.message;}finally{overlay.hidden=false;busy=false;draw();}});
   if(overlay.isConnected&&!overlay.hidden){const control=overlay.querySelectorAll('button')[focusedIndex];(control&&!control.disabled?control:overlay.querySelector('[data-close]')).focus();}
  }
  async function refresh(){
   const version=SpecialThemes.version(),response=await clubApi.request('/api/profile/cosmetics');if(!response.ok)throw Error('无法读取装扮权益，请关闭后重试');
   state=await response.json();if(SpecialThemes.isCurrent(version))SpecialThemes.sync(state);checking=false;
  }
  document.body.append(overlay);document.addEventListener('keydown',keyboard,true);draw();overlay.querySelector('[data-close]').focus();
  refresh().then(()=>{if(overlay.isConnected)draw();}).catch(e=>{checking=false;error=e.message;if(overlay.isConnected)draw();});
 }
 return {open};
})();
