const {prepare}=require('./activity-fixture.cjs');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');

test('a refreshed historical day replaces cached completed flags and reopens the button',()=>{
  const old={date:'2026-10-23',submitted:true,hasSubmission:true,isMakeup:true,canSubmit:false};
  const current={...old,submitted:false,hasSubmission:false,isMakeup:false,makeupOpen:true,canSubmit:true};
  const entry={classList:{toggle(){}}};
  const context={pulseDays:[old],pulseToday:'2026-11-01',adminTestMode:false,entry,current};
  prepare(context);vm.createContext(context);
  const merge=source.slice(source.indexOf('function updatePulseDay('),source.indexOf('\nasync function refreshActivityLayout'));
  const button=source.slice(source.indexOf('function updateSubmissionEntry('),source.indexOf('\nfunction selectPulseDay'));
  vm.runInContext(merge+button+'\nupdatePulseDay(current);updateSubmissionEntry(entry,pulseDays[0],current.date);',context);
  assert.match(entry.innerHTML,/补交当日记录/);assert.equal(entry.disabled,false);
  context.current={...current,submitted:true,hasSubmission:true,isMakeup:true,canSubmit:false};
  vm.runInContext('updatePulseDay(current);updateSubmissionEntry(entry,pulseDays[0],current.date);',context);
  assert.match(entry.innerHTML,/当日已补签/);assert.equal(entry.disabled,true);
});

test('today returns to its first-submission action after the final submission disappears',()=>{
  const entry={classList:{toggle(){}}};
  const context={entry,day:{submitted:false,hasSubmission:false,canSubmit:true},pulseToday:'2026-11-01',adminTestMode:false};
  prepare(context);vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function updateSubmissionEntry('),source.indexOf('\nfunction selectPulseDay'))+"\nupdateSubmissionEntry(entry,day,pulseToday);",context);
  assert.match(entry.innerHTML,/提交今日记录/);assert.equal(entry.disabled,false);
});

test('a leaderboard request started before deletion cannot overwrite the new solved total',async()=>{
  const pending=[],data={},inflight=new Map();
  const context={rankingData:data,leaderboardInFlight:inflight,rankingKey:(a,b)=>a+':'+b,
    rankingSelection:()=>({scope:'solved',platform:'codeforces'}),renderLeaderboard(){},
    clubApi:{request:()=>new Promise(resolve=>pending.push(resolve))}};
  prepare(context);vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function loadLeaderboard('),source.indexOf('\nasync function refreshAfterMutation')),context);
  const old=vm.runInContext("loadLeaderboard('solved')",context);
  const fresh=vm.runInContext("loadLeaderboard('solved','codeforces',{force:true})",context);
  pending[1]({ok:true,json:async()=>({rows:[{value:0}]})});await fresh;
  pending[0]({ok:true,json:async()=>({rows:[{value:1}]})});await old;
  assert.equal(data['solved:codeforces'][0].value,0);
});

test('rejected corrections bypass overview day locks and never request a makeup ticket',async()=>{
  const entries=new Map();
  const $=key=>{if(!entries.has(key))entries.set(key,{dataset:{}});return entries.get(key);};
  const context={$,pulseToday:'2026-11-01',selectedPulseDate:'2026-10-30',
    pulseDays:[{date:'2026-10-30',submitted:true,isMakeup:false,canSubmit:false,weekId:2}],
    adminTestMode:false,currentSubmissionWeekId:3,completeMakeup:async()=>{throw Error('must not spend ticket');},
    loadDailyChallenges(){},resetSubmissionForm(){},showSubmissionEditor(){},editingSubmission:null,resubmitting:null};
  prepare(context);vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function openModal('),source.indexOf('\nlet submissionScrollState')),context);
  assert.equal(await vm.runInContext("openModal(false,{record_date:'2026-10-30',week_id:2})",context),true);
  assert.equal($('#submissionForm').dataset.recordDate,'2026-10-30');
  assert.equal($('#submissionForm').dataset.makeup,'');
  assert.equal(await vm.runInContext('openModal()',context),undefined);
});

test('the rejected-record action uses record eligibility rather than overview date permissions',async()=>{
  const community=fs.readFileSync(require.resolve('../community.js'),'utf8');
  const record={id:8,can_resubmit:true,record_date:'2026-10-30',week_id:2,problem_url:'x',parts:[]};
  const entries=new Map(),calls=[];
  const context={ownRecords:new Map([[8,record]]),$:key=>{if(!entries.has(key))entries.set(key,{dataset:{}});return entries.get(key);},
    openModal:async(...args)=>{calls.push(args);return true;},showToast(){},uiProblemTitle:x=>x,
    setSubmissionCodeDraft(){},renderSubmissionDraftBlog(){},startSubmissionDraft(){},resubmitting:null};
  prepare(context);vm.createContext(context);
  vm.runInContext(community.slice(community.indexOf('async function beginResubmit('),community.indexOf("\ndocument.addEventListener('DOMContentLoaded'",community.indexOf('async function beginResubmit('))),context);
  assert.equal(await vm.runInContext('beginResubmit(8)',context),true);
  assert.equal(calls[0][0],false);assert.equal(calls[0][1],record);
  assert.equal(context.resubmitting,8);
});

test('normal editing uses can_edit while rejected resubmission keeps its separate permission',async()=>{
  const community=fs.readFileSync(require.resolve('../community.js'),'utf8');
  for(const scenario of [
    {can_edit:true,can_resubmit:false,edit:true,allowed:true},
    {can_edit:false,can_resubmit:true,edit:true,allowed:false},
    {can_edit:true,can_resubmit:false,edit:false,allowed:false},
    {can_edit:false,can_resubmit:true,edit:false,allowed:true},
    {can_edit:false,can_resubmit:false,edit:true,allowed:false},
  ]){
    const record={id:8,...scenario,record_date:'2026-10-30',week_id:2,problem_url:'x',parts:[]};
    const entries=new Map(),calls=[],messages=[];
    const context={ownRecords:new Map([[8,record]]),$:key=>{if(!entries.has(key))entries.set(key,{dataset:{}});return entries.get(key);},
      openModal:async(...args)=>{calls.push(args);return true;},showToast:message=>messages.push(message),uiProblemTitle:x=>x,
      setSubmissionCodeDraft(){},renderSubmissionDraftBlog(){},startSubmissionDraft(){},resubmitting:null,editingSubmission:null,
      captureEditReturn:()=>({}),closeReview(){},restoreEditReturn(){},submissionEditReturnState:null};
    prepare(context);vm.createContext(context);
    vm.runInContext(community.slice(community.indexOf('async function beginResubmit('),community.indexOf("\ndocument.addEventListener('DOMContentLoaded'",community.indexOf('async function beginResubmit('))),context);
    vm.runInContext(community.slice(community.indexOf('async function editOwnSubmission('),community.indexOf('\nfunction openTipDialog')),context);
    await vm.runInContext(scenario.edit?'editOwnSubmission(8)':'beginResubmit(8)',context);
    assert.equal(calls.length,scenario.allowed?1:0,JSON.stringify(scenario));
    if(scenario.allowed){
      assert.equal(messages.length,0);
      assert.equal(context.resubmitting,scenario.edit?null:8);
      assert.equal(context.editingSubmission,scenario.edit?8:null);
      if(scenario.edit){
        assert.equal(context.$('#proofImage').required,false);
        assert.equal(context.$('#cancelSubmissionEdit').hidden,false);
        assert.match(context.$('.form-note span:last-child').textContent,/编辑原提交/);
      }
    }
  }
});
