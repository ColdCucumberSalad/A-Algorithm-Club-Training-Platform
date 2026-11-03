const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../app.js'), 'utf8');
const draftSource = source.slice(source.indexOf('// Store only text fields.'), source.indexOf('\nfunction resetSubmissionForm()'));

function fixture(storage = new Map()) {
  const nodes = new Map(), events = {}, messages = [];
  const $ = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {value: '', dataset: {}, addEventListener(type, fn) { this[type] = fn; },
      classList: {remove() {}}, setAttribute() {}, removeAttribute() {}, querySelector: () => $('submit')});
    return nodes.get(selector);
  };
  $('#submissionForm').dataset = {weekId: '4', recordDate: '2026-11-04'};
  $('#submissionCodeLanguage').value = 'text';
  const context = vm.createContext({$, localStorage: {
    getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key),
  }, window: {addEventListener: (type, fn) => { events[type] = fn; }},
  document: {visibilityState: 'visible', addEventListener: (type, fn) => { events[type] = fn; }},
  renderCodeDraft() {}, renderSubmissionDraftBlog() {}, showToast: message => messages.push(message)});
  const run = code => vm.runInContext(code, context);
  run(draftSource);
  run("submissionDraftOwner = ['alice', 1, false]");
  return {nodes, $, events, messages, storage, context, run};
}

test('typing persists exact text immediately and a fresh page restores all fields without images', () => {
  const f = fixture(); f.run('startSubmissionDraft()');
  const values = {'#logicText': ' 思路\n复杂度 O(n) ', '#submissionCodeInput': 'int main() {\n    return 0;\n}',
    '#submissionCodeLanguage': 'cpp', '#blogMarkdownInput': '# 未点击保存的 Markdown\n\n正文 ', '#problemUrl': 'https://example.com/problem/1'};
  for (const [selector, value] of Object.entries(values)) { f.$(selector).value = value; f.$(selector).input(); }
  f.$('#proofImage').value = 'private-image.png';
  const stored = [...f.storage.values()][0];
  assert.ok(!stored.includes('private-image'));
  assert.equal(Object.keys(JSON.parse(stored).fields).length, 5);
  const fresh = fixture(f.storage); fresh.run('startSubmissionDraft()');
  for (const [selector, value] of Object.entries(values)) assert.equal(fresh.$(selector).value, value);
  assert.equal(fresh.$('#proofImage').value, '');
  assert.match(fresh.messages[0], /已恢复本地草稿/);
});

test('closing and reopening restores changes; a cleared successful draft stays cleared on pagehide', () => {
  const f = fixture(); f.run('startSubmissionDraft()');
  f.$('#logicText').value = 'last keystroke';
  f.context.submissionScrollState = null;
  f.run(source.slice(source.indexOf('function closeModal(){'), source.indexOf("$$('.nav-item", source.indexOf('function closeModal(){'))));
  f.run('closeModal()');
  f.$('#logicText').value = ''; f.run('startSubmissionDraft()');
  assert.equal(f.$('#logicText').value, 'last keystroke');
  f.run('clearSubmissionDraft(); closeModal()'); f.events.pagehide();
  assert.equal(f.storage.size, 0);
});

test('accounts, teams, test mode, dates and correction records have independent drafts', () => {
  const f = fixture(); f.run('startSubmissionDraft()');
  f.$('#logicText').value = 'original'; f.$('#logicText').input();
  for (const setup of [
    "submissionDraftOwner = ['bob', 1, false]; startSubmissionDraft()",
    "submissionDraftOwner = ['alice', 2, false]; startSubmissionDraft()",
    "submissionDraftOwner = ['alice', 1, true]; startSubmissionDraft()",
    "submissionDraftOwner = ['alice', 1, false]; $('#submissionForm').dataset.recordDate = '2026-11-03'; startSubmissionDraft()",
    'startSubmissionDraft({id: 8}, {edit: true})', 'startSubmissionDraft({id: 8})', 'startSubmissionDraft({id: 9})',
  ]) {
    f.$('#logicText').value = ''; f.run(setup);
    assert.equal(f.$('#logicText').value, '');
  }
  f.run("$('#submissionForm').dataset.recordDate = '2026-11-04'; startSubmissionDraft()");
  assert.equal(f.$('#logicText').value, 'original');
});

test('editing existing records restores the local revision over server content', () => {
  const f = fixture(); f.run('startSubmissionDraft({id: 8}, {edit: true})');
  f.$('#logicText').value = 'local revision'; f.$('#logicText').input();
  const fresh = fixture(f.storage);
  fresh.$('#logicText').value = 'server content';
  fresh.run('startSubmissionDraft({id: 8}, {edit: true})');
  assert.equal(fresh.$('#logicText').value, 'local revision');
});

test('empty drafts are removed, invalid data and unavailable storage do not prevent editing', () => {
  const f = fixture(); f.run('startSubmissionDraft()');
  f.$('#logicText').value = 'x'; f.$('#logicText').input();
  f.$('#logicText').value = ''; f.$('#logicText').input();
  assert.equal(f.storage.size, 0);
  f.run("localStorage.getItem = () => '{invalid'; startSubmissionDraft()");
  f.run("localStorage.getItem = () => { throw Error('disabled'); }; startSubmissionDraft()");
  f.run("localStorage.setItem = () => { throw Error('quota'); }");
  f.$('#logicText').value = 'still editable';
  f.$('#logicText').input(); f.events.pagehide();
  assert.equal(f.messages.length, 1); assert.match(f.messages[0], /保存失败/);
});

test('failed submissions retain the draft and successful submissions clear it', async () => {
  for (const outcome of ['network', 'rejected', 'success']) {
    const f = fixture(); f.run('startSubmissionDraft()');
    f.$('#logicText').value = 'draft'; f.$('#submissionCodeInput').value = 'code';
    f.$('#proofImage').files = [];
    f.context.adminTestMode = false; f.context.demoMode = false;
    f.context.editingSubmission = null; f.context.resubmitting = null;
    f.context.FormData = class {set() {} delete() {}};
    f.context.getBlogEditorContent = () => '';
    f.context.clubApi = {request: async () => {
      if (outcome === 'network') throw Error('offline');
      return {ok: outcome === 'success', status: outcome === 'success' ? 200 : 400, json: async () => ({error: 'failed'})};
    }};
    f.context.closeModal = () => f.run('saveSubmissionDraft(); activeSubmissionDraftKey = null');
    f.context.resetSubmissionForm = () => { f.$('#logicText').value = ''; };
    f.context.playFeedback = () => {}; f.context.refreshAfterMutation = () => {}; f.context.canManage = false;
    const start = source.indexOf("$('#submissionForm').addEventListener('submit'");
    f.run(source.slice(start, source.indexOf("\ndocument.addEventListener('paste'", start)));
    await f.$('#submissionForm').submit({preventDefault() {}, target: f.$('#submissionForm')});
    assert.equal(f.storage.size, outcome === 'success' ? 0 : 1, outcome);
    f.events.pagehide();
    assert.equal(f.storage.size, outcome === 'success' ? 0 : 1, outcome);
  }
});
