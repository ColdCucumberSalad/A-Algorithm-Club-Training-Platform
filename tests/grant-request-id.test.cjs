const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');

test('admin grants can generate stable UUIDs without crypto.randomUUID (plain HTTP)',()=>{
 const context={window:{},crypto:{getRandomValues:array=>webcrypto.getRandomValues(array)},Uint8Array};
 vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../api.js'),'utf8'),context);
 const form={dataset:{}};
 // Exercise the actual grant token expression used by each submit handler.
 for(const file of ['../static/team-management.js','../static/account-management.js']){
  const source=fs.readFileSync(require.resolve(file),'utf8');
  const expression=source.match(/form.dataset.requestId \|\|= [^;]+;/)?.[0];
  assert.ok(expression,file);context.form=form;
  vm.runInContext(expression,context);const first=form.dataset.requestId;
  assert.match(first,/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  vm.runInContext(expression,context);assert.equal(form.dataset.requestId,first);
 }
});
