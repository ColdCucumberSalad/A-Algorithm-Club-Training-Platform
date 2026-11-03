const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');

test('solved period defaults to semester and has separate cache keys',()=>{
  const context={document:{querySelector:()=>null}};vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('const rankingKey ='),source.indexOf('\nconst pageTitles')),context);
  assert.equal(vm.runInContext("rankingSelection('#list').period",context),'semester');
  assert.equal(vm.runInContext("rankingKey('solved')",context),'solved:semester');
  assert.equal(vm.runInContext("rankingKey('solved','codeforces','all')",context),'solved:all');
  assert.equal(vm.runInContext("rankingKey('rating','atcoder','all')",context),'rating:atcoder');
});

test('a delayed semester response cannot replace a currently selected total board',async()=>{
  const pending=[],data={},requests=new Map(),renders=[];
  const context={rankingData:data,leaderboardInFlight:requests,
    rankingKey:(scope,platform,period='semester')=>`${scope}:${period}`,
    rankingSelection:target=>({scope:target==='#leaderboardRatingList'?'rating':target==='#leaderboardWealthList'?'wealth':'solved',platform:'codeforces',period:target==='#leaderboardSolvedList'?'semester':'all'}),
    renderLeaderboard:(scope,target)=>renders.push(target),
    clubApi:{request:url=>new Promise(resolve=>pending.push({url,resolve}))}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function loadLeaderboard('),source.indexOf('\nasync function refreshAfterMutation')),context);
  const term=vm.runInContext("loadLeaderboard('solved')",context);
  const all=vm.runInContext("loadLeaderboard('solved','codeforces',{period:'all'})",context);
  assert.match(pending[0].url,/period=semester/);assert.match(pending[1].url,/period=all/);
  pending[1].resolve({ok:true,json:async()=>({rows:[{value:20}]})});await all;
  pending[0].resolve({ok:true,json:async()=>({rows:[{value:3}]})});await term;
  assert.equal(renders.length,3);
  assert.deepEqual(renders,['#leaderboardList','#leaderboardListFull','#leaderboardSolvedList']);
  assert.equal(data['solved:all'][0].value,20);assert.equal(data['solved:semester'][0].value,3);
});

test('heatmap always uses dated solved counts and explains unknown dates',()=>{
  const nodes=new Map(),calls=[];
  const $=selector=>{
    if(!nodes.has(selector))nodes.set(selector,{value:'month',dataset:{},textContent:'',hidden:false,setAttribute(name,value){this[name]=value;}});
    return nodes.get(selector);
  };
  const context={$,
    activityPayload:{end:'2026-11-01',today:'2026-11-01',days:[],ac:{undated:42}},
    renderActivityMonths:(days,metric,unit)=>{calls.push([metric,unit]);return '';},
    wireActivityHeatScroll(){},selectedPulseDate:'2026-11-01',updatePulseDay(){},selectPulseDay(){}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function renderTrainingActivity('),source.indexOf('\nasync function loadTrainingActivity')),context);
  vm.runInContext('renderTrainingActivity()',context);
  assert.deepEqual(calls,[['ac','题']]);
  assert.equal($('#activityNote').hidden,false);
  assert.match($('#activityNote').textContent,/42.*日期未知/);
  const html=fs.readFileSync(require.resolve('../index.html'),'utf8');
  assert.doesNotMatch(html,/activityMetric/);
});

test('a newly completed baseline refreshes ranking and heatmap once while polling stays quiet',()=>{
  const profile=fs.readFileSync(require.resolve('../profile.js'),'utf8'),events=[];
  const context={data:{platforms:{},bindings:[{platform:'codeforces'}]},solvedBaselineSignature:null,
    page:{querySelector:()=>({})},window:{dispatchEvent:event=>events.push(event.type)},Event:class{constructor(type){this.type=type;}}};
  vm.createContext(context);
  vm.runInContext(profile.slice(profile.indexOf('  function renderBindings('),profile.indexOf('\n  async function act(')),context);
  vm.runInContext('renderBindings();renderBindings()',context);
  assert.equal(events.length,0);
  context.data.bindings[0].solved_baseline={captured_at:'2026-11-01T10:00:00Z'};
  vm.runInContext('renderBindings();renderBindings()',context);
  assert.deepEqual(events,['platform-solved-updated']);
});
