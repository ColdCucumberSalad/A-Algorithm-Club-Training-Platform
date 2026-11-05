const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({delayed=false}={}){
 let overlay,listener,release,state={badges:[{kind:'badge',key:'garden',name:'Garden'}]};
 const gate=delayed?new Promise(resolve=>release=resolve):null;
 const document={activeElement:{},addEventListener(type,fn){listener=fn},removeEventListener(){listener=null},body:{append(el){el.isConnected=true}},
  createElement(){
   overlay={isConnected:false,hidden:false,controls:[],contains(el){return this.controls.includes(el)},remove(){this.isConnected=false},
    set innerHTML(html){if(this.contains(document.activeElement))document.activeElement={};this.html=html;
     this.controls=[...html.matchAll(/<button\b([^>]*)>/g)].map(([tag,attrs])=>({disabled:/\bdisabled\b/.test(attrs),dataset:attrs.includes('data-equip')?{equip:'0'}:{},
      close:attrs.includes('data-close'),buy:attrs.includes('data-buy'),focus(){document.activeElement=this},addEventListener(type,fn){this.onclick=fn}}));},
    querySelector(selector){return selector==='[data-close]'?this.controls.find(b=>b.close):this.controls.find(b=>b.buy)},
    querySelectorAll(selector){return this.controls.filter(b=>selector==='button'||selector==='button:not(:disabled)'&&!b.disabled||selector==='[data-equip]'&&b.dataset.equip!==undefined)}};
   return overlay;
  }};
 const context={document,console,MemberTitles:{badgeMarkup:()=>'',frameAvatar:x=>x},CosmeticMedia:{safe:()=>false},SpecialThemes:{version:()=>0,isCurrent:()=>true,sync(){},async select(){return state}},
  clubApi:{async request(){if(gate)await gate;return {ok:true,json:async()=>state}}}};
 context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/cosmetic-bundle.js'),'utf8'),context);
 return {open(onPurchase=async()=>false){context.CosmeticBundle.open({item:{id:1,name:'Garden',components:[{kind:'badge',key:'garden'}]},onPurchase});return overlay},
  release:()=>release?.(),focus:()=>document.activeElement,blur(){document.activeElement={}},key(event){listener?.(event)}};
}
test('ownership redraw retains the modal close focus and Tab recaptures escaped focus',async()=>{
 const f=fixture({delayed:true}),overlay=f.open(),old=f.focus();assert.equal(old.close,true);
 f.release();await settle();assert.equal(f.focus().close,true);assert.notEqual(f.focus(),old);
 for(const shiftKey of [false,true]){f.blur();let prevented=false;f.key({key:'Tab',shiftKey,preventDefault(){prevented=true}});
  assert.equal(prevented,true);assert.equal(f.focus(),shiftKey?overlay.controls.at(-1):overlay.controls[0]);}
});
test('equipping redraw preserves the selected control',async()=>{
 const f=fixture(),overlay=f.open();await settle();const equip=overlay.querySelectorAll('[data-equip]')[0];equip.focus();await equip.onclick();
 assert.equal(f.focus().dataset.equip,'0');assert.notEqual(f.focus(),equip);
});
for(const purchased of [false,true])test('hidden bundle yields Escape and Tab to purchase dialogs, purchase='+purchased,async()=>{
 const f=fixture();let finish;const overlay=f.open(()=>new Promise(resolve=>finish=resolve));await settle();
 const buying=overlay.querySelector('[data-buy]').onclick();assert.equal(overlay.hidden,true);
 for(const key of ['Escape','Tab']){let intercepted=false;f.key({key,preventDefault(){intercepted=true},stopImmediatePropagation(){intercepted=true}});assert.equal(intercepted,false);}
 finish(purchased);await buying;assert.equal(overlay.hidden,false);assert.ok(overlay.contains(f.focus()));
 f.key({key:'Escape',preventDefault(){},stopImmediatePropagation(){}});assert.equal(overlay.isConnected,false);
});
test('closing during ownership loading does not recreate the preview or steal focus',async()=>{
 const f=fixture({delayed:true}),overlay=f.open();overlay.querySelector('[data-close]').onclick();f.blur();const focus=f.focus();f.release();await settle();
 assert.equal(overlay.isConnected,false);assert.equal(f.focus(),focus);
});
