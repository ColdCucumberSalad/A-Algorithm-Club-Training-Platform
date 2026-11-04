const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const profile=fs.readFileSync(require.resolve('../profile.js'),'utf8');
function fixture(){
 let finish,listener,renders=0;const avatar={frame:{key:'old'}},data={name:'Alice',avatar_frame:{key:'old'}},name={};
 const context={data,page:{},entry:{querySelector:selector=>selector==='strong'?name:avatar},renderIdentity(){renders++},
   request:()=>new Promise(resolve=>finish=resolve),Event,setTimeout(){return 1},clearTimeout(){},
   document:{documentElement:{dataset:{}},addEventListener(){},querySelector(){return null}},
   window:{addEventListener(type,fn){listener=fn},dispatchEvent(){},MemberTitles:{frameElement:(el,frame)=>el.frame=frame},
     clubApi:{async request(url,options){const {kind,key}=JSON.parse(options.body);return {ok:true,json:async()=>({themes:[{key:'taffy'}],avatar_frame:kind==='frame'&&key?{key}:null})}}}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/special-themes.js'),'utf8'),context);
 vm.runInContext(profile.slice(profile.indexOf('  function updateHeader('),profile.indexOf('  function message('))+profile.slice(profile.indexOf("  window.addEventListener('club:cosmetics-expired'"),profile.indexOf('  window.PersonalProfile =')),context);
 return {data,avatar,context,themes:context.window.SpecialThemes,start:()=>listener(),finish:value=>finish(value),renders:()=>renders,frame:frame=>{context.frame=frame;vm.runInContext('updateFrame(frame)',context)}};
}
for(const key of ['taffy-goggles',''])test('profile expiry response cannot undo a newer frame choice '+(key||'none'),async()=>{
 const f=fixture(),pending=f.start();
 const chosen=await f.themes.select('frame',key);f.frame(chosen.avatar_frame);
 f.finish({name:'Alice',avatar_frame:{key:'old'}});await pending;
 assert.equal(f.avatar.frame?.key,key||undefined);assert.equal(f.data.avatar_frame?.key,key||undefined);assert.equal(f.renders(),0);
});
test('profile expiry response is applied when no newer selection occurred',async()=>{
 const f=fixture(),pending=f.start();f.finish({name:'Alice',avatar_frame:null});await pending;
 assert.equal(f.avatar.frame,null);assert.equal(f.context.data.avatar_frame,null);assert.equal(f.renders(),1);
});
test('a newer title selection also invalidates an older profile expiry snapshot',async()=>{
 const f=fixture(),pending=f.start();f.themes.invalidate();f.data.titles=[{text:'New title'}];
 f.finish({name:'Alice',avatar_frame:null,titles:[]});await pending;
 assert.equal(f.data.titles[0].text,'New title');assert.equal(f.renders(),0);
});
