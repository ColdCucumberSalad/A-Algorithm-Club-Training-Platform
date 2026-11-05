const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync(require.resolve('../app.js'),'utf8');
const handler=app.slice(app.indexOf("window.addEventListener('club:cosmetics-expired'"));
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({kind='theme',tab='shop',active=true}={}){
 let now=Date.parse('2026-11-04T15:30:00Z'),timer,preview,listener;const end=now+1000,calls=[];
 class Clock extends Date{static now(){return now;}}
 const previewButton={dataset:{previewCosmetic:'1',previewTitle:'1'}};
 const container={dataset:{shopTab:tab,shopCategory:'decorations'},innerHTML:'',
   querySelector:selector=>selector==='.shop-tabs'?{querySelectorAll:()=>[]}:null,
   querySelectorAll:selector=>selector===(kind==='title'?'[data-preview-title]':'[data-preview-cosmetic]')?[previewButton]:[]};
 const window={addEventListener(type,fn){if(type==='club:cosmetics-expired')listener=fn},dispatchEvent(event){if(event.type==='club:cosmetics-expired')listener()},
   CosmeticBundle:{open(options){preview=options}},ShopImages:{mount(){}},CosmeticShop:{openTitle(options){preview=options}},clubApi:{async request(url){calls.push(url);const owned=now<end;
     const item={id:1,item_id:1,item_type:kind,name:'Temporary cosmetic',item_name:'Temporary cosmetic',description:'',price:3,stock:-1,cosmetic_key:'taffy',title_definition:{text:'Title'},title_owned:kind==='title'&&owned,cosmetic_owned:kind==='theme'&&owned,purchase_blocked:false,expires_at:owned?new Date(end).toISOString():null};
     const data=url.includes('/balance')?{balance:10,can_purchase:true}:url.includes('/shop/items')?{items:[item]}:url.includes('/inventory')?{inventory:owned?[item]:[]}:{themes:owned?[{key:'taffy',expires_at:new Date(end).toISOString()}]:[],server_time:new Date(now).toISOString()};
     return {ok:true,json:async()=>data};}}};
 const document={documentElement:{dataset:{}},addEventListener(){},querySelector(){return null},getElementById:id=>id==='rbcshopView'?container:null};
 const context={window,document,Date:Clock,Event,console,setTimeout(fn){timer=fn;return 1},clearTimeout(){},currentView:active?'rbcshop':'dashboard',refreshCosmeticRankings:()=>Promise.resolve()};
 vm.createContext(context);
 for(const file of ['static/special-themes.js','currency.js'])vm.runInContext(fs.readFileSync(require.resolve('../'+file),'utf8'),context);
 vm.runInContext(handler,context);
 const term=new Date(end).toISOString();window.SpecialThemes.sync({server_time:new Date(now).toISOString(),themes:kind==='theme'?[{key:'taffy',expires_at:term}]:[],title_expirations:kind==='title'?[term]:[]});
 return {container,calls,render:async()=>{await window.CurrencyModule.init();return window.CurrencyModule.renderShopView(container)},preview:()=>{previewButton.onclick();return preview},expire:async()=>{now=end+10;await timer();await settle();}};
}
for(const kind of ['title','theme'])test(kind+' expiry reloads ownership and lets the newly opened detail offer a purchase',async()=>{
 const f=fixture({kind});await f.render();assert.match(f.container.innerHTML,/续期/);assert.equal(Boolean(f.preview().owned),true);
 await f.expire();assert.equal(f.calls.filter(url=>url.includes('/shop/items')).length,2);
 assert.doesNotMatch(f.container.innerHTML,/已拥有/);assert.equal(Boolean(f.preview().owned),false);
 assert.equal(f.preview().item.purchase_blocked,false);assert.doesNotMatch(f.container.innerHTML,/<button[^>]*shop-buy-btn[^>]*disabled/);
 assert.equal(f.container.dataset.shopCategory,'decorations');
});
test('the active backpack refreshes when an entitlement expires and preserves its selected tab',async()=>{
 const f=fixture({tab:'inventory'});await f.render();assert.match(f.container.innerHTML,/Temporary cosmetic/);
 await f.expire();assert.equal(f.calls.filter(url=>url.includes('/inventory')).length,2);
 assert.doesNotMatch(f.container.innerHTML,/Temporary cosmetic/);assert.equal(f.container.dataset.shopTab,'inventory');
});
test('expiry does not reload a hidden shop',async()=>{
 const f=fixture({active:false});await f.render();await f.expire();
 assert.equal(f.calls.filter(url=>url.includes('/shop/items')).length,1);
});
