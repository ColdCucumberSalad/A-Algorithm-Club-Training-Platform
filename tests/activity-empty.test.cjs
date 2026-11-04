const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function render(record, day = record, today = '2026-11-01') {
  const elements = {
    '#activityRecords':{}, '#pulseFocus':{},
    '#activitySubmit':{}, '#openSubmission':{hidden:false},
  };
  const {prepare}=require('./activity-fixture.cjs');
  const c=prepare({
    $:selector=>elements[selector],$$:()=>[],pulseToday:today,loadActivitySelectedDay(){},
    document:{body:{classList:{contains:()=>false}}}
  });
  if(record)c.activityStore.merge([record]);
  c.renderActivityDay(day);
  return elements['#activityRecords'].innerHTML;
}

test('a loaded empty date overrides a stale hasSubmission flag from the date strip', () => {
  const record = {date:'2026-10-23',daily:0,ac:0,hasSubmission:false,records:[]};
  assert.match(render(record,{...record,hasSubmission:true}),/当日没有提交/);
  assert.doesNotMatch(render(record,{...record,hasSubmission:true}),/已有提交/);
});

test('a checkin without a submission keeps the checkin-only explanation', () => {
  const html = render({date:'2026-10-23',daily:0,hasSubmission:false,checkedIn:true,records:[]});
  assert.match(html,/当日没有提交/);
  assert.match(html,/已签到，尚未提交题目/);
  assert.doesNotMatch(html,/已有提交/);
});

test('only a real pending submission shows the unconfirmed AC explanation', () => {
  const record = {date:'2026-10-23',daily:1,hasSubmission:true,records:[]};
  assert.match(render(record),/当日已有提交，暂无已确认的 AC 记录/);
  assert.match(render({...record,date:'2026-11-01'}),/今日已有提交，暂无已确认的 AC 记录/);
});

test('an unloaded date shows loading instead of inferring a submission', () => {
  assert.match(render(null,{date:'2026-10-23',hasSubmission:true}),/正在加载当天记录/);
});

test('today and future empty dates retain their own messages', () => {
  assert.match(render({date:'2026-11-01',daily:0,records:[]}),/今日没有提交/);
  assert.match(render({date:'2026-11-02',daily:0,records:[]}),/这一天还未到来/);
});
