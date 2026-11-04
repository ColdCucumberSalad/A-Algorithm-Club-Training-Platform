const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
 let overlay,state={},fail=false,calls=[];
 const element=()=>({focus(){},disabled:false,textContent:''});
 const document={activeElement:null,addEventListener(){},removeEventListener(){},
   querySelector(selector){return selector==='.cosmetic-preview-overlay'&&overlay?.isConnected?overlay:null},
   createElement(){
     const action=element(),close=element(),status=element();
     overlay={isConnected:false,html:'',remove(){this.isConnected=false},
       set innerHTML(value){this.html=value;action.disabled=/<button[^>]*data-cosmetic-action disabled/.test(value)},
       querySelector(selector){return selector==='[data-cosmetic-action]'?action:selector==='[data-cosmetic-close]'?close:status},querySelectorAll(){return []}};
     return overlay;
   },body:{append(el){el.isConnected=true}}};
 const context={document,window:{MemberTitles:{frameAvatar:x=>x,badgeMarkup:()=>'',markup:()=>''},SpecialThemes:{sync(){},async select(kind,key){state={...state,active_theme:kind==='theme'?key:state.active_theme,badge:kind==='badge'?{key}:state.badge,avatar_frame:kind==='frame'?{key}:state.avatar_frame};}},
 clubApi:{async request(url,options){calls.push({url,options});if(fail)throw Error('offline');if(options?.method==='POST')state={titles:[{text:JSON.parse(options.body).title}]};return {ok:true,json:async()=>state}}}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/cosmetic-shop.js'),'utf8'),context);
 return {setState(value){state=value},fail(value){fail=value},calls,
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
