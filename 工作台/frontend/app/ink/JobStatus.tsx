'use client';
import { useEffect, useState } from 'react';
import { LoaderCircle, CircleCheck, CircleAlert } from 'lucide-react';
import { names, type Job } from './ink-shared';
export default function JobStatus({ jobs }: { jobs: Job[] }) {
  const [now, setNow] = useState(() => Date.now());
  const running = jobs.some(job => job.state === 'running');
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  return <section className="ink-job-list" aria-label="生成任务状态">
    {jobs.slice(0, 3).map(job => {
      const pending = job.state === 'running';
      const completed = job.state === 'completed';
      const seconds = job.created ? Math.max(0, Math.floor((now - job.created * 1000) / 1000)) : null;
      const elapsed = seconds === null ? '' : seconds < 60 ? `${seconds}秒` : `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
      const status = pending ? '正在处理' : completed ? '已完成' : job.state === 'interrupted' ? '已中断' : '生成失败';
      return <article key={job.id} className={`ink-job-status ${pending ? 'is-running' : ''}`}>
        <div className="ink-job-main">
          <span className="ink-job-icon" aria-hidden="true">{pending ? <LoaderCircle className="ink-job-spinner" size={20} /> : completed ? <CircleCheck size={20} /> : <CircleAlert size={20} />}</span>
          <div className="ink-job-copy"><p role="status" aria-live="polite"><strong>{names[job.action] || job.action}</strong><span> · {status}</span></p>
            <p className="ink-job-hint">{job.error || (pending ? seconds !== null && seconds >= 90 ? '本次等待较久，仍在等待生成结果。完成后会自动更新，请勿重复发起。' : '正在等待生成结果，完成后会自动更新，请勿重复发起。' : completed ? '结果已更新，可继续下一步创作。' : '已保留完成的结果，请检查提示后手动重试。')}</p>
          </div>
          {pending && elapsed ? <span className="ink-job-time">已等待 {elapsed}</span> : null}
        </div>
        {pending ? <div className="ink-job-track" aria-hidden="true"><span /></div> : null}
      </article>;
    })}
  </section>;
}
