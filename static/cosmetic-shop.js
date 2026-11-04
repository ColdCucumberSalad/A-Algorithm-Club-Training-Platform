/* Preview permanent cosmetics without changing ownership or the current outfit. */
window.CosmeticShop = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function openTitle({item, owned=false, canPurchase=true, onPurchase, onChange}) {
    document.querySelector('.cosmetic-preview-overlay')?.remove();
    const previous=document.activeElement, overlay=document.createElement('div');
    overlay.className='cosmetic-preview-overlay';
    const cosmetic=['badge','theme','frame'].includes(item.item_type),isTheme=item.item_type==='theme';
    // A missing expiry on existing ownership means permanent; sale terms apply to new purchases.
    const durationDays=owned?0:item.cosmetic_duration_days;
    const name=document.querySelector('#openProfile strong')?.textContent || '你的名字';
    let context='ranking',busy=false,equipped=false,checking=owned&&!item.preview_only,stateFailed=false;
    async function refreshEquipped(){
      checking=true;stateFailed=false;
      if(overlay.isConnected)draw();
      try{
        const response=await window.clubApi.request(cosmetic?'/api/profile/cosmetics':'/api/profile');
        if(!response.ok)throw Error('读取佩戴状态失败');
        const data=await response.json();
        if(!overlay.isConnected)return;
        if(cosmetic){
          window.SpecialThemes?.sync(data);
          equipped=isTheme?data.active_theme===item.cosmetic_key:(item.item_type==='frame'?data.avatar_frame:data.badge)?.key===item.cosmetic_key;
        }else {
          if(data.cosmetics)window.SpecialThemes?.sync(data.cosmetics);
          equipped=(data.titles||[]).some(title=>title.text===item.title_definition?.text);
        }
      }catch{stateFailed=true;}
      finally{checking=false;if(overlay.isConnected)draw();}
    }
    const close=()=>{if(busy)return;overlay.remove();document.removeEventListener('keydown',keydown,true);previous?.isConnected&&previous.focus();};
    const keydown=event=>{
      if(!overlay.isConnected||overlay.hidden)return;
      if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();}
      if(event.key==='Tab'){
        const controls=[...overlay.querySelectorAll('button:not(:disabled)')],first=controls[0],last=controls.at(-1);
        if(event.shiftKey&&(document.activeElement===first||!overlay.contains(document.activeElement))){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&(document.activeElement===last||!overlay.contains(document.activeElement))){event.preventDefault();first?.focus();}
      }
    };
    const now=()=>window.SpecialThemes?.now?.()??Date.now();
    const term=()=>item.expires_at?(Date.parse(item.expires_at)<=now()?'已过期':'有效至 '+new Date(item.expires_at).toLocaleString('zh-CN')):durationDays?durationDays+' 天':'永久有效';
    function draw(){
      const focusedIndex=overlay.isConnected?[...overlay.querySelectorAll('button')].indexOf(document.activeElement):-1;
      const isExpired=Boolean(owned&&item.expires_at&&Date.parse(item.expires_at)<=now());
      const blocked=!owned && (item.purchase_blocked||item.purchase_limit_reached||item.stock===0);
      overlay.innerHTML=`<section class="cosmetic-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="cosmeticProductTitle">
        <header><div><p class="section-label">${isTheme?'SPECIAL THEME':cosmetic?'BADGE COLLECTION':'TITLE COLLECTION'}</p><h2 id="cosmeticProductTitle">${esc(item.name)}</h2></div><button type="button" class="secondary-button" data-cosmetic-close aria-label="关闭商品详情">×</button></header>
        <div class="cosmetic-preview-stage${isTheme?' is-theme-preview':''}">${isTheme?'<img class="cosmetic-theme-poster" src="/static/cosmetics/taffy-scroll.jpg" alt="塔菲主题背景">':''}<div class="cosmetic-preview-tabs" role="tablist" aria-label="试戴场景"><button role="tab" aria-selected="${context==='ranking'}" data-cosmetic-context="ranking">排行榜</button><button role="tab" aria-selected="${context==='profile'}" data-cosmetic-context="profile">个人名片</button></div>
          <div class="cosmetic-live-person ${context==='profile'?'is-profile':''}">${window.MemberTitles.frameAvatar(`<span class="cosmetic-demo-avatar" aria-hidden="true">${esc(name.slice(0,1))}</span>`,isTheme?{key:"taffy-goggles"}:item.item_type==="frame"?{key:item.cosmetic_key}:null)}<div><div class="cosmetic-live-name">${context==='ranking'?(cosmetic?(item.item_type==='frame'?'':window.MemberTitles.badgeMarkup({key:item.item_type==='badge'?item.cosmetic_key:'taffy'})):window.MemberTitles.markup(item.title_definition)):''}<strong>${esc(name)}</strong></div>${context==='profile'?`<p class="cosmetic-live-name">${cosmetic?(item.item_type==='frame'?'':window.MemberTitles.badgeMarkup({key:item.item_type==='badge'?item.cosmetic_key:'taffy'})):window.MemberTitles.markup(item.title_definition)}</p>`:'<small>你的排行榜名片</small>'}</div></div>
          <span class="cosmetic-preview-note">试戴预览</span></div>
        <p class="cosmetic-product-description">${esc(item.description || '让你的每一次登榜都有自己的风格。')}</p><div class="cosmetic-product-traits"><span>${esc(term())}</span><span>全部团队通用</span><span>可随时更换</span>${isTheme?'<span class="cosmetic-theme-gift"><img src="/static/cosmetics/taffy-original-head.svg" alt="">附赠小塔菲徽章与护目镜头像框</span>':''}</div>
        <footer><div><strong>${item.preview_only?'预览示例':owned?'已拥有':`${Number(item.price)} RBC`}</strong><small>${owned?'选择后在当前团队佩戴':'购买后进入全局背包'}</small></div><button type="button" class="primary-button" data-cosmetic-action ${!canPurchase||blocked||equipped||isExpired||checking?'disabled':''}>${isExpired?'已过期':!canPurchase?'管理预览':checking?'读取状态…':stateFailed?'重试读取状态':equipped?(isTheme?'已启用':'已佩戴'):owned?(isTheme?'立即启用':'立即佩戴'):blocked?'暂不可购买':(isTheme?'购买主题':cosmetic?'购买徽章':'购买称号')}</button></footer><p class="cosmetic-status" role="status">${stateFailed?'暂时无法读取佩戴状态，请重试。':blocked?esc(item.purchase_block_reason||'当前商品不可购买'):''}</p>
      </section>`;
      overlay.querySelector('[data-cosmetic-close]').onclick=close;
      overlay.querySelectorAll('[data-cosmetic-context]').forEach(button=>button.onclick=()=>{context=button.dataset.cosmeticContext;draw();overlay.querySelector(`[data-cosmetic-context="${context}"]`).focus();});
      overlay.querySelector('[data-cosmetic-action]').onclick=async event=>{
        if(busy||checking||equipped)return;
        if(stateFailed){await refreshEquipped();return;}
        busy=true;const button=event.currentTarget;button.disabled=true;button.textContent=owned?'佩戴中…':'确认中…';
        try {
          if(!owned){overlay.hidden=true;try{if(await onPurchase()){owned=true;await onChange?.();}}finally{overlay.hidden=false;}}
          else {
            if(cosmetic){
              const selection=await window.SpecialThemes.select(item.item_type,item.cosmetic_key,button);
              if(item.item_type==='frame')window.PersonalProfile?.updateFrame?.(selection.avatar_frame);
            }
            else {
            const response=await window.clubApi.request('/api/profile/titles/wear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:item.title_definition.text})});
            const data=await response.json();if(!response.ok)throw Error(data.error||'佩戴失败');}
            equipped=true;
            if(typeof refreshCosmeticRankings==='function')refreshCosmeticRankings();
          }
          draw();overlay.querySelector('[data-cosmetic-close]').focus();
        }catch(error){draw();overlay.querySelector('.cosmetic-status').textContent=error.message;}
        finally{busy=false;}
      };
      if(focusedIndex>=0){
        const control=overlay.querySelectorAll('button')[focusedIndex];
        (control&&!control.disabled?control:overlay.querySelector('[data-cosmetic-close]')).focus();
      }
    }
    draw();document.body.append(overlay);document.addEventListener('keydown',keydown,true);overlay.querySelector('[data-cosmetic-close]').focus();
    if(checking)refreshEquipped();
    // Use capture so Escape only dismisses this topmost window.
  }
  return {openTitle};
})();
