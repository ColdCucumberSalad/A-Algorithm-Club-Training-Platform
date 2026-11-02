const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../community.js'),'utf8');
const start=source.indexOf('async function confirmSubmissionReversal(');
const code=source.slice(start,source.indexOf('\nconst showcaseRecords',start));

function fixture(preview,confirmed=true){
  const dialogs=[];
  const c={communityRequest:async()=>preview,window:{clubDialog:{confirm:async options=>{dialogs.push(options);return confirmed;}}}};
  vm.createContext(c);vm.runInContext(code,c);
  return {dialogs,run:(action='delete',options={})=>vm.runInContext(`confirmSubmissionReversal(7,'${action}',${JSON.stringify({...options,alwaysConfirm:action==='delete'})})`,c)};
}

test('deletion confirmation names each reclaimed item and original-price refund',async()=>{
  const f=fixture({items:[{name:'会徽钥匙扣',quantity:1,refund:10}],reward_reversal:12,balance_after:0,token:'signed'});
  assert.equal((await f.run()).token,'signed');
  assert.match(f.dialogs[0].text,/该操作会导致“会徽钥匙扣”被回收/);
  assert.match(f.dialogs[0].text,/返还 10 Coins/);
  assert.equal('html' in f.dialogs[0],false);
});

test('canceling recovery does not authorize deletion',async()=>{
  const f=fixture({items:[{name:'物品',quantity:1,refund:1}],reward_reversal:3,balance_after:-2,token:'signed'},false);
  assert.equal(await f.run(),null);
  assert.match(f.dialogs[0].text,/2 Coins 待抵扣/);
});

test('report penalties are included in the negative balance confirmation',async()=>{
  const f=fixture({items:[],reward_reversal:0,balance_after:1,token:'signed'});
  assert.equal((await f.run('reject',{authorPenalty:3})).token,'signed');
  assert.match(f.dialogs[0].text,/举报成立额外扣除 3 Coins/);
  assert.match(f.dialogs[0].text,/2 Coins 待抵扣/);
  assert.match(f.dialogs[0].text,/后续收入先抵扣欠额/);
});

test('administrator rejection also confirms recovery, while an ordinary rejection needs no second dialog',async()=>{
  const recovered=fixture({items:[{name:'物品',quantity:1,refund:1}],reward_reversal:1,balance_after:0,token:'signed'});
  assert.equal((await recovered.run('reject')).token,'signed');
  assert.match(recovered.dialogs[0].title,/物品回收/);
  const ordinary=fixture({items:[],reward_reversal:0,balance_after:10,token:'signed'});
  await ordinary.run('reject');assert.equal(ordinary.dialogs.length,0);
});
