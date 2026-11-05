const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
const lock=source.slice(source.indexOf('function lockSubmissionForm('),source.indexOf('let submissionScrollState'));
const handler=source.slice(source.indexOf("$('#submissionForm').addEventListener('submit'"),source.indexOf("document.addEventListener('paste'"));
function fixture(){
 const button={disabled:false,textContent:'提交记录',dataset:{},setAttribute(){},removeAttribute(){}};
 const input={disabled:false,value:'my code',files:[]};
 const closed={disabled:false};let resolve,reject,listener;
 const calls=[];const form={dataset:{submissionMode:'today'},querySelector:()=>button,querySelectorAll:()=>[button,input],setAttribute(){},removeAttribute(){},addEventListener:(event,fn)=>{listener=fn;}};
 const context={submissionPending:false,submissionSession:1,adminTestMode:false,demoMode:false,editingSubmission:null,resubmitting:null,submissionEditReturnState:null,
 $:key=>key==='#submissionForm'?form:key==='#closeSubmission'?closed:input,
 FormData:class{set(){} delete(){}},clubApi:{request:()=>{calls.push('request');return new Promise((a,b)=>{resolve=a;reject=b;});}},
 saveSubmissionDraft(){},clearSubmissionDraft:()=>calls.push('clear'),closeModal:()=>calls.push('close'),resetSubmissionForm:()=>calls.push('reset'),playFeedback(){},showToast(){},refreshAfterMutation(){},canManage:false};
 vm.createContext(context);vm.runInContext(lock+handler,context);
 return {context,input,button,closed,calls,submit:()=>listener({preventDefault(){},target:form}),resolve:()=>resolve({ok:true}),reject:()=>reject(Error('offline'))};
}
test('pending request locks fields and closing control and rejects duplicate submissions',async()=>{
 const f=fixture(),pending=f.submit();assert.equal(f.input.disabled,true);assert.equal(f.closed.disabled,true);
 await f.submit();assert.deepEqual(f.calls,['request']);f.resolve();await pending;
 assert.equal(f.input.disabled,false);assert.equal(f.closed.disabled,false);assert.equal(f.context.submissionPending,false);
 assert.deepEqual(f.calls,['request','clear','close','reset']);
});
test('failure restores controls and preserves contents without clearing or closing',async()=>{
 const f=fixture(),pending=f.submit();f.reject();await pending;
 assert.equal(f.input.value,'my code');assert.equal(f.input.disabled,false);assert.equal(f.button.disabled,false);assert.deepEqual(f.calls,['request']);
});
test('late response cannot clear a different form session',async()=>{
 const f=fixture(),pending=f.submit();f.context.submissionSession++;f.resolve();await pending;
 assert.deepEqual(f.calls,['request']);
});
test('opening, closing and cancelling an edit are blocked during submission',async()=>{
 const context={submissionPending:true,showToast(){}};vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('async function openModal('),source.indexOf('let submissionPending')),context);
 vm.runInContext(source.slice(source.indexOf('function closeModal(){'),source.indexOf("$$('.nav-item[data-view]')",source.indexOf('function closeModal(){'))),context);
 const community=fs.readFileSync(require.resolve('../community.js'),'utf8');
 vm.runInContext(community.slice(community.indexOf('function cancelSubmissionEdit(){'),community.indexOf('function setDetailAvatar')),context);
 assert.equal(await vm.runInContext('openModal()',context),false);
 assert.equal(vm.runInContext('closeModal()',context),false);
 vm.runInContext('cancelSubmissionEdit()',context);
});
