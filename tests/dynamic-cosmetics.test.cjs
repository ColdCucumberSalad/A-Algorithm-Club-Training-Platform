const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
function setup(){const context={window:{},document:{documentElement:{dataset:{},style:{setProperty(){},removeProperty(){}}},addEventListener(){},querySelector(){return null}},Event};context.window.dispatchEvent=()=>{};vm.createContext(context);for(const file of ['static/member-titles.js','static/special-themes.js'])vm.runInContext(fs.readFileSync(require.resolve('../'+file),'utf8'),context);return context;}
test('uploaded badge and frame metadata render without a compiled whitelist and reject external images',()=>{
 const c=setup(),ui=c.window.MemberTitles,url='/api/cosmetic-assets/media/'+'a'.repeat(64)+'.png';
 assert.match(ui.badgeMarkup({key:'new-badge',name:'<Artist>',icon:url}),/a{64}\.png/);
 assert.match(ui.badgeMarkup({key:'new-badge',name:'<Artist>',icon:url}),/&lt;Artist&gt;/);
 assert.equal(ui.badgeMarkup({key:'new-badge',icon:'https://example.com/image.png'}),'');
 const frame=ui.frameAvatar('<span>R</span>',{key:'new-frame',icon:url,geometry:{scale:1.5,x:-.25,y:-.3}});
 assert.match(frame,/--frame-size:150%/);assert.match(frame,/--frame-y:-30%/);
 assert.equal(ui.frameAvatar('R',{key:'bad',icon:'javascript:alert(1)'}),'R');
});
test('a server-owned theme with palettes activates without hardcoded Taffy checks',()=>{
 const c=setup(),model=require('../theme-model.js');c.window.SiteTheme=model;
 const settings=model.defaults(),before=JSON.stringify(settings),palettes=model.defaults().palettes;
 palettes.light.accent='#aa7788';palettes.dark.accent='#ddbbaa';
 c.window.SpecialThemes.sync({active_theme:'artist-garden',themes:[{key:'artist-garden',name:'Garden',palettes}]});
 assert.equal(c.document.documentElement.dataset.specialTheme,'artist-garden');
 assert.equal(c.window.SpecialThemes.adjust(settings,'dark').accent,'#ddbbaa');
 assert.equal(JSON.stringify(settings),before);
 c.window.SpecialThemes.sync({active_theme:'artist-garden',themes:[]});
 assert.equal(c.document.documentElement.dataset.specialTheme,undefined);
});
