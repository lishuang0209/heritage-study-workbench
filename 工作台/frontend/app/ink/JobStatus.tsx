'use client';
import { useEffect, useState } from 'react';
import { LoaderCircle, CircleCheck, CircleAlert } from 'lucide-react';
import { names, type Job } from './ink-shared';
export default function JobStatus({ jobs, title, successHint }: { jobs: Job[]; title?:string; successHint?:string }) {
  const [now, setNow] = useState(() => Date.now());
  const running = jobs.some(job => job.state === 'running' || job.state === 'submitting');
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  return <section className="ink-job-list" aria-label="生成任务状态">
    {jobs.slice(0, 3).map(job => {
      const submitting = job.state === 'submitting';
      const pending = job.state === 'running' || submitting;
      const completed = job.state === 'completed';
      const failed = !pending && !completed;
      const seconds = job.created ? Math.max(0, Math.floor((now - job.created * 1000) / 1000)) : null;
      const elapsed = seconds === null ? '' : seconds < 60 ? `${seconds}秒` : `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
      const status = submitting ? '正在提交' : pending ? '正在处理' : completed ? '已完成' : job.state === 'submit-failed' ? '提交失败' : job.state === 'interrupted' ? '已中断' : '生成失败';
      return <article key={job.id} className={`ink-job-status ${pending ? 'is-running' : failed ? 'is-failed' : ''}`}>
        <div className="ink-job-main">
          <span className="ink-job-icon" aria-hidden="true">{pending ? <LoaderCircle className="ink-job-spinner" size={20} /> : completed ? <CircleCheck size={20} /> : <CircleAlert size={20} />}</span>
          <div className="ink-job-copy" role={failed ? 'alert' : 'status'} aria-live={failed ? 'assertive' : 'polite'}><p><strong>{title || names[job.action] || job.action}</strong><span> · {status}</span></p>
            <p className="ink-job-hint">{job.error || (submitting ? '正在提交生成请求，请勿重复点击。' : pending ? seconds !== null && seconds >= 90 ? '本次等待较久，仍在等待生成结果。完成后会自动更新，请勿重复发起。' : '正在等待生成结果，完成后会自动更新，请勿重复发起。' : completed ? successHint || '结果已更新，可继续下一步创作。' : '已保留完成的结果，请检查提示后手动重试。')}</p>
          </div>
          {pending && !submitting && elapsed ? <span className="ink-job-time">已等待 {elapsed}</span> : null}
        </div>
        {pending ? <div className="ink-job-track" role="progressbar" aria-label="生成进度" aria-valuetext={submitting ? '正在提交生成请求' : '正在生成，完成后会自动更新'}><span /></div> : null}
      </article>;
    })}
  </section>;
}
