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
