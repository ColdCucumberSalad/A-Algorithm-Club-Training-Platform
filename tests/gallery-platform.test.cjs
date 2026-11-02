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
  ctx.communityRequest=async()=>{throw Object.assign(new Error('浏览记录已过期'), {status:400});};
  await ctx.openProblem(42,'expired','luogu');
  assert.equal($('#galleryMore').hidden,false);
  assert.equal($('#galleryMore').textContent,'重新加载题解');
  ctx.communityRequest=original;
  await $('#galleryMore').onclick();
  assert.match(requests[0],/cursor=&platform=luogu$/);
});

function dayContext(){
  const element=()=>({children:[],dataset:{},html:'',append(...nodes){this.children.push(...nodes);},get lastElementChild(){return this.children.at(-1);},insertAdjacentHTML(position,html){this.html+=html;}});
  const ctx={Intl,Date,document:{createElement:element}};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('function galleryUploadDay('),source.indexOf('async function loadShowcase(')),ctx);
  return {ctx,element};
}
test('upload dates use Beijing midnight regardless of browser timezone',()=>{
  const {ctx}=dayContext();
  assert.equal(ctx.galleryUploadDay('2026-11-01T15:59:59Z'),'2026-11-01');
  assert.equal(ctx.galleryUploadDay('2026-11-01T16:00:00Z'),'2026-11-02');
});
test('subsequent pages extend the same day and preserve row order',()=>{
  const {ctx,element}=dayContext(),host=element();
  ctx.appendGalleryDay(host,'2026-11-02T10:00:00Z','A');
  ctx.appendGalleryDay(host,'2026-11-02T09:00:00Z','B');
  ctx.appendGalleryDay(host,'2026-11-01T10:00:00Z','C');
  assert.equal(host.children.length,2);
  assert.equal(host.children[0].lastElementChild.html,'AB');
  assert.equal(host.children[1].dataset.uploadDay,'2026-11-01');
  assert.equal(host.children[0].children[0].textContent,'2026 年 11 月 02 日');
});
test('same-problem solutions from different days append into one list',async()=>{
  const {ctx,$}=setup();
  const host=$('#showcaseGrid');
  host.replaceChildren=()=>{host.innerHTML='';};
  host.insertAdjacentHTML=(position,html)=>{host.innerHTML+=html;};
  ctx.submissionCard=item=>`<article>${item.id}</article>`;
  let count=0;
  ctx.communityRequest=async()=>({problem:{title:'Example',url:'https://qoj.ac/problem/1'},
    submissions:++count===1?[{id:3,submitted_at:'2026-11-02T00:00:00Z'},{id:2,submitted_at:'2026-11-01T00:00:00Z'}]:[{id:1,submitted_at:'2026-10-31T00:00:00Z'}],next:count===1?'next':null});
  await ctx.openProblem(42,1,'luogu');
  await $('#galleryMore').onclick();
  assert.equal(host.innerHTML,'<article>3</article><article>2</article><article>1</article>');
  assert.equal(host.className,'submission-days problem-solutions');
});

test('failed subsequent detail page keeps existing content and retries the same cursor',async()=>{
  const {ctx,$,requests}=setup();
  $('#showcaseGrid').innerHTML='existing-content';
  const original=ctx.communityRequest;
  ctx.communityRequest=async()=>{throw new Error('network unavailable');};
  await ctx.openProblem(42,'page-two','luogu');
  assert.equal($('#showcaseGrid').innerHTML,'existing-content');
  assert.equal($('#galleryLoadError').textContent,'network unavailable');
  assert.equal($('#galleryMore').textContent,'重试加载更多');
  ctx.communityRequest=original;
  await $('#galleryMore').onclick();
  assert.match(requests[0],/cursor=page-two&platform=luogu$/);
  assert.equal($('#galleryLoadError').hidden,true);
});
test('expired subsequent detail page preserves existing content until explicit restart',async()=>{
  const {ctx,$}=setup();
  $('#showcaseGrid').innerHTML='existing-content';
  ctx.communityRequest=async()=>{throw Object.assign(new Error('expired'),{status:400});};
  await ctx.openProblem(42,'expired','luogu');
  assert.equal($('#showcaseGrid').innerHTML,'existing-content');
  assert.equal($('#galleryMore').textContent,'重新加载题解');
});
test('failed subsequent gallery page retains content and retries the same cursor',async()=>{
  const {ctx,$}=setup();
  ctx.galleryQuery=()=>'';
  $('#galleryPlatform').value='luogu';
  $('#showcaseGrid').innerHTML='existing-topics';
  vm.runInContext(source.slice(source.indexOf('async function loadShowcase('),source.indexOf('async function openProblem(')),ctx);
  const requests=[];
  ctx.communityRequest=async url=>{requests.push(url);throw new Error('offline');};
  await ctx.loadShowcase('page-two');
  assert.equal($('#showcaseGrid').innerHTML,'existing-topics');
  assert.equal($('#galleryMore').textContent,'重试加载更多');
  await $('#galleryMore').onclick();
  assert.equal(requests[0],requests[1]);
});
