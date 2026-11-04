const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
const helper=source.slice(source.indexOf('const memberAvatarSources ='),source.indexOf('\nfunction renderLeaderboard'));

test('rank refreshes reuse stable small version URLs and skip absent avatars',()=>{
  const context={window:{},escapeHtml:value=>String(value).replaceAll('&','&amp;')};
  vm.createContext(context);vm.runInContext(helper,context);
  const render=()=>vm.runInContext("memberAvatar(3,'Alice','leader-avatar','/api/members/3/avatar?size=small&v=one')",context);
  const initial=render();assert.equal(initial,render());assert.match(initial,/size=small/);assert.match(initial,/v=one/);
  assert.doesNotMatch(initial,/Date.now|size=large/);
  assert.doesNotMatch(vm.runInContext("memberAvatar(4,'Bob','leader-avatar',null)",context),/<img/);
  assert.match(vm.runInContext("memberAvatar(5,'Carol')",context),/avatar\?size=small/);
  const replaced=vm.runInContext("memberAvatar(3,'Alice','leader-avatar','/api/members/3/avatar?size=small&v=two')",context);
  assert.match(replaced,/v=two/);assert.notEqual(initial,replaced);
});

test('saving a profile changes only that member image and identical URLs do not reload',()=>{
  let handler,replacements=0;
  function holder(id,src){
    const h={dataset:{avatarMember:String(id)},image:{src,getAttribute:()=>h.image.src,remove(){h.image=null;replacements++;}},
      querySelector:()=>h.image,append:image=>{h.image=image;}};
    return h;
  }
  const own=holder(3,'/small?v=one'),other=holder(4,'/other?v=same');
  const context={window:{addEventListener:(_,fn)=>handler=fn},memberAvatarSources:new Map(),
    document:{querySelectorAll:()=>[own,other],createElement:()=>({getAttribute(){return this.src;},remove(){}})},
    refreshAfterMutation(){},currentView:'dashboard',loadMembersLive(){}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("window.addEventListener('personal-profile-saved'"),source.indexOf('\nasync function loadLiveData')),context);
  handler({detail:{memberId:3,avatar:'/small?v=two'}});
  assert.equal(replacements,1);assert.equal(own.image.src,'/small?v=two');assert.equal(other.image.src,'/other?v=same');
  handler({detail:{memberId:3,avatar:'/small?v=two'}});assert.equal(replacements,1);
});

test('header avatar removes default text on success and restores it on error',()=>{
  const profile=fs.readFileSync(require.resolve('../profile.js'),'utf8');
  function fixture(){
    const holder={children:[],text:'',replaceChildren(image){this.children=[image];this.text='';},
      append(image){this.children.push(image);image.parentElement=this;}};
    Object.defineProperty(holder,'textContent',{get:()=>holder.text,set:value=>{
      holder.children.forEach(image=>image.parentElement=null);holder.children=[];holder.text=value;
    }});
    const context={window:{},entry:{querySelector:selector=>selector==='.profile-avatar'?holder:{}},
      document:{createElement:()=>({})}};
    vm.createContext(context);
    vm.runInContext(profile.slice(profile.indexOf('  function updateHeader('),profile.indexOf('  function message(')),context);
    return {holder,render:()=>vm.runInContext("updateHeader({name:'Alice',avatar_small:'/small?v=one'})",context)};
  }
  const first=fixture();first.render();assert.equal(first.holder.text,'A');
  first.holder.children[0].onload();assert.equal(first.holder.text,'');assert.equal(first.holder.children.length,1);
  const failed=fixture();failed.render();failed.holder.children[0].onerror();
  assert.equal(failed.holder.text,'A');assert.equal(failed.holder.children.length,0);
  const stale=fixture();stale.render();const image=stale.holder.children[0];stale.render();image.onload();
  assert.notEqual(stale.holder.children[0],image);
});
