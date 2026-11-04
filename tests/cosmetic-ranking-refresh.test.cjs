const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync(require.resolve('../app.js'),'utf8');
const profile=fs.readFileSync(require.resolve('../profile.js'),'utf8');
const helper=app.slice(app.indexOf('function refreshCosmeticRankings('),app.indexOf('async function refreshAfterMutation('));
const key=(scope,platform,period)=>scope==='rating'?scope+':'+platform:scope==='solved'?scope+':'+period:scope;
const dashboards=[{scope:'checkin'},{scope:'rating',platform:'codeforces'},{scope:'solved',period:'semester'},{scope:'wealth'}];
for(const selected of [{scope:'rating',platform:'atcoder'},{scope:'solved',period:'all'},{scope:'wealth'},{scope:'checkin',view:'members'}]){
 for(const kind of ['badge','frame'])test(kind+' changes refresh the underlying '+key(selected.scope,selected.platform,selected.period)+' leaderboard',async()=>{
   let rosterRefreshes=0;const calls=[],errors=[],elements=new Map(),buttons={badge:{dataset:{badgeKey:'taffy'}},frame:{dataset:{frameKey:'taffy-goggles'}}};
   const titles={frameElement(){},list:()=>'',markup:()=>'',badgeMarkup:()=>'',frameAvatar:()=>'',badgeAssets:{taffy:{}}};
   function element(selector){if(!elements.has(selector))elements.set(selector,{querySelectorAll:()=>selector==='#badgeWardrobe'?[buttons.badge]:selector==='#frameWardrobe'?[buttons.frame]:[]});return elements.get(selector);}
   const data={name:'User',titles:[],awarded_titles:[],cosmetics:{badges:[{key:'taffy'}],frames:[{key:'taffy-goggles'}]}};
   const context={currentView:selected.view||'leaderboard',loadMembersLive:async()=>{rosterRefreshes++},data,window:{MemberTitles:titles},MemberTitles:titles,page:{querySelector:element},escape:x=>x,updateHeader(){},message:(text,bad)=>{if(bad)errors.push(text)},
     SpecialThemes:{async select(){return {badge:{key:'taffy'},avatar_frame:{key:'taffy-goggles'},...data.cosmetics}}},
     rankingKey:key,rankingSelection:target=>target==='#leaderboardListFull'?selected:dashboards[['#leaderboardList','#leaderboardRatingList','#leaderboardSolvedList','#leaderboardWealthList'].indexOf(target)],
     loadLeaderboard:(scope,platform,options)=>{calls.push({scope,platform,...options});return Promise.resolve(true)}};
   vm.createContext(context);vm.runInContext(helper+profile.slice(profile.indexOf('  function renderIdentity()'),profile.indexOf('  function buildPage()'))+';renderIdentity();',context);
   await buttons[kind].onclick();
   assert.equal(rosterRefreshes,selected.view==='members'?1:0);assert.deepEqual(errors,[]);assert.ok(calls.some(c=>key(c.scope,c.platform,c.period)===key(selected.scope,selected.platform,selected.period)));
   assert.ok(calls.every(c=>c.force));assert.equal(new Set(calls.map(c=>key(c.scope,c.platform,c.period))).size,calls.length);
 });
}
test('cosmetic refresh supersedes an in-flight request with the old appearance',async()=>{
 const selected={scope:'rating',platform:'atcoder',period:'semester'},pending=[],data={},renders=[];
 const context={currentView:'leaderboard',rankingData:data,leaderboardInFlight:new Map(),rankingKey:key,rankingSelection:()=>selected,
   renderLeaderboard:(scope,target)=>renders.push(target),clubApi:{request:()=>new Promise(resolve=>pending.push(resolve))}};
 vm.createContext(context);vm.runInContext(app.slice(app.indexOf('async function loadLeaderboard('),app.indexOf('async function refreshAfterMutation(')),context);
 const old=vm.runInContext("loadLeaderboard('rating','atcoder')",context);
 const fresh=vm.runInContext('refreshCosmeticRankings()',context);
 assert.equal(pending.length,2);
 pending[1]({ok:true,json:async()=>({rows:[{avatar_frame:{key:'new'}}]})});await fresh;
 pending[0]({ok:true,json:async()=>({rows:[{avatar_frame:{key:'old'}}]})});await old;
 assert.equal(data['rating:atcoder'][0].avatar_frame.key,'new');assert.ok(renders.includes('#leaderboardListFull'));
});

for(const frame of [{key:'taffy-goggles'},null])test('cosmetic changes rebuild the visible roster with frame '+(frame?.key||'removed'),async()=>{
 const grid={innerHTML:''},requests=[],selected={scope:'checkin'};
 const context={window:{},currentView:'members',membersRequestVersion:0,$:()=>grid,$$:()=>[],escapeHtml:String,uiMemberName:x=>x,
   rankingKey:key,rankingSelection:()=>selected,loadLeaderboard:async()=>true,
   clubApi:{async request(url){requests.push(url);return {ok:true,json:async()=>({members:[{id:1,name:'Alice',role:'member',avatar:null,avatar_frame:frame,submissions:0,score:0}]})}}}};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync(require.resolve('../static/member-titles.js'),'utf8'),context);
 context.window.MemberTitles.rememberFrames([{id:1,avatar_frame:frame?null:{key:'taffy-goggles'}}]);
 vm.runInContext(app.slice(app.indexOf('const memberAvatarSources ='),app.indexOf('function renderLeaderboard('))+app.slice(app.indexOf('async function loadMembersLive('),app.indexOf('clearStaticPreview(); loadLiveData();'))+helper,context);
 await vm.runInContext('refreshCosmeticRankings()',context);
 assert.deepEqual(requests,['/api/members']);assert.match(grid.innerHTML,/Alice/);
 assert.equal(grid.innerHTML.includes('avatar-frame-art'),Boolean(frame));
 assert.equal(context.window.MemberTitles.frameFor(1)?.key,frame?.key);
});
