const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');

test('closing an unopened review window is safe after a gallery edit',()=>{
  const context={window:{},document:{addEventListener(){}}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require.resolve('../static/moderation.js'),'utf8'),context);
  assert.doesNotThrow(()=>context.window.ModerationWindows.closeReview());
  assert.doesNotThrow(()=>context.window.ModerationWindows.closeReview());
});
