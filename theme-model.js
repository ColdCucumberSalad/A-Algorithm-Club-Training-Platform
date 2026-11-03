/* Pure appearance model, shared by the UI and its tests. */
(function (scope, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else scope.SiteTheme = api;
})(typeof window === 'undefined' ? globalThis : window, () => {
  'use strict';
  const roles = {
    pageBackground: '页面背景', surface: '卡片 / 列表底', surfaceElevated: '弹窗 / 浮层底',
    separator: '分隔线', labelPrimary: '主文字', labelSecondary: '次级文字',
    labelTertiary: '弱化文字', fill: '输入框 / 标签底', accent: '强调色', overlayDim: '遮罩',
  };
  const palettes = {
    light: {pageBackground:'#f2f2f7', surface:'#ffffff', surfaceElevated:'#ffffff', separator:'#c6c6c899', labelPrimary:'#1c1c1e', labelSecondary:'#3c3c4399', labelTertiary:'#3c3c4373', fill:'#f2f2f7', accent:'#f0605e', overlayDim:'#00000033'},
    dark: {pageBackground:'#000000', surface:'#1c1c1e', surfaceElevated:'#2c2c2e', separator:'#38383a99', labelPrimary:'#ffffff', labelSecondary:'#ebebf5b3', labelTertiary:'#ebebf580', fill:'#1c1c1e', accent:'#f0605e', overlayDim:'#00000066'},
  };
  const blocks = {
    other:{name:'其他内容卡片 / 空状态',selectors:'.panel,.empty-state,.contest-empty,.review-content-block,.history-summary,.review-author,.problem-row,.checkin-card,.balance-card,.currency-card,.inventory-item,.checkin-calendar,.calendar-container,.shop-management,.swal2-popup,.feedback-card'},
    sidebar:{name:'侧边导航', selectors:'.sidebar', kind:'ui'},
    topbar:{name:'顶部工具栏', selectors:'.topbar', kind:'ui'},
    intro:{name:'训练总览 / 页面标题', selectors:'.atlas-copy', kind:'ui'},
    progress:{name:'本周训练概览', selectors:'.atlas-stage'},
    daily:{name:'每日训练记录', selectors:'.pulse-panel'},
    score:{name:'统计 · 本周积分', selectors:'.metric-card[data-metric=score]'},
    submissionsCount:{name:'统计 · 有效提交', selectors:'.metric-card[data-metric=submissions]'},
    streak:{name:'统计 · 连续签到', selectors:'.metric-card[data-metric=streak]'},
    ranking:{name:'团队排行榜', selectors:'.leaderboard-panel,.full-leaderboard'},
    submissions:{name:'我的提交', selectors:'.my-submissions-live'},
    showcase:{name:'团队提交 / 题解', selectors:'.problem-toolbar,.problem-list,.submission-days,.problem-detail,.solution-card,.solution-item'},
    members:{name:'成员卡片', selectors:'.member-card'},
    contests:{name:'赛事中心', selectors:'.contest-overview,.contest-browser,.contest-card,.contest-problem-tray,.tracker-browser,.tracker-summary>div'},
    extensions:{name:'拓展工具', selectors:'.extension-tile,.extension-form:not(.poker-form),#extensionsView .panel'},
    admin:{name:'管理工作台', selectors:'.workbench-panel,.workbench-scope,.workbench-team,.workbench-nav'},
    shop:{name:'RBC 商店 / 背包', selectors:'.shop-item-card,.currency-summary,.transaction-list,.currency-stat-card,.currency-panel,.currency-balance-card,.inventory-item,#rbcshopView .panel'},
    profile:{name:'个人资料 / 平台绑定', selectors:'.personal-page,.personal-basics,.personal-platform-section,.platform-card'},
    dialog:{name:'弹窗 / 提交表单', selectors:'.team-management-dialog,.modal,.currency-modal,.modal-content,.contest-reward-summary,.poker-dialog'},
    auth:{name:'登录 / 注册 / 团队选择', selectors:'.auth-card'},
    authStory:{name:'登录 / 注册说明卡片', selectors:'.auth-story'},
    editor:{name:'Markdown 编辑器', selectors:'.blog-editor-modal'},
  };
  const clone = value => JSON.parse(JSON.stringify(value));
  const clamp = (value, min, max, fallback) => typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
  const color = (value, fallback) => typeof value === 'string' && /^#[a-f\d]{6}([a-f\d]{2})?$/i.test(value) ? value.toLowerCase() : fallback;
  const isObject = value => value && typeof value === 'object' && !Array.isArray(value);
  const option = (v, values, fallback) => values.includes(v) ? v : fallback;
  function defaults() {
    return {version:3, mode:'custom', customDark:false, accent:'#d96c75', palettes:clone(palettes),paletteOverrides:{light:[],dark:[]},
      uiScale:1, cardScale:1, radius:12, rowHeight:52, opacity:0.94, blur:18, glass:true,
      animations:true, heatmapMonthGap:true, editBlocks:false, textMode:'auto', align:'start', font:'system', blocks:{light:{},dark:{}}};
  }
  function blockDefaults() { return {enabled:false,background:'#ffffff',opacity:1,textMode:'auto',text:'#1c1c1e',accent:null,scale:1,radius:null}; }
  function sanitize(input) {
    const d = defaults(), s = isObject(input) ? input : {};
    d.mode = option(s.mode,['original','system','light','dark','custom'],d.mode);
    d.customDark = s.customDark === true; d.accent = color(s.accent,d.accent);
    for (const mode of ['light','dark']) {
      if(Array.isArray(s.paletteOverrides?.[mode]))d.paletteOverrides[mode]=[...new Set(s.paletteOverrides[mode].filter(key=>Object.hasOwn(roles,key)))];
      for (const role of Object.keys(roles)) d.palettes[mode][role]=color(s.palettes?.[mode]?.[role],d.palettes[mode][role]);
      for (const id of Object.keys(blocks)) {
        const b=s.blocks?.[mode]?.[id]; if (!isObject(b)) continue;
        d.blocks[mode][id]={enabled:b.enabled===true,background:color(b.background,mode==='dark'?'#1c1c1e':'#ffffff'),opacity:clamp(b.opacity,.05,1,1),
          textMode:option(b.textMode,['auto','light','dark','custom'],'auto'),text:color(b.text,'#1c1c1e'),accent:b.accent===null?null:color(b.accent,null),
          scale:clamp(b.scale,.8,1.4,1),radius:b.radius===null?null:clamp(b.radius,6,26,null)};
      }
    }
    for (const [key,min,max] of [['uiScale',.8,1.4],['cardScale',.8,1.35],['radius',6,26],['rowHeight',46,96],['opacity',.05,1],['blur',0,40]]) d[key]=clamp(s[key],min,max,d[key]);
    for (const key of ['glass','animations','heatmapMonthGap','editBlocks']) if(typeof s[key]==='boolean') d[key]=s[key];
    d.textMode=option(s.textMode,['auto','light','dark'],'auto'); d.align=option(s.align,['start','center'],'start');
    d.font=option(s.font,['system','sans'],'system');
    return d;
  }
  function rgba(hex) { const c=color(hex,'#ffffff'); return [parseInt(c.slice(1,3),16),parseInt(c.slice(3,5),16),parseInt(c.slice(5,7),16),c.length===9?parseInt(c.slice(7,9),16)/255:1]; }
  function hex(rgb) { return '#'+rgb.slice(0,3).map(v=>Math.round(v).toString(16).padStart(2,'0')).join(''); }
  function mix(a,b,t) { const x=rgba(a),y=rgba(b);return hex(x.map((n,i)=>n*(1-t)+y[i]*t)); }
  function composite(fg,bg,opacity=1) { const a=rgba(fg),b=rgba(bg),alpha=a[3]*opacity;return hex(a.map((n,i)=>n*alpha+b[i]*(1-alpha))); }
  function luminance(c) { const [r,g,b]=rgba(c).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return .2126*r+.7152*g+.0722*b; }
  function contrast(a,b) { const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); }
  function autoText(bg) {
    const best=contrast(bg,'#1c1c1e')>=contrast(bg,'#ffffff')?'#1c1c1e':'#ffffff';
    return contrast(bg,best)<4.5 && contrast(bg,'#000000')>contrast(bg,best)?'#000000':best;
  }
  function cssColor(c,opacity=1) {const [r,g,b,a]=rgba(c);return `rgba(${r}, ${g}, ${b}, ${Math.round(a*opacity*1000)/1000})`;}
  function modeOf(s,systemDark=false) {
    if(s.mode==='original')return 'light';
    if(s.mode==='custom')return s.customDark?'dark':'light';
    if(s.mode==='dark'||s.mode==='light')return s.mode;
    return systemDark?'dark':'light';
  }
  function paletteOf(s,mode) {
    if(s.mode==='original')return {...s.palettes.light,pageBackground:'#f6f9ff',labelPrimary:'#203654',labelSecondary:'#65758e',accent:'#245ec0'};
    if(s.mode!=='custom')return s.palettes[mode];
    const base=mode==='dark'?'#000000':'#ffffff',a=s.accent;
    // Match the app's accent-derived background and surfaces; keep edited roles.
    const derived={...s.palettes[mode],pageBackground:mix(a,base,mode==='dark'?.90:.94),surface:mix(a,base,mode==='dark'?.86:.975),surfaceElevated:mix(a,base,mode==='dark'?.80:.99),separator:mix(a,base,mode==='dark'?.62:.82),fill:mix(a,base,mode==='dark'?.88:.92),accent:a};
    for(const key of Object.keys(roles))if(s.paletteOverrides?.[mode]?.includes(key)||s.palettes[mode][key]!==palettes[mode][key])derived[key]=s.palettes[mode][key];
    return derived;
  }
  function companionColor(accent,mode='light') {
    const [r,g,b]=rgba(accent).map(value=>value/255),max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min;
    let hue=210;
    if(delta>.035){hue=(max===r?((g-b)/delta)%6:max===g?(b-r)/delta+2:(r-g)/delta+4)*60;hue=(hue+520)%360;}
    const saturation=.44,lightness=mode==='dark'?.66:.46,c=(1-Math.abs(2*lightness-1))*saturation;
    const x=c*(1-Math.abs((hue/60)%2-1)),m=lightness-c/2;
    const rgb=hue<60?[c,x,0]:hue<120?[x,c,0]:hue<180?[0,c,x]:hue<240?[0,x,c]:hue<300?[x,0,c]:[c,0,x];
    return hex(rgb.map(value=>(value+m)*255));
  }
  function blockTokens(s,mode,id,palette=paletteOf(s,mode)) {
    const b=s.blocks[mode][id],active=b?.enabled;
    let bg=active?b.background:palette[(['dialog','editor'].includes(id)?'surfaceElevated':'surface')];
    if(!s.glass)bg=bg.slice(0,7);
    const opacity=s.glass?(active?b.opacity:s.opacity):1;
    const blended=composite(bg,palette.pageBackground,opacity),textMode=active?b.textMode:s.textMode;
    const text=textMode==='custom'?b.text:textMode==='light'?'#ffffff':textMode==='dark'?'#1c1c1e':active?autoText(blended):palette.labelPrimary;
    return {background:cssColor(bg,opacity),solidBackground:blended,text,
      secondary:active?cssColor(text,.67):palette.labelSecondary,tertiary:active?cssColor(text,.52):palette.labelTertiary,
      accent:active&&b.accent?b.accent:palette.accent,scale:(blocks[id]?.kind==='ui'?s.uiScale:s.cardScale)*(active?b.scale:1),
      radius:active&&b.radius!==null?b.radius:s.radius,contrast:contrast(blended,composite(text,blended))};
  }
  return {roles,palettes,blocks,defaults,blockDefaults,sanitize,rgba,hex,mix,composite,luminance,contrast,autoText,cssColor,modeOf,paletteOf,blockTokens,companionColor,clone};
});
