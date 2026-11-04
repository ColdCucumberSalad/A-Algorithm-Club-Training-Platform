/* A purchased preset feeds the existing theme tokens; custom settings stay saved. */
window.SpecialThemes=(()=>{
  let library={themes:[],active_theme:'',badges:[],frames:[]},expiryTimer,clockOffset=0;
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
      try{const response=await window.clubApi.request('/api/profile/cosmetics');if(response.ok)sync(await response.json());}catch{}
    },Math.min(2147483647,Math.max(20,Math.min(...ends)-Date.now()-clockOffset+10)));
  }
  const palette={
    light:{pageBackground:'#fff3f7',surface:'#fff9fb',surfaceElevated:'#fffafd',fill:'#f9eaf0',separator:'#e8cdd8',labelPrimary:'#513d46',labelSecondary:'#92717e',labelTertiary:'#a98a97',accent:'#b96c88',overlayDim:'#36252e99'},
    dark:{pageBackground:'#24151f',surface:'#2c1d26',surfaceElevated:'#30212a',fill:'#3d2834',separator:'#60424f',labelPrimary:'#f3e6ec',labelSecondary:'#bca1af',labelTertiary:'#a68a99',accent:'#dfa0b7',overlayDim:'#160c12bd'}
  };
  function sync(data={}){
    if(data.server_time&&Number.isFinite(Date.parse(data.server_time)))clockOffset=Date.parse(data.server_time)-Date.now();
    window.MemberTitles?.syncClock?.(Date.now()+clockOffset);
    library={themes:(data.themes||[]).filter(t=>!expired(t)),badges:(data.badges||[]).filter(t=>!expired(t)),frames:(data.frames||[]).filter(t=>!expired(t)),title_expirations:data.title_expirations||[],active_theme:data.active_theme||''};
    if(!library.themes.some(t=>t.key===library.active_theme))library.active_theme='';
    schedule();
    const active=library.active_theme==='taffy'&&library.themes.some(t=>t.key==='taffy');
    if(active)document.documentElement.dataset.specialTheme='taffy';else delete document.documentElement.dataset.specialTheme;
    window.dispatchEvent(new Event('site-special-theme-change'));render();
  }
  function adjust(settings,mode){
    if(document.documentElement.dataset.specialTheme!=='taffy')return settings;
    const result=window.SiteTheme.clone(settings);result.mode='custom';result.accent=palette[mode].accent;
    result.palettes[mode]={...result.palettes[mode],...palette[mode]};result.paletteOverrides[mode]=Object.keys(palette[mode]);result.blocks[mode]={};return result;
  }
  async function requestSelection(kind,key){
    const response=await window.clubApi.request('/api/profile/cosmetics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,key})});
    const data=await response.json();if(!response.ok)throw Error(data.error||'设置失败');return data;
  }
  async function select(kind,key,button){
    const data=await requestSelection(kind,key);
    if(kind==='theme'&&button&&window.SiteAppearance?.transition){
      await window.SiteAppearance.transition(button,()=>sync(data),palette[document.documentElement.dataset.siteMode==='dark'?'dark':'light'].accent);
    }else sync(data);
    return data;
  }
  function render(){
    const swatches=document.querySelector('#appearanceForm .settings-swatches');if(!swatches)return;
    let row=document.querySelector('#specialThemeLibrary');
    if(!row){row=document.createElement('div');row.id='specialThemeLibrary';row.className='settings-special-swatches';}
    if(row.previousElementSibling!==swatches)swatches.after(row);
    row.hidden=!library.themes.some(t=>t.key==='taffy');
    row.innerHTML='<button type="button" class="theme-special-swatch" data-special-key="taffy" aria-label="特殊主题：塔菲" aria-pressed="'+(library.active_theme==='taffy')+'"><span class="theme-special-portrait"><img src="/static/cosmetics/taffy-original-head.svg" alt=""></span><span>塔菲</span></button><span class="special-theme-status" role="status"></span>';
    const button=row.querySelector('[data-special-key]');
    button.onclick=async()=>{if(library.active_theme==='taffy')return;button.disabled=true;try{await select('theme','taffy',button);}catch(error){row.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}};
  }
  document.addEventListener('DOMContentLoaded',render);
  return {sync,adjust,select,requestSelection,render,registerExpiry};
})();
