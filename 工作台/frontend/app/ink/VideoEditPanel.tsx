'use client';
import { useEffect, useRef, useState } from 'react';
import Select from '@/components/Select';
import { X } from 'lucide-react';
import { api, json, type Project, type Shot } from './ink-shared';
import { previewVideo, videoEditSource } from './wizard-state';

type Version = { video: string; video_url: string; kind: string; current: boolean; needs_confirmation?: boolean; created: number };
const label = (v: Version) => v.kind === 'edited' ? '局部调整版' : v.kind === 'subtitled' ? '配音字幕版' : '原视频';

export default function VideoEditPanel({ project, shot, disabled, onUpdated, onWorkingChange, open, onOpen, onClose }: {
  open: boolean; onOpen: () => void; onClose: () => void;
  project: Project; shot: Shot; disabled: boolean; onUpdated: (p: Project) => Project;
  onWorkingChange: (working: boolean) => void;
}) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState('');
  const [instruction, setInstruction] = useState(shot.video_edit_draft?.instruction || '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const blocked = disabled || pending;
  const proposal = shot.video_proposal;
  const currentVideoUrl = previewVideo(shot);
  const sourceVersion = versions.find(version => version.video === source);
  useEffect(() => {
    if (!open) return;
    const el = dialog.current;
    el?.showModal();
    let active = true;
    setLoading(true); setError(''); setSource(''); setVersions([]);
    void api<{ videos: Version[] }>(`/projects/${project.id}/shots/${shot.id}/video-history`).then(data => {
      if (!active) return;
      setVersions(data.videos);
      setSource(videoEditSource(data.videos, currentVideoUrl));
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : '视频版本加载失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; el?.close(); };
  }, [open, project.id, shot.id, currentVideoUrl]);
  async function mutate(action: string, body: unknown) {
    if (blocked) return;
    setPending(true); onWorkingChange(true); setError(''); setNotice('');
    try {
      onUpdated(await api<Project>(`/projects/${project.id}/shots/${shot.id}/${action}`, json('POST', body)));
      onClose();
      if (action === 'adopt-video-candidate') setNotice('已采用调整版，声音沿用底稿；已有成片需重新合成。');
      if (action === 'discard-video-candidate') setNotice('已放弃候选，当前视频保留；候选仍可在历史版本查看。');
    } catch (e) { setError(e instanceof Error ? e.message : '操作失败'); }
    finally { setPending(false); onWorkingChange(false); }
  }
  return <section aria-label="视频局部调整">
    {notice ? <p role="status" className="ink-wizard-review">{notice}</p> : null}
    {!open && error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}
    {proposal ? <div className="ink-proposal">
      <h3>视频调整候选 · 尚未采用</h3>
      <p>{proposal.instruction}</p>
      <div className="ink-proposal-grid">
        <figure><video key={proposal.source_url} controls preload="metadata" src={proposal.source_url} aria-label="调整前的底稿视频" /><figcaption>调整前 · 本次底稿</figcaption></figure>
        <figure><video key={proposal.video_url} controls preload="metadata" src={proposal.video_url} aria-label="局部调整视频候选" /><figcaption>调整后 · 新候选</figcaption></figure>
      </div>
      <p className="ink-wizard-footnote">检查动作、画风和口型是否合适，采用后才用于当前镜头和合成。</p>
      <div className="ink-wizard-secondary">
        <button type="button" disabled={blocked} onClick={() => onOpen()}>继续调整要求</button>
        <button type="button" disabled={blocked} onClick={() => void mutate('discard-video-candidate', {candidate_id: proposal.id})}>放弃候选</button>
        <button type="button" className="ink-primary-button" disabled={blocked} onClick={() => void mutate('adopt-video-candidate', {candidate_id: proposal.id})}>采用调整版</button>
      </div>
    </div> : null}
    {open ? <dialog ref={dialog} className="ink-wizard-dialog" aria-labelledby="ink-video-edit-title" onCancel={e => { e.preventDefault(); if (!pending) onClose(); }}>
      <header><h2 id="ink-video-edit-title">基于已有视频调整</h2><button type="button" disabled={pending} onClick={() => onClose()} aria-label="关闭视频调整"><X size={20} /></button></header>
      <form onSubmit={e => { e.preventDefault(); void mutate('preview-video', {video: source, revision: shot.revision, instruction}); }}>
        <div className="ink-wizard-dialog-body">
          <p>选择已生成的视频作底稿，描述要改的动作，生成后对比候选。</p>
          <label>选择底稿<Select value={source} disabled={blocked || loading} onChange={e => setSource(e.target.value)}>
            {!source ? <option value="">{loading ? '正在加载…' : versions.length ? '请选择底稿' : '暂无视频'}</option> : null}
            {versions.map(v => <option key={v.video} value={v.video}>{v.current ? v.needs_confirmation ? '待确认 · ' : '当前使用 · ' : ''}{label(v)} · {new Date(v.created * 1000).toLocaleString('zh-CN')}</option>)}
          </Select></label>
          {sourceVersion ? <video key={source} className="ink-video-edit-preview" controls preload="metadata" src={sourceVersion.video_url} poster={sourceVersion.current && !shot.image_stale ? shot.image_url || undefined : undefined} aria-label="本次视频调整底稿" /> : null}
          <label>只调整哪些动作？<textarea required maxLength={1000} rows={4} disabled={blocked} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="例如：仅把书生接伞的动作放慢，右手接稳后少女再松手；其余动作、镜头和水墨画风保持。" /></label>
          <p className="ink-wizard-footnote">生成新候选会计费，原视频保留。尽量保持未指定部分，但仍需播放核对。底稿需为2至10秒，声音沿用底稿。</p>
          {proposal ? <p>重新生成会保留上一候选到历史版本。</p> : null}
          {error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}
        </div>
        <footer><button type="submit" className="ink-primary-button" disabled={blocked || loading || !source || !instruction.trim()}>{pending ? '正在提交…' : '生成调整候选（计费）'}</button></footer>
      </form>
    </dialog> : null}
  </section>;
}
