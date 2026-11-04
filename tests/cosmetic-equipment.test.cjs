const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({skew=0,serverTime=Date.now(),realClock=false,delayed=false}={}){
 let serverNow=serverTime;
 class Clock extends Date{static now(){return serverNow+skew;}}
 let overlay,state={},fail=false,calls=[],listeners={},release;
 const pending=delayed?new Promise(resolve=>release=resolve):null;
 const element=kind=>({kind,focus(){document.activeElement=this},disabled:false,textContent:'',dataset:kind==='ranking'||kind==='profile'?{cosmeticContext:kind}:{}});
 const document={documentElement:{dataset:{}},activeElement:null,addEventListener(type,fn){listeners[type]=fn},removeEventListener(type){delete listeners[type]},
   querySelector(selector){return selector==='.cosmetic-preview-overlay'&&overlay?.isConnected?overlay:null},
   createElement(){
     const status=element('status');
     overlay={isConnected:false,html:'',controls:[],contains(el){return this.controls.includes(el)},remove(){this.isConnected=false},
       set innerHTML(value){if(this.contains(document.activeElement))document.activeElement=null;this.html=value;this.controls=['close','ranking','profile','action'].map(element);this.controls[3].disabled=/<button[^>]*data-cosmetic-action disabled/.test(value)},
       querySelector(selector){return selector==='[data-cosmetic-action]'?this.controls[3]:selector==='[data-cosmetic-close]'?this.controls[0]:selector.includes('data-cosmetic-context=')?this.controls.find(c=>selector.includes(c.dataset.cosmeticContext)&&c.dataset.cosmeticContext):status},querySelectorAll(selector){return selector==='[data-cosmetic-context]'?this.controls.slice(1,3):selector==='button:not(:disabled)'?this.controls.filter(c=>!c.disabled):this.controls}};
     return overlay;
   },body:{append(el){el.isConnected=true}}};
 const context={document,Date:Clock,Event,setTimeout(){return 1},clearTimeout(){},window:{dispatchEvent(){},MemberTitles:{frameAvatar:x=>x,badgeMarkup:()=>'',markup:()=>''},SpecialThemes:{sync(){},async select(kind,key){state={...state,active_theme:kind==='theme'?key:state.active_theme,badge:kind==='badge'?{key}:state.badge,avatar_frame:kind==='frame'?{key}:state.avatar_frame};}},
 clubApi:{async request(url,options){calls.push({url,options});if(pending)await pending;if(fail)throw Error('offline');if(options?.method==='POST')state={titles:[{text:JSON.parse(options.body).title}]};return {ok:true,json:async()=>state}}}}};
 vm.createContext(context);
 if(realClock)vm.runInContext(fs.readFileSync(require.resolve('../static/special-themes.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(require.resolve('../static/cosmetic-shop.js'),'utf8'),context);
 return {release:()=>release?.(),focus:()=>document.activeElement,blur(){document.activeElement={}},key(event){listeners.keydown(event)},advance(ms){serverNow+=ms},setState(value){state=value},fail(value){fail=value},calls,
   open(item){context.window.CosmeticShop.openTitle({item,owned:true});return overlay},
   action:()=>overlay.querySelector('[data-cosmetic-action]'),html:()=>overlay.html};
}
const items=[
 {item_type:'theme',cosmetic_key:'taffy',selected:{active_theme:'taffy'},label:'已启用'},
 {item_type:'badge',cosmetic_key:'taffy',selected:{badge:{key:'taffy'}},label:'已佩戴'},
 {item_type:'frame',cosmetic_key:'taffy-goggles',selected:{avatar_frame:{key:'taffy-goggles'}},label:'已佩戴'},
 {item_type:'title',title_definition:{text:'Title'},selected:{titles:[{text:'Title'}]},label:'已佩戴'}
];
for(const item of items){
 test(item.item_type+' reads the saved selection every time the detail opens',async()=>{
   const f=fixture();f.setState(item.selected);f.open(item);
   assert.match(f.html(),/读取状态/);assert.equal(f.action().disabled,true);
   await settle();assert.match(f.html(),new RegExp('>'+item.label+'</button>'));assert.equal(f.action().disabled,true);
   await f.action().onclick({currentTarget:f.action()});assert.equal(f.calls.length,1);
   f.setState({});f.open(item);await settle();assert.match(f.html(),/立即启用|立即佩戴/);assert.equal(f.action().disabled,false);
   await f.action().onclick({currentTarget:f.action()});assert.match(f.html(),new RegExp('>'+item.label+'</button>'));
   f.open(item);await settle();assert.match(f.html(),new RegExp('>'+item.label+'</button>'));assert.equal(f.action().disabled,true);
 });
}
test('failed selection lookup can be retried without equipping or purchasing',async()=>{
 const f=fixture();f.fail(true);f.open(items[0]);await settle();assert.match(f.html(),/重试读取状态/);assert.equal(f.action().disabled,false);
 f.fail(false);f.setState(items[0].selected);await f.action().onclick({currentTarget:f.action()});
 assert.match(f.html(),/>已启用<\/button>/);assert.ok(f.calls.every(call=>!call.options));
});
test('closing while the saved selection loads leaves the dialog closed',async()=>{
 const f=fixture();f.setState(items[0].selected);const overlay=f.open(items[0]);overlay.querySelector('[data-cosmetic-close]').onclick();await settle();assert.equal(overlay.isConnected,false);
});

for(const item of items)for(const skew of [120000,-120000])test(item.item_type+' expiry gate follows server time with clock skew '+skew,async()=>{
 const start=Date.parse('2026-11-04T14:00:00Z'),end=new Date(start+60000).toISOString();
 const f=fixture({skew,serverTime:start,realClock:true});
 const data={server_time:new Date(start).toISOString(),themes:[{key:'taffy',expires_at:end}]};
 f.setState(item.item_type==='title'?{titles:[],cosmetics:data}:data);
 const product={...item,expires_at:end};f.open(product);await settle();
 assert.match(f.html(),/立即启用|立即佩戴/);assert.doesNotMatch(f.html(),/已过期/);assert.equal(f.action().disabled,false);
 f.advance(60000);const expiredState={...data,server_time:end};
 f.setState(item.item_type==='title'?{titles:[],cosmetics:expiredState}:expiredState);
 f.open(product);await settle();assert.match(f.html(),/>已过期<\/button>/);assert.equal(f.action().disabled,true);
});

test('owned-state redraws preserve focus during loading and after completion',async()=>{
 const f=fixture({delayed:true});f.setState(items[0].selected);const overlay=f.open(items[0]);
 assert.equal(f.focus().kind,'close');
 await overlay.controls[2].onclick();assert.equal(f.focus().kind,'profile');
 const before=f.focus();f.release();await settle();assert.equal(f.focus().kind,'profile');assert.notEqual(f.focus(),before);
});
test('Tab in either direction recaptures focus that escapes the modal',async()=>{
 const f=fixture();f.open(items[0]);await settle();
 for(const shiftKey of [false,true]){
   f.blur();let prevented=false;
   f.key({key:'Tab',shiftKey,preventDefault(){prevented=true}});
   assert.equal(prevented,true);assert.equal(f.focus().kind,shiftKey?'action':'close');
 }
});
test('retrying a failed lookup restores focus when the action becomes disabled',async()=>{
 const f=fixture();f.fail(true);f.open(items[0]);await settle();f.action().focus();
 f.fail(false);f.setState(items[0].selected);await f.action().onclick({currentTarget:f.action()});
 assert.equal(f.focus().kind,'close');assert.equal(f.action().disabled,true);
});
