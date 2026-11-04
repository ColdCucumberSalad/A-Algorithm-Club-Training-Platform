const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync(require.resolve('../app.js'),'utf8');
const profile=fs.readFileSync(require.resolve('../profile.js'),'utf8');
const helper=app.slice(app.indexOf('function refreshCosmeticRankings('),app.indexOf('async function refreshAfterMutation('));
const key=(scope,platform,period)=>scope==='rating'?scope+':'+platform:scope==='solved'?scope+':'+period:scope;
const dashboards=[{scope:'checkin'},{scope:'rating',platform:'codeforces'},{scope:'solved',period:'semester'},{scope:'wealth'}];
for(const selected of [{scope:'rating',platform:'atcoder'},{scope:'solved',period:'all'},{scope:'wealth'}]){
 for(const kind of ['badge','frame'])test(kind+' changes refresh the underlying '+key(selected.scope,selected.platform,selected.period)+' leaderboard',async()=>{
   const calls=[],errors=[],elements=new Map(),buttons={badge:{dataset:{badgeKey:'taffy'}},frame:{dataset:{frameKey:'taffy-goggles'}}};
   const titles={frameElement(){},list:()=>'',markup:()=>'',badgeMarkup:()=>'',frameAvatar:()=>'',badgeAssets:{taffy:{}}};
   function element(selector){if(!elements.has(selector))elements.set(selector,{querySelectorAll:()=>selector==='#badgeWardrobe'?[buttons.badge]:selector==='#frameWardrobe'?[buttons.frame]:[]});return elements.get(selector);}
   const data={name:'User',titles:[],awarded_titles:[],cosmetics:{badges:[{key:'taffy'}],frames:[{key:'taffy-goggles'}]}};
   const context={data,window:{MemberTitles:titles},MemberTitles:titles,page:{querySelector:element},escape:x=>x,updateHeader(){},message:(text,bad)=>{if(bad)errors.push(text)},
     SpecialThemes:{async select(){return {badge:{key:'taffy'},avatar_frame:{key:'taffy-goggles'},...data.cosmetics}}},
     rankingKey:key,rankingSelection:target=>target==='#leaderboardListFull'?selected:dashboards[['#leaderboardList','#leaderboardRatingList','#leaderboardSolvedList','#leaderboardWealthList'].indexOf(target)],
     loadLeaderboard:(scope,platform,options)=>{calls.push({scope,platform,...options});return Promise.resolve(true)}};
   vm.createContext(context);vm.runInContext(helper+profile.slice(profile.indexOf('  function renderIdentity()'),profile.indexOf('  function buildPage()'))+';renderIdentity();',context);
   await buttons[kind].onclick();
   assert.deepEqual(errors,[]);assert.ok(calls.some(c=>key(c.scope,c.platform,c.period)===key(selected.scope,selected.platform,selected.period)));
   assert.ok(calls.every(c=>c.force));assert.equal(new Set(calls.map(c=>key(c.scope,c.platform,c.period))).size,calls.length);
 });
}
test('cosmetic refresh supersedes an in-flight request with the old appearance',async()=>{
 const selected={scope:'rating',platform:'atcoder',period:'semester'},pending=[],data={},renders=[];
 const context={rankingData:data,leaderboardInFlight:new Map(),rankingKey:key,rankingSelection:()=>selected,
   renderLeaderboard:(scope,target)=>renders.push(target),clubApi:{request:()=>new Promise(resolve=>pending.push(resolve))}};
 vm.createContext(context);vm.runInContext(app.slice(app.indexOf('async function loadLeaderboard('),app.indexOf('async function refreshAfterMutation(')),context);
 const old=vm.runInContext("loadLeaderboard('rating','atcoder')",context);
 const fresh=vm.runInContext('refreshCosmeticRankings()',context);
 assert.equal(pending.length,2);
 pending[1]({ok:true,json:async()=>({rows:[{avatar_frame:{key:'new'}}]})});await fresh;
 pending[0]({ok:true,json:async()=>({rows:[{avatar_frame:{key:'old'}}]})});await old;
 assert.equal(data['rating:atcoder'][0].avatar_frame.key,'new');assert.ok(renders.includes('#leaderboardListFull'));
});
