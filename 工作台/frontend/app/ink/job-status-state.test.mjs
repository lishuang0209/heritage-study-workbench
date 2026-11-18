import test from 'node:test';
import assert from 'node:assert/strict';
import {jobHint} from './job-status-state.ts';

const job={id:'job',action:'split',state:'running',error:''};
test('split feedback shows the current persisted step even after a long wait',()=>{
  assert.equal(jobHint({...job,progress:{message:'正在解析研学资料',completed:0,total:3}},103),'第 1/3 步 · 正在解析研学资料');
  assert.equal(jobHint({...job,progress:{message:'正在规划6个分镜',completed:1,total:3}},103),'第 2/3 步 · 正在规划6个分镜');
});
test('terminal status does not show a stale running step or hide the error',()=>{
  const progress={message:'新分镜已保存',completed:3,total:3};
  assert.equal(jobHint({...job,state:'completed',progress},110),'新分镜已保存');
  assert.equal(jobHint({...job,state:'completed',progress},110,'已生成候选'),'已生成候选');
  assert.equal(jobHint({...job,state:'failed',error:'画面方案未完整',progress},110),'画面方案未完整');
  assert.equal(jobHint({...job,state:'interrupted',progress},110),'已保留完成的结果，请检查提示后手动重试。');
});
test('legacy and malformed progress retain the waiting message',()=>{
  assert.match(jobHint(job,103),/等待较久/);
  for(const progress of [null,{},'bad',{message:'错误',completed:7,total:3},{message:'错误',completed:1,total:0}]) {
    assert.match(jobHint({...job,progress},10),/正在等待生成结果/);
  }
  assert.match(jobHint({...job,state:'submitting'},0),/正在提交/);
});
