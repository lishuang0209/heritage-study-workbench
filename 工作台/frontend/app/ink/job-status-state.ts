import type { Job } from './ink-shared';

export function jobHint(job:Job,seconds:number|null,successHint?:string):string {
  if (job.error) return job.error;
  if (job.state==='submitting') return '正在提交生成请求，请勿重复点击。';
  const progress=job.progress;
  const validProgress=progress && typeof progress.message==='string' && progress.message.trim() &&
    Number.isInteger(progress.completed) && Number.isInteger(progress.total) &&
    progress.total>0 && progress.total<=100 && progress.completed>=0 && progress.completed<=progress.total;
  if (job.state==='running') {
    if (validProgress) return `第 ${Math.min(progress.completed+1,progress.total)}/${progress.total} 步 · ${progress.message}`;
    return seconds!==null && seconds>=90 ? '本次等待较久，仍在等待生成结果。完成后会自动更新，请勿重复发起。' : '正在等待生成结果，完成后会自动更新，请勿重复发起。';
  }
  if (job.state==='completed') return successHint || (validProgress ? progress.message : '结果已更新，可继续下一步创作。');
  return '已保留完成的结果，请检查提示后手动重试。';
}
