/* Native site appearance. No backend writes, duplicated application or image storage. */
(() => {
  'use strict';
  const T=window.SiteTheme,KEY='rbc-site-theme-v3',root=document.documentElement;
  const system=matchMedia('(prefers-color-scheme:dark)');
  let settings=T.defaults(),editingMode='light',editingBlock='progress',frame=0;
  const styled=new Map(),fontStyles=new Map();
  try {const raw=localStorage.getItem(KEY);if(raw)settings=T.sanitize(JSON.parse(raw));} catch (_) {}
  const vars={pageBackground:'page',surface:'surface',surfaceElevated:'elevated',separator:'border',labelPrimary:'text',labelSecondary:'secondary',labelTertiary:'subtle',fill:'fill',accent:'accent',overlayDim:'overlay-dim'};
  function mode(){return T.modeOf(settings,system.matches);}
  function feedback(text,error=false){const e=document.querySelector('#appearanceStatus');if(e){e.textContent=text;e.dataset.error=String(error);}}
  function save(message='外观已自动保存'){
    settings=T.sanitize(settings);
    try {localStorage.setItem(KEY,JSON.stringify(settings));feedback(message);}catch(_){feedback('无法持久保存，当前修改仍可预览；可导出配置留存。',true);}
    beginColorTransition();apply();
  }
  let colorTimer;
  function beginColorTransition(){
    if(radialChanging||!settings.animations||matchMedia('(prefers-reduced-motion:reduce)').matches)return;
    root.dataset.siteColorTransition='true';clearTimeout(colorTimer);colorTimer=setTimeout(()=>delete root.dataset.siteColorTransition,400);
  }
  let radialChanging=false,pendingPreset=null;
  root.dataset.themeTransitionApi='cover-then-reveal';
  async function revealTheme(wave,preset,radius){
    root.dataset.themeTransitionState='reveal';
    root.style.setProperty('--theme-wave-x',preset.x+'px');root.style.setProperty('--theme-wave-y',preset.y+'px');root.style.setProperty('--theme-wave-radius',radius+'px');
    if(typeof document.startViewTransition==='function'){
      let transition;
      try{transition=document.startViewTransition(()=>wave.remove());await transition.ready;await transition.finished;return;}
      catch(_){transition?.skipTransition();if(!wave.isConnected)document.body.append(wave);}
    }
    // Inverse mask fallback reveals the new page through a growing second circle.
    wave.getAnimations().forEach(a=>a.cancel());
    Object.assign(wave.style,{left:'0',top:'0',width:'100vw',height:'100dvh',transform:'none',borderRadius:'0'});
    await new Promise(resolve=>{
      const start=performance.now();
      function frame(now){const p=Math.min(1,(now-start)/620),ease=p<.5?4*p*p*p:1-Math.pow(-2*p+2,3)/2;
        const size=radius*ease;const mask=`radial-gradient(circle at ${preset.x}px ${preset.y}px,transparent ${size}px,#000 ${size+1}px)`;
        wave.style.maskImage=mask;wave.style.webkitMaskImage=mask;
        if(p<1)requestAnimationFrame(frame);else resolve();}
      requestAnimationFrame(frame);
    });
  }
  async function ripplePreset(preset,update){
    const radius=Math.hypot(Math.max(preset.x,innerWidth-preset.x),Math.max(preset.y,innerHeight-preset.y))+32;
    const wave=document.createElement('div');wave.className='theme-color-wave';wave.setAttribute('aria-hidden','true');
    Object.assign(wave.style,{left:preset.x+'px',top:preset.y+'px',background:preset.color});document.body.append(wave);
    const animation=wave.animate([{transform:'translate(-50%,-50%) scale(0)',opacity:1},{transform:`translate(-50%,-50%) scale(${radius/16})`,opacity:1}],{duration:520,easing:'cubic-bezier(.65,0,.35,1)',fill:'forwards'});
    try{await animation.finished;update();await revealTheme(wave,preset,radius);}
    catch(_){update();}finally{animation.cancel();wave.remove();}
  }

  async function changePreset(button){
    const dot=button.querySelector('.theme-swatch-dot')||button,rect=dot.getBoundingClientRect();
    const preset={color:button.dataset.accent,x:rect.left+rect.width/2,y:rect.top+rect.height/2};
    if(root.dataset.specialTheme){try{const data=await window.SpecialThemes.requestSelection('theme','');preset.beforeUpdate=()=>window.SpecialThemes.applySelection(data);}catch(error){feedback(error.message,true);return;}}
    if(radialChanging){pendingPreset=preset;return;}
    await runPreset(preset);
  }
  async function runPreset(preset){
    const update=()=>{preset.beforeUpdate?.();settings.accent=preset.color;settings.mode='custom';const current=mode();settings.paletteOverrides[current]=settings.paletteOverrides[current].filter(key=>key!=='accent');settings.palettes[current].accent=T.palettes[current].accent;save();renderSettings();};
    if(!settings.animations||matchMedia('(prefers-reduced-motion:reduce)').matches){update();return;}
    radialChanging=true;delete root.dataset.siteColorTransition;root.dataset.siteRadial='true';
    root.dataset.themeTransitionState='opaque-cover';
    try{await ripplePreset(preset,update);}
    finally{radialChanging=false;delete root.dataset.siteRadial;const next=pendingPreset;pendingPreset=null;if(next)runPreset(next);}
  }
  window.SiteAppearance={transition:async(button,update,color)=>{
    if(radialChanging)return update();
    if(!settings.animations||matchMedia('(prefers-reduced-motion:reduce)').matches)return update();
    const target=button.querySelector('.theme-special-portrait')||button,rect=target.getBoundingClientRect();
    const preset={color,x:rect.left+rect.width/2,y:rect.top+rect.height/2};
    radialChanging=true;root.dataset.siteRadial='true';root.dataset.themeTransitionState='opaque-cover';
    try{await ripplePreset(preset,update);}finally{radialChanging=false;delete root.dataset.siteRadial;const next=pendingPreset;pendingPreset=null;if(next)runPreset(next);}
  }};
  function originalStyle(el){if(!styled.has(el))styled.set(el,Object.fromEntries(['box-shadow','--site-block-radius','background-color','background-image','border-color','color','border-radius','backdrop-filter','--panel','--canvas','--blue','--blue-soft','--ink','--ink-strong','--muted','--teal','--teal-dark','--coral','--line','--teal-soft'].map(k=>[k,[el.style.getPropertyValue(k),el.style.getPropertyPriority(k)]])));return styled.get(el);}
  function restoreSurface(el){
    const original=styled.get(el);if(original)for(const[k,[value,priority]]of Object.entries(original)){if(value)el.style.setProperty(k,value,priority);else el.style.removeProperty(k);}
    delete el.dataset.siteThemed;
  }
  function setComponentVar(el,key,value){const original=originalStyle(el);if(!Object.hasOwn(original,key))original[key]=[el.style.getPropertyValue(key),el.style.getPropertyPriority(key)];el.style.setProperty(key,value);}
  function paint(el,tokens,palette){
    originalStyle(el);
    const personal=el.matches('#personalPage')||!!el.closest('#personalPage');
    if(personal){
      const text=tokens.contrast<4.5?T.autoText(tokens.solidBackground):tokens.text;
      tokens={...tokens,background:T.cssColor(tokens.solidBackground),text,secondary:T.cssColor(text,.78),tertiary:T.cssColor(text,.65)};
    }
    const fill=personal||T.contrast(T.composite(tokens.text,palette.fill),palette.fill)<4.5?T.mix(tokens.solidBackground,tokens.text,.055):palette.fill;
    const elevated=personal?tokens.solidBackground:palette.surfaceElevated;
    const values={'companion':T.companionColor(tokens.accent,mode()),'block-radius':tokens.radius+'px',text:tokens.text,secondary:tokens.secondary,subtle:tokens.tertiary,accent:tokens.accent,'button-text':T.autoText(T.composite(tokens.accent,tokens.solidBackground)),fill,border:palette.separator,elevated};
    for(const[k,v]of Object.entries(values))setComponentVar(el,'--site-'+k,v);
    const aliases={panel:tokens.background,canvas:palette.pageBackground,blue:tokens.accent,'blue-soft':T.cssColor(tokens.accent,.12),ink:tokens.text,'ink-strong':tokens.text,muted:tokens.secondary,teal:tokens.accent,'teal-dark':tokens.accent,coral:tokens.accent,line:palette.separator,'teal-soft':T.cssColor(tokens.accent,.12)};
    for(const[k,v]of Object.entries(aliases))setComponentVar(el,'--'+k,v);
    el.dataset.siteThemed='true';
    const flat=el.matches('#showcaseView .problem-toolbar,#showcaseView .problem-list,#showcaseView .submission-days,#reviewModal .review-blog-section');
    const shadow=flat||el.matches('.atlas-stage')?'none':mode()==='dark'?'0 8px 24px rgba(0,0,0,.28)':'0 6px 20px rgba(0,0,0,.045)';
    const properties={'block-background':flat?'transparent':tokens.background,'block-shadow':shadow,'block-blur':settings.glass?`blur(${settings.blur}px)`:'none',hover:T.mix(fill,tokens.accent,.07),selected:T.mix(fill,tokens.accent,.13),'avatar-background':T.mix(fill,tokens.accent,.14),'avatar-text':T.autoText(T.mix(fill,tokens.accent,.14)),'status-background':T.mix(tokens.solidBackground,'#67a68b',.13),'status-text':T.autoText(T.mix(tokens.solidBackground,'#67a68b',.13))};
    for(const[k,v]of Object.entries(properties))setComponentVar(el,'--site-'+k,v);
  }

  function cancelFontTransitions(el){
    // Measuring an in-flight font-size transition reads the previous scaled size.
    // Cancel only that transition so colors, hover effects and other motion continue.
    for(const animation of el.getAnimations?.()||[]){
      if(animation.transitionProperty==='font-size')animation.cancel();
    }
  }
  function scaleText(){
    for(const[el,record]of fontStyles){if(!el.isConnected){fontStyles.delete(el);continue;}if(record.value)el.style.setProperty('font-size',record.value,record.priority);else el.style.removeProperty('font-size');}
    for(const el of fontStyles.keys())cancelFontTransitions(el);
    if(settings.uiScale===1&&settings.cardScale===1&&!Object.values(settings.blocks[mode()]).some(b=>b.enabled&&b.scale!==1))return;
    const pending=[];
    for(const el of document.querySelectorAll('body *')){
      if(el.closest('#settingsView,.submission-code-editor')||el.namespaceURI!=='http://www.w3.org/1999/xhtml'||el.matches('script,style,link,meta'))continue;
      if(!el.matches('input,select,textarea')&&![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))continue;
      const id=el.closest('[data-theme-block]')?.dataset.themeBlock;
      const factor=id?T.blockTokens(settings,mode(),id).scale:settings.uiScale;
      if(factor===1)continue;
      if(!fontStyles.has(el))fontStyles.set(el,{value:el.style.getPropertyValue('font-size'),priority:el.style.getPropertyPriority('font-size')});
      pending.push([el,parseFloat(getComputedStyle(el).fontSize)*factor]);
    }
    for(const[el,size]of pending)el.style.setProperty('font-size',size+'px','important');
    for(const[el]of pending)cancelFontTransitions(el);
  }
  function apply(){
    const heatmapLayoutChanged=root.dataset.heatmapMonthGap!==String(settings.heatmapMonthGap);
    root.dataset.heatmapMonthGap=String(settings.heatmapMonthGap);
    if(heatmapLayoutChanged)window.dispatchEvent(new Event('site-heatmap-layout-change'));
    const current=mode(),effective=window.SpecialThemes?.adjust(settings,current)||settings,active=effective.mode!=='original',palette=T.paletteOf(effective,current);
    root.dataset.siteThemeActive=String(active);root.dataset.siteMode=current;root.dataset.siteMotion=settings.animations?'on':'off';root.dataset.siteGlass=settings.glass?'on':'off';root.dataset.siteAlign=settings.align;root.dataset.siteEditing=String(settings.editBlocks);root.dataset.siteDensity=String(active||settings.rowHeight!==52);root.dataset.siteFont=settings.font;
    root.style.setProperty('--site-ui-scale',settings.uiScale);root.style.setProperty('--site-radius',settings.radius+'px');root.style.setProperty('--site-row-height',settings.rowHeight+'px');
    root.style.setProperty('--site-companion',T.companionColor(palette.accent,current));
    root.style.setProperty('--site-hover',T.mix(palette.fill,palette.accent,.07));
    root.style.setProperty('--site-selected',T.mix(palette.fill,palette.accent,.13));
    root.style.setProperty('--site-avatar-background',T.mix(palette.fill,palette.accent,.14));
    root.style.setProperty('--site-avatar-text',T.autoText(T.mix(palette.fill,palette.accent,.14)));
    for(const[k,v]of Object.entries(vars))root.style.setProperty('--site-'+v,palette[k]);
    root.style.setProperty('--site-button-text',T.autoText(T.composite(palette.accent,palette.pageBackground)));
    // Legacy components outside registered cards must inherit the same palette.
    if(active){
      originalStyle(root);
      const aliases={ink:palette.labelPrimary,'ink-strong':palette.labelPrimary,muted:palette.labelSecondary,panel:palette.surface,canvas:palette.pageBackground,line:palette.separator,teal:palette.accent,'teal-dark':palette.accent,blue:palette.accent,coral:palette.accent,'teal-soft':T.cssColor(palette.accent,.12),'blue-soft':T.cssColor(palette.accent,.12)};
      for(const[k,v]of Object.entries(aliases))root.style.setProperty('--'+k,v);
    }else restoreSurface(root);
    if(!document.body)return;

    const surfaces=new Map();
    for(const[id,block]of Object.entries(T.blocks))for(const el of document.querySelectorAll(block.selectors))surfaces.set(el,id);
    for(const[el,id]of surfaces){
        const block=T.blocks[id];
        if(el.closest('#settingsView'))continue;
        el.dataset.themeBlock=id;
        if(active||settings.blocks[current][id]?.enabled)paint(el,T.blockTokens(effective,current,id,palette),palette);else restoreSurface(el);
        if(!el.matches('button,a')&&!el.querySelector(':scope > .theme-card-edit')){const edit=document.createElement('a');edit.className='theme-card-edit';edit.href='/?view=settings&block='+id;edit.textContent='调节';edit.setAttribute('aria-label','调节'+block.name);el.append(edit);}
    }
    document.querySelectorAll('#appearanceForm [data-accent]').forEach(button=>button.setAttribute('aria-pressed',String(!root.dataset.specialTheme&&settings.mode==='custom'&&settings.accent===button.dataset.accent)));
    scaleText();
    if(!settings.animations)document.getAnimations().forEach(a=>a.cancel());
    renderPreview();
  }
  function schedule(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;apply();});}
  function setPath(path,value){const keys=path.split('.'),last=keys.pop();keys.reduce((o,k)=>o[k],settings)[last]=value;}
  function ensureBlock(){return settings.blocks[editingMode][editingBlock] ||= {...T.blockDefaults(),background:editingMode==='dark'?'#1c1c1e':'#ffffff'};}
  function renderPreview(){
    const card=document.querySelector('#appearancePreview');if(!card)return;
    const effective=window.SpecialThemes?.adjust(settings,editingMode)||settings,palette=T.paletteOf(effective,editingMode),tokens=T.blockTokens(effective,editingMode,editingBlock,palette);
    for(const[k,v]of Object.entries({text:tokens.text,secondary:tokens.secondary,accent:tokens.accent,soft:T.cssColor(tokens.accent,.12),'button-text':T.autoText(tokens.accent),scale:tokens.scale}))card.style.setProperty('--preview-'+k,v);
    card.style.background=tokens.background;card.style.borderRadius=tokens.radius+'px';card.style.fontSize=15*tokens.scale+'px';card.style.backdropFilter=settings.glass?`blur(${settings.blur}px)`:'none';card.parentElement.style.background=palette.pageBackground;
    const name=document.querySelector('#previewBlockName');if(name.textContent!==T.blocks[editingBlock].name)name.textContent=T.blocks[editingBlock].name;
    const status=document.querySelector('#contrastStatus'),message=tokens.contrast<4.5?'文字对比偏低，建议选用自动文字颜色。':'文字对比度 '+tokens.contrast.toFixed(1)+' : 1';if(status.textContent!==message)status.textContent=message;status.dataset.warning=String(tokens.contrast<4.5);
  }
  function select(name,label,options,value){return `<label class="settings-row"><span>${label}</span><select name="${name}" aria-label="${label}">${options.map(([v,t])=>`<option value="${v}" ${String(value)===String(v)?'selected':''}>${t}</option>`).join('')}</select></label>`;}
  function slider(name,label,value,min,max,step=.01,hint=''){return `<label class="settings-slider"><span><span>${label}</span><output data-for="${name}">${Number(value).toFixed(step>=1?0:2)}</output></span><input type="range" name="${name}" aria-label="${label}" min="${min}" max="${max}" step="${step}" value="${value}">${hint?`<small>${hint}</small>`:''}</label>`;}
  function toggle(name,label,value,hint=''){return `<label class="settings-row settings-toggle"><span>${label}${hint?`<small>${hint}</small>`:''}</span><input type="checkbox" name="${name}" aria-label="${label}" ${value?'checked':''}></label>`;}
  function colorControl(name,label,value,reset=''){const rgba=T.rgba(value),rgb=value.slice(0,7);return `<div class="settings-color-row"><label for="${name}Color">${label}</label><input type="color" id="${name}Color" name="${name}" aria-label="${label}颜色" value="${rgb}"><input class="settings-hex" name="${name}Hex" aria-label="${label}十六进制颜色" value="${value}" maxlength="9" pattern="#[A-Fa-f0-9]{6}([A-Fa-f0-9]{2})?"><button type="button" class="settings-reset-role" data-reset="${reset}" ${reset?'':'hidden'} aria-label="重置${label}">重置</button><label class="settings-alpha">透明度<input type="range" name="${name}Alpha" aria-label="${label}透明度" min="0" max="1" step="0.01" value="${rgba[3]}"><output data-for="${name}Alpha">${Math.round(rgba[3]*100)}%</output></label></div>`;}
  function section(id,title,copy,content){return `<section class="settings-section" id="${id}"><div class="settings-section-heading"><h2>${title}</h2></div><div class="settings-group">${content}</div></section>`;}

  function modeSwitch(kind,index){return `<div class="settings-mode-tabs" data-switch-kind="${kind}" style="--switch-index:${index}" role="group" aria-label="${kind==='palette'?'编辑色板':'自定义主题底色'}"><span class="settings-mode-indicator" aria-hidden="true"></span>${['light','dark'].map((mode,i)=>`<button type="button" ${kind==='palette'?'data-edit-mode':'data-surface-mode'}="${mode}" aria-pressed="${index===i}">${i?'深色':'浅色'}</button>`).join('')}</div>`;}
  function surfaceModeControl(dark){return `<div class="settings-surface-row"><span>自定义主题底色</span><input type="hidden" name="customDark" value="${dark}">${modeSwitch('surface',dark?1:0)}</div>`;}
  function animateModeSwitch(kind,previous){
    const group=document.querySelector(`[data-switch-kind="${kind}"]`),indicator=group?.querySelector('.settings-mode-indicator');
    const current=Number(group?.style.getPropertyValue('--switch-index'));
    if(indicator&&settings.animations&&!matchMedia('(prefers-reduced-motion:reduce)').matches&&indicator.animate){indicator.animate([{transform:`translateX(${previous*100}%)`},{transform:`translateX(${current*100}%)`}],{duration:240,easing:'cubic-bezier(.22,.7,.3,1)'});}
    group?.querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});
  }
  function renderSettings(){
    const form=document.querySelector('#appearanceForm');if(!form)return;
    const d=settings,b=d.blocks[editingMode][editingBlock]||T.blockDefaults();
    const swatches=[['#d96c75','明亮红'],['#d37f96','樱花粉'],['#cf8776','珊瑚橘'],['#c69a68','暖杏橙'],['#b6a264','麦穗黄'],['#89a975','鼠尾草绿'],['#6da88e','薄荷绿'],['#6aa4a2','青瓷青'],['#78a4c8','晴空蓝'],['#829bb6','雾霾蓝'],['#818cc0','柔靛蓝'],['#a08dbb','丁香紫'],['#b18ba7','烟霞紫'],['#ae9183','奶咖棕'],['#8c979d','岩石灰']];
    form.innerHTML=
      section('theme','主题与外观','',
        select('mode','主题模式',[['original','原站主题'],['system','跟随系统'],['light','浅色'],['dark','深色'],['custom','自定义主题']],d.mode)+
        `<div class="settings-swatches">${swatches.map(([c,n])=>`<button type="button" aria-label="主题色：${n}" title="${n}" data-accent="${c}" style="--swatch:${c}" ${!root.dataset.specialTheme&&d.mode==='custom'&&d.accent===c?'aria-pressed="true"':'aria-pressed="false"'}><span class="theme-swatch-dot" aria-hidden="true"></span><span>${n}</span></button>`).join('')}</div>`+
        colorControl('accent','自定义主题色',d.accent)+surfaceModeControl(d.customDark)+
        `<button class="settings-link" type="button" id="derivePalette">恢复按主题色自动派生</button>`)+
      section('typography','文字与排版','界面文字与内容卡片分别缩放，避免一处调大导致全部挤在一起。',
        select('font','字体',[['system','系统字体 · 跟随设备'],['sans','无衬线 · Arial / 微软雅黑']],d.font)+
        slider('uiScale','界面文字大小',d.uiScale,.8,1.4,.05,'导航、标题和设置界面的文字。标准为 1.00。')+
        slider('cardScale','卡片文字缩放',d.cardScale,.8,1.35,.05,'训练记录、统计和内容卡片，独立于界面字号。')+
        select('textMode','卡片文字颜色',[['auto','自动'],['light','浅色文字'],['dark','深色文字']],d.textMode)+select('align','卡片内容对齐',[['start','靠左'],['center','居中']],d.align))+
      section('surfaces','卡片与效果','沿用日程助手的圆角、行高、透明度、模糊和动画控制。',
        toggle('heatmapMonthGap','热力图月份间隔',d.heatmapMonthGap,'在不同月份之间留出间距；月份和学期视图均生效，默认开启。')+slider('radius','卡片圆角',d.radius,6,26,1)+slider('rowHeight','列表行高',d.rowHeight,46,96,1)+slider('opacity','卡片不透明度',d.opacity,.05,1,.01)+
        slider('blur','毛玻璃模糊',d.blur,0,40,1,'模糊较高时，低性能设备可能不够流畅。')+toggle('glass','毛玻璃',d.glass,'关闭后使用不透明底色。')+toggle('animations','连贯动画',d.animations,'切页、展开与按压反馈；同时尊重系统的减少动态效果设置。'))+
      section('palette','自定义色板','与软件一致，页面底、卡片、浮层、文字、分隔线、强调色和遮罩均可独立调节。',
        modeSwitch('palette',editingMode==='dark'?1:0)+
        Object.entries(T.roles).map(([key,name])=>colorControl('palette-'+key,name,d.palettes[editingMode][key],key)).join(''))+
      section('blocks','板块独立设置','每个板块可沿用全局设置，也可以单独设置背景、文字、强调色、透明度和字号。',
        select('editingBlock','选择板块',Object.entries(T.blocks).map(([id,v])=>[id,v.name]),editingBlock)+
        `<p class="settings-caption">正在编辑：${editingMode==='light'?'浅色':'深色'}主题。切换上方色板标签可分别配置。</p>`+
        toggle('block-enabled','单独设置这个板块',b.enabled)+`<div ${b.enabled?'':'hidden'} id="blockCustomControls">`+
        colorControl('block-background','板块背景',b.background)+slider('block-opacity','板块不透明度',b.opacity,.05,1,.01)+
        select('block-textMode','板块文字颜色',[['auto','自动 · 按背景选择清晰文字'],['light','浅色文字'],['dark','深色文字'],['custom','自定义文字颜色']],b.textMode)+
        `<div id="blockTextControl" ${b.textMode==='custom'?'':'hidden'}>${colorControl('block-text','板块主文字',b.text)}</div>`+
        colorControl('block-accent','板块强调色',b.accent||T.paletteOf(d,editingMode).accent)+
        slider('block-scale','板块文字缩放',b.scale,.8,1.4,.05)+slider('block-radius','板块圆角',b.radius??d.radius,6,26,1)+
        `<button class="settings-link" type="button" id="resetBlock">此板块恢复全局设置</button></div>`+
        toggle('editBlocks','页面上显示板块调节入口',d.editBlocks,'打开后，每个板块会显示“调节”，可直接跳到对应设置。'))+
      section('backup','配置管理','外观配置只影响当前浏览器，不改账号、团队、积分和数据库。',`<div class="settings-wall-actions"><button type="button" class="secondary-button" id="exportAppearance">导出外观配置</button><label class="secondary-button settings-upload">导入配置<input type="file" id="importAppearance" accept="application/json,.json" aria-label="导入外观配置"></label><button type="button" class="settings-link" id="resetAppearance">恢复默认外观</button></div>`);
    window.SpecialThemes?.render();
    renderPreview();
  }

  function updateColor(name,value){
    if(name.startsWith('palette-')){const key=name.slice(8);settings.palettes[editingMode][key]=value;if(!settings.paletteOverrides[editingMode].includes(key))settings.paletteOverrides[editingMode].push(key);}
    else if(name.startsWith('block-'))ensureBlock()[name.slice(6)]=value;
    else {settings.accent=value;settings.mode='custom';}
  }
  function events(){
    const form=document.querySelector('#appearanceForm');if(!form)return;
    form.addEventListener('submit',event=>event.preventDefault());
    form.addEventListener('input',event=>{
      const el=event.target,name=el.name;if(!name||el.type==='file'||name==='editingBlock')return;
      const base=name.replace(/(Hex|Alpha)$/,'');
      if(el.type==='color'||name.endsWith('Hex')||name.endsWith('Alpha')){
        let value;
        if(name.endsWith('Alpha')){value=form.elements.namedItem(base+'Hex').value.slice(0,7)+Math.round(Number(el.value)*255).toString(16).padStart(2,'0');form.elements.namedItem(base+'Hex').value=value;}
        else if(name.endsWith('Hex')){if(!/^#[a-f\d]{6}([a-f\d]{2})?$/i.test(el.value)){el.setCustomValidity('请输入 #RRGGBB 或 #RRGGBBAA');return;}el.setCustomValidity('');value=el.value;form.elements.namedItem(base).value=value.slice(0,7);form.elements.namedItem(base+'Alpha').value=T.rgba(value)[3];}
        else {value=el.value+Math.round(Number(form.elements.namedItem(base+'Alpha').value)*255).toString(16).padStart(2,'0');form.elements.namedItem(base+'Hex').value=value;}
        updateColor(base,value);
      }else if(name.startsWith('block-'))ensureBlock()[name.slice(6)]=el.type==='checkbox'?el.checked:el.type==='range'?Number(el.value):el.value;
      else {setPath(name,el.type==='checkbox'?el.checked:el.type==='range'?Number(el.value):name==='customDark'?el.value==='true':el.value);if(name==='customDark')settings.mode='custom';}
      const output=form.querySelector(`[data-for="${name}"]`);if(output)output.textContent=name.endsWith('Alpha')?Math.round(el.value*100)+'%':Number(el.value).toFixed(Number(el.step)>=1?0:2);
      save();form.elements.namedItem('mode').value=settings.mode;
      if(name==='block-enabled')document.querySelector('#blockCustomControls').hidden=!el.checked;
      if(name==='block-textMode')document.querySelector('#blockTextControl').hidden=el.value!=='custom';
    });
    form.addEventListener('change',async event=>{
      const el=event.target;
      if(el.name==='editingBlock'){editingBlock=el.value;renderSettings();}
      if(['mode','customDark'].includes(el.name)){editingMode=mode();renderSettings();}
      if(el.id==='importAppearance'&&el.files[0]){try{if(el.files[0].size>200000)throw Error('配置文件过大');const raw=JSON.parse(await el.files[0].text());if(raw.version!==3)throw Error('配置版本不受支持');settings=T.sanitize(raw);save('已导入外观配置');renderSettings();}catch(error){feedback('导入失败：'+error.message,true);}el.value='';}
    });
    form.addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button)return;
      if(button.dataset.accent){changePreset(button);return;}
      if(button.dataset.surfaceMode){const previous=settings.customDark?1:0;settings.customDark=button.dataset.surfaceMode==='dark';settings.mode='custom';editingMode=mode();save();renderSettings();animateModeSwitch('surface',previous);return;}
      if(button.dataset.editMode){const previous=editingMode==='dark'?1:0;editingMode=button.dataset.editMode;renderSettings();animateModeSwitch('palette',previous);}
      if(button.dataset.reset){updateColor('palette-'+button.dataset.reset,T.palettes[editingMode][button.dataset.reset]);save();renderSettings();}
      if(button.id==='derivePalette'){settings.palettes=T.clone(T.palettes);settings.paletteOverrides={light:[],dark:[]};settings.mode='custom';save();renderSettings();}
      if(button.id==='resetBlock'){delete settings.blocks[editingMode][editingBlock];save();renderSettings();}
      if(button.id==='resetAppearance'){settings=T.defaults();save('已恢复默认明亮红主题');renderSettings();}
      if(button.id==='exportAppearance'){const url=URL.createObjectURL(new Blob([JSON.stringify(settings,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='RBC-theme.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    });
    form.addEventListener('click',event=>{const link=event.target.closest('a[href^="#"]');if(link)event.stopPropagation();});
  }
  system.addEventListener('change',schedule);window.addEventListener('resize',schedule);
  window.addEventListener('storage',event=>{if(event.key===KEY){try{settings=T.sanitize(JSON.parse(event.newValue||'{}'));apply();renderSettings();}catch(_) {}}});
  window.addEventListener('site-special-theme-change',apply);
  apply();
  document.addEventListener('DOMContentLoaded',()=>{
    const requested=new URLSearchParams(location.search).get('block');if(Object.hasOwn(T.blocks,requested))editingBlock=requested;editingMode=mode();
    renderSettings();events();apply();
    new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true});
    document.querySelectorAll('.page-view').forEach(el=>new MutationObserver(schedule).observe(el,{attributes:true,attributeFilter:['class']}));
    document.querySelector('.appearance-nav')?.addEventListener('click',event=>{const link=event.target.closest('a');if(!link)return;const section=document.querySelector(link.getAttribute('href'));if(section){event.preventDefault();section.scrollIntoView({block:'start',behavior:settings.animations?'smooth':'auto'});}});
  });
})();
