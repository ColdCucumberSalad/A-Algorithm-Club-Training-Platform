/* A purchased preset feeds the existing theme tokens; custom settings stay saved. */
window.SpecialThemes=(()=>{
  let library={themes:[],active_theme:'',badges:[],frames:[]},expiryTimer,clockOffset=0,stateVersion=0,selectionVersion=0;
  const selectionVersions=new WeakMap();
  let selectionQueue=Promise.resolve();
  const displayedEnds=new Set();
  function registerExpiry(end){
    if(Number.isFinite(end)&&end>Date.now()+clockOffset&&!displayedEnds.has(end)){displayedEnds.add(end);schedule();}
  }
  const expired=item=>item.expires_at&&Date.parse(item.expires_at)<=Date.now()+clockOffset;
  function schedule(){
    if(expiryTimer)clearTimeout(expiryTimer);
    const now=Date.now()+clockOffset;
    for(const end of displayedEnds)if(end<=now)displayedEnds.delete(end);
    const ends=[...library.themes,...library.badges,...library.frames].map(t=>t.expires_at).concat(library.title_expirations||[]).map(Date.parse).concat([...displayedEnds]).filter(end=>Number.isFinite(end)&&end>now);
    if(!ends.length)return;
    expiryTimer=setTimeout(async()=>{
      const now=Date.now()+clockOffset;
      sync({...library,server_time:new Date(now).toISOString(),title_expirations:(library.title_expirations||[]).filter(t=>Date.parse(t)>now)});
      window.MemberTitles?.pruneExpired?.(now);
      window.dispatchEvent(new Event('club:cosmetics-expired'));
      const version=stateVersion;
      try{
        const response=await window.clubApi.request('/api/profile/cosmetics');
        if(!response.ok)return;
        const data=await response.json();
        if(version===stateVersion)sync(data);
      }catch{}
    },Math.min(2147483647,Math.max(20,Math.min(...ends)-Date.now()-clockOffset+10)));
  }
  const palette={
    light:{pageBackground:'#fff3f7',surface:'#fff9fb',surfaceElevated:'#fffafd',fill:'#f9eaf0',separator:'#e8cdd8',labelPrimary:'#513d46',labelSecondary:'#92717e',labelTertiary:'#a98a97',accent:'#b96c88',overlayDim:'#36252e99'},
    dark:{pageBackground:'#24151f',surface:'#2c1d26',surfaceElevated:'#30212a',fill:'#3d2834',separator:'#60424f',labelPrimary:'#f3e6ec',labelSecondary:'#bca1af',labelTertiary:'#a68a99',accent:'#dfa0b7',overlayDim:'#160c12bd'}
  };
  function sync(data={}){
    stateVersion++;
    if(data.server_time&&Number.isFinite(Date.parse(data.server_time)))clockOffset=Date.parse(data.server_time)-Date.now();
    window.MemberTitles?.syncClock?.(Date.now()+clockOffset);
    library={themes:(data.themes||[]).filter(t=>!expired(t)),badges:(data.badges||[]).filter(t=>!expired(t)),frames:(data.frames||[]).filter(t=>!expired(t)),title_expirations:data.title_expirations||[],active_theme:data.active_theme||''};
    if(!library.themes.some(t=>t.key===library.active_theme))library.active_theme='';
    schedule();
    const active=library.themes.find(t=>t.key===library.active_theme&&(t.key==='taffy'||t.palettes?.light&&t.palettes?.dark));
    if(active){
      document.documentElement.dataset.specialTheme=active.key;
      const bg=window.CosmeticMedia?.safe(active.background||active.poster)?active.background||active.poster:'';
      document.documentElement.style?.setProperty('--site-cosmetic-background',bg?'url("'+bg+'")':'none');
    }else{delete document.documentElement.dataset.specialTheme;document.documentElement.style?.removeProperty('--site-cosmetic-background');}
    window.dispatchEvent(new Event('site-special-theme-change'));render();
  }
  function adjust(settings,mode){
    const active=library.themes.find(t=>t.key===library.active_theme);if(!active)return settings;
    const selected=active.palettes?.[mode]||(active.key==='taffy'?palette[mode]:null);if(!selected)return settings;
    const result=window.SiteTheme.clone(settings);result.mode='custom';result.accent=selected.accent;
    result.palettes[mode]={...result.palettes[mode],...selected};result.paletteOverrides[mode]=Object.keys(selected);result.blocks[mode]={};return result;
  }
  function requestSelection(kind,key){
    const task=selectionQueue.then(async()=>{
      const response=await window.clubApi.request('/api/profile/cosmetics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,key})});
      const data=await response.json();if(!response.ok)throw Error(data.error||'设置失败');
      // Invalidate reads immediately on success, before an optional transition commits the selection.
      stateVersion++;selectionVersions.set(data,++selectionVersion);return data;
    });
    selectionQueue=task.catch(()=>{});
    return task;
  }
  function applySelection(data){
    if(selectionVersions.get(data)!==selectionVersion)return false;
    sync(data);return true;
  }
  async function select(kind,key,button){
    const data=await requestSelection(kind,key);
    if(kind==='theme'&&button&&window.SiteAppearance?.transition){
      await window.SiteAppearance.transition(button,()=>applySelection(data),(data.themes?.find(t=>t.key===key)?.palettes?.[document.documentElement.dataset.siteMode==='dark'?'dark':'light']?.accent||palette[document.documentElement.dataset.siteMode==='dark'?'dark':'light'].accent));
    }else applySelection(data);
    return data;
  }
  function render(){
    const swatches=document.querySelector('#appearanceForm .settings-swatches');if(!swatches)return;
    let row=document.querySelector('#specialThemeLibrary');
    if(!row){row=document.createElement('div');row.id='specialThemeLibrary';row.className='settings-special-swatches';}
    if(row.previousElementSibling!==swatches)swatches.after(row);
    row.hidden=!library.themes.length;
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    row.innerHTML=library.themes.map(t=>`<button type="button" class="theme-special-swatch" data-special-key="${esc(t.key)}" aria-label="特殊主题：${esc(t.name||t.key)}" aria-pressed="${library.active_theme===t.key}"><span class="theme-special-portrait">${window.CosmeticMedia?.safe(t.icon||t.poster)?`<img src="${esc(t.icon||t.poster)}" alt="">`:'◈'}</span><span>${esc(t.name||t.key)}</span></button>`).join('')+'<span class="special-theme-status" role="status"></span>';
    row.querySelectorAll('[data-special-key]').forEach(button=>button.onclick=async()=>{if(library.active_theme===button.dataset.specialKey)return;button.disabled=true;try{await select('theme',button.dataset.specialKey,button);}catch(error){row.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}});

  }
  document.addEventListener('DOMContentLoaded',render);
  return {sync,adjust,select,requestSelection,applySelection,version:()=>stateVersion,invalidate:()=>++stateVersion,isCurrent:version=>version===stateVersion,render,registerExpiry,now:()=>Date.now()+clockOffset};
})();
