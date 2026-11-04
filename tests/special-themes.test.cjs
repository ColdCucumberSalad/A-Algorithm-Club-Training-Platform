const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const T=require('../theme-model.js');
function setup(){
 const root={dataset:{}};
 const context={window:{SiteTheme:T,dispatchEvent(){}},document:{documentElement:root,addEventListener(){},querySelector(){return null}},Event};
 vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/special-themes.js'),'utf8'),context);
 return {themes:context.window.SpecialThemes,root};
}
test('special theme uses tokens without overwriting saved custom theme or layout',()=>{
 const {themes,root}=setup(),settings=T.defaults();settings.accent='#889966';settings.blocks.light.daily={enabled:true,background:'#123456'};
 const before=JSON.stringify(settings);
 themes.sync({themes:[{key:'taffy'}],active_theme:'taffy'});
 assert.equal(root.dataset.specialTheme,'taffy');
 for(const mode of ['light','dark']){
   const adjusted=themes.adjust(settings,mode),palette=T.paletteOf(adjusted,mode);
   assert.notEqual(adjusted,settings);assert.notEqual(palette.accent,settings.accent);
   assert.ok(T.contrast(palette.labelPrimary,palette.surface)>4.5);
   assert.equal(adjusted.uiScale,settings.uiScale);assert.equal(adjusted.radius,settings.radius);
 }
 assert.equal(JSON.stringify(settings),before);
 themes.sync({themes:[{key:'taffy'}],active_theme:''});
 assert.equal(themes.adjust(settings,'light'),settings);assert.equal(root.dataset.specialTheme,undefined);
});
test('unknown or unowned presets cannot become active through returned state',()=>{
 const {themes,root}=setup(),settings=T.defaults();
 for(const data of [{themes:[],active_theme:'taffy'},{themes:[{key:'unknown'}],active_theme:'unknown'}]){
   themes.sync(data);assert.equal(root.dataset.specialTheme,undefined);assert.equal(themes.adjust(settings,'dark'),settings);
 }
});

test('finite rights schedule one expiry, revert the active theme and prune displayed cosmetics',async()=>{
 let now=Date.now(),callback,delay,requests=0;const root={dataset:{}},events=[];
 class Clock extends Date{static now(){return now;}}
 const context={Date:Clock,Event,setTimeout(fn,ms){callback=fn;delay=ms;return 1;},clearTimeout(){},
 document:{documentElement:root,addEventListener(){},querySelector(){return null}},
 window:{dispatchEvent(event){events.push(event.type)},MemberTitles:{pruneExpired(time){assert.equal(time,now)}},clubApi:{async request(){requests++;return {ok:false}}}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/special-themes.js'),'utf8'),context);
 context.window.SpecialThemes.sync({server_time:new Date(now).toISOString(),themes:[{key:'taffy',expires_at:new Date(now+1000).toISOString()}],active_theme:'taffy'});
 assert.equal(root.dataset.specialTheme,'taffy');assert.ok(delay>=1000&&delay<=1020);
 now+=1010;await callback();assert.equal(root.dataset.specialTheme,undefined);assert.equal(requests,1);assert.ok(events.includes('club:cosmetics-expired'));
});

function cosmeticClock(skew=0){
 let server=Date.parse('2026-11-04T10:00:00Z'),callback,delay;const nodes=[];
 class Clock extends Date{static now(){return server+skew;}}
 const context={Date:Clock,Event,setTimeout(fn,ms){callback=fn;delay=ms;return 1},clearTimeout(){},
 document:{documentElement:{dataset:{}},addEventListener(){},querySelector(){return null},querySelectorAll(){return nodes}},
 window:{dispatchEvent(){},clubApi:{async request(){return {ok:false}}}}};
 vm.createContext(context);
 for(const file of ['member-titles','special-themes'])vm.runInContext(fs.readFileSync(require.resolve('../static/'+file+'.js'),'utf8'),context);
 return {ui:context.window.MemberTitles,themes:context.window.SpecialThemes,nodes,now:()=>server,delay:()=>delay,advance:async ms=>{server+=ms;await callback();}};
}

test('other members cosmetics schedule expiry with an empty viewer library and preempt later deadlines',async()=>{
 const c=cosmeticClock();c.themes.sync({server_time:new Date(c.now()).toISOString()});
 const end=new Date(c.now()+1000).toISOString();
 for(const markup of [c.ui.markup({text:'Temporary',expires_at:end}),c.ui.badgeMarkup({key:'taffy',expires_at:end}),c.ui.frameAvatar('avatar',{key:'taffy-goggles',expires_at:end})]){
   assert.match(markup,/data-cosmetic-until/);
   const node={dataset:{cosmeticUntil:String(c.now()+1000)},remove(){this.removed=true}};c.nodes.push(node);
 }
 assert.equal(c.delay(),1010);
 c.themes.sync({themes:[{key:'taffy',expires_at:new Date(c.now()+10000).toISOString()}]});
 assert.equal(c.delay(),1010);
 await c.advance(1010);assert.ok(c.nodes.every(n=>n.removed));
 assert.equal(c.ui.markup({text:'Temporary',expires_at:end}),'');
 assert.equal(c.delay(),9000);
});

test('server synchronization corrects ahead and behind clocks before rendering all decorations',()=>{
 for(const skew of [120000,-120000]){
   const c=cosmeticClock(skew),end=new Date(c.now()+60000).toISOString();
   c.themes.sync({server_time:new Date(c.now()).toISOString()});
   assert.match(c.ui.markup({text:'Valid',expires_at:end}),/member-title-badge/);
   assert.match(c.ui.badgeMarkup({key:'taffy',expires_at:end}),/member-icon-badge/);
   assert.match(c.ui.frameAvatar('avatar',{key:'taffy-goggles',expires_at:end}),/avatar-frame-art/);
   assert.equal(c.delay(),60010);
   c.themes.sync({server_time:new Date(c.now()+61000).toISOString()});
   assert.equal(c.ui.markup({text:'Expired',expires_at:end}),'');
   assert.equal(c.ui.badgeMarkup({key:'taffy',expires_at:end}),'');
   assert.equal(c.ui.frameAvatar('avatar',{key:'taffy-goggles',expires_at:end}),'avatar');
 }
});
