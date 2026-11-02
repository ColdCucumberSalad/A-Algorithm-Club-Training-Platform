const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../community.js'),'utf8');
function setup(){
  const nodes=new Map();
  const $=selector=>{if(!nodes.has(selector))nodes.set(selector,{hidden:false,textContent:'',innerHTML:'',closest(){return this;},removeAttribute(){},replaceChildren(){},insertAdjacentHTML(){}});return nodes.get(selector);};
  const requests=[];
  const ctx={$,galleryDetailPlatform:'',galleryProblem:null,galleryRequest:0,encodeURIComponent,
    communityRequest:async url=>{requests.push(url);return {problem:{title:'Example',url:'https://qoj.ac/problem/1'},submissions:[],next:'snapshot-token'};},
    uiProblemTitle:x=>x,submissionCard:()=>'',renderSubmissionBlogs(){},escapeHtml:x=>x};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function openProblem('),source.indexOf('async function loadAdminQueue(')),ctx);
  return {ctx,$,requests};
}
test('detail keeps its platform on subsequent snapshot pages and can switch to all platforms',async()=>{
  const {ctx,$,requests}=setup();
  await ctx.openProblem(42,1,'luogu');
  assert.match(requests[0],/platform=luogu$/);
  assert.equal($('#problemAllPlatforms').hidden,false);
  await $('#galleryMore').onclick();
  assert.match(requests[1],/cursor=snapshot-token&platform=luogu$/);
  await ctx.openProblem(42,1,'');
  assert.match(requests[2],/cursor=&platform=$/);
  assert.equal($('#problemAllPlatforms').hidden,true);
});
test('expired detail snapshot offers restart preserving its platform',async()=>{
  const {ctx,$,requests}=setup();
  const original=ctx.communityRequest;
  ctx.communityRequest=async()=>{throw new Error('浏览记录已过期');};
  await ctx.openProblem(42,'expired','luogu');
  assert.equal($('#galleryMore').hidden,false);
  assert.equal($('#galleryMore').textContent,'重新加载题解');
  ctx.communityRequest=original;
  await $('#galleryMore').onclick();
  assert.match(requests[0],/cursor=&platform=luogu$/);
});
