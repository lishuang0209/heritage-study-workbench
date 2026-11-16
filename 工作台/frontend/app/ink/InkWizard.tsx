'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, Film, LoaderCircle, Settings2, Upload, X } from 'lucide-react';
import { api, json, type Project, type Shot, type InkCaption, type Track, type DeletedShot } from './ink-shared';
import { nextShotStep, adjustmentPlan, wizardSteps, unlockedStage, resumeStage, referenceShot, imageReady, clipReady, soundReady, previewVideo } from './wizard-state';
import JobStatus from './JobStatus';
import CreativeSetup from './CreativeSetup';
import StoryboardEditor from './StoryboardEditor';
import './wizard.css';
import VideoEditPanel from './VideoEditPanel';

const eraChoices = ['', '汉代', '唐代', '宋代', '北宋', '南宋', '明代', '清代'];

type Props = {
  project: Project; tracks: Track[]; readonly: boolean;
  onWorkingChange: (working: boolean) => void;
  onAction: (action: string, sid?: string, preset?: string) => Promise<Project>;
  onUpdated: (project: Project) => Project;
  onSave: (sid: string, data: unknown) => Promise<Project>;
  onUpload: (sid: string, file: File) => Promise<Project>;
  onLock: (sid: string, caption: InkCaption) => Promise<Project>;
  onVoices: (voices: Record<string, string>) => Promise<Project>;
  onMusic: (id: string) => Promise<Project>;
  onClone: () => Promise<void>;
};
function AdjustmentDialog({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const el = ref.current; el?.showModal(); return () => el?.close(); }, []);
  return <dialog ref={ref} className="ink-wizard-dialog" onCancel={e => { e.preventDefault(); close(); }} aria-labelledby="ink-adjust-title">
    <header><h2 id="ink-adjust-title">{title}</h2><button type="button" onClick={close} aria-label="关闭弹窗"><X size={20} /></button></header>{children}
  </dialog>;
}
export default function InkWizard({ project: p, tracks, readonly, onWorkingChange, onAction, onUpdated, onSave, onUpload, onLock, onVoices, onMusic, onClone }: Props) {
  const storageKey = `ink.wizard.v2.${p.id}`;
  const [requestedStage, setRequestedStage] = useState(() => unlockedStage(p));
  const [hydrated, setHydrated] = useState(false);
  const [activeId, setActiveId] = useState(() => referenceShot(p)?.id || 's1');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [undoNoticeShot, setUndoNoticeShot] = useState<string | null>(null);
  useEffect(() => {
    if (!undoNoticeShot) return;
    const timer = window.setTimeout(() => { setUndoNoticeShot(null); setNotice(''); }, 8000);
    return () => window.clearTimeout(timer);
  }, [undoNoticeShot]);
  const [storyboardEditing, setStoryboardEditing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ shot: Shot; number: number } | null>(null);
  const [editingBackground, setEditingBackground] = useState(false);
  const [eraDraft, setEraDraft] = useState('');

  const [setupLabel, setSetupLabel] = useState('确认，继续');
  const [modal, setModal] = useState<'shot' | 'video' | 'voices' | 'history' | 'video-history' | 'video-edit' | null>(null);
  const [historyItems, setHistoryItems] = useState<{ image: string; image_url: string; created: number; status: string; has_snapshot: boolean }[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [videoHistoryItems, setVideoHistoryItems] = useState<{video: string; video_url: string; created: number; kind: string; current: boolean; needs_confirmation?: boolean}[]>([]);
  const [editMode, setEditMode] = useState<'detail' | 'redesign' | 'style'>('redesign');
  const [detailInstruction, setDetailInstruction] = useState('');
  const [draft, setDraft] = useState<Shot | null>(null);
  const [videoDraft, setVideoDraft] = useState({motion:'',camera:'',duration:5,mode:'first_frame',end_shot_id:''});
  const [voiceDraft, setVoiceDraft] = useState<Record<string, string>>({});
  const stage = resumeStage(p, requestedStage);
  const shot = p.shots.find(s => s.id === activeId) || referenceShot(p);
  const stageHeading = useRef<HTMLHeadingElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const nativeAudio = p.video_modes?.find(m => m.id === (shot?.video_settings?.mode || 'first_frame'))?.native_audio;
  const busy = p.jobs.some(j => j.state === 'running');
  const disabled = readonly || pending || busy;
  useEffect(() => {
    try { const saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); if (saved) { setRequestedStage(resumeStage(p, saved.stage)); if (p.shots.some(s => s.id === saved.shot)) setActiveId(saved.shot); } } catch { /* storage may be unavailable */ }
    setHydrated(true);
    // The wizard is keyed by project ID; restore only on entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);
  useEffect(() => { if (hydrated) { try { localStorage.setItem(storageKey, JSON.stringify({ stage, shot: activeId })); } catch { /* keep working without storage */ } } }, [hydrated, stage, activeId, storageKey]);
  useEffect(() => { if (requestedStage !== stage) setRequestedStage(stage); }, [requestedStage, stage]);
  useEffect(() => { if (hydrated) stageHeading.current?.focus({ preventScroll: true }); }, [stage, hydrated]);
  const run = async (fn: () => Promise<unknown>) => {
    if (pending || busy || readonly) return;
    setError(''); setNotice(''); setUndoNoticeShot(null); setPending(true); onWorkingChange(true);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : '操作失败，请重试'); }
    finally { setPending(false); onWorkingChange(false); }
  };
  const go = (next: number, id?: string) => {
    if (pending || busy || storyboardEditing) return;
    setError(''); setModal(null); setRequestedStage(next);
    if (id) setActiveId(id);
    stageHeading.current?.scrollIntoView({ block: 'start' });
  };
  const openShot = (s: Shot, continueCandidate = false) => {
    const saved = continueCandidate ? s.image_draft : null;
    const editing = structuredClone({ ...s, ...(saved?.shot || {}) });
    if (p.creative_settings) {
      editing.character_ids = editing.character_ids.filter(id=>p.characters.some(c=>c.id===id));
      editing.dialogues = editing.dialogues.filter(d=>editing.character_ids.includes(d.character_id));
      editing.prop_ids = (editing.prop_ids||[]).filter(id=>p.creative_settings!.props.some(x=>x.id===id));
      if (!p.creative_settings.scenes.some(x=>x.id===editing.scene_id)) editing.scene_id=null;
    }
    setActiveId(s.id); setDraft(editing);
    setEditMode(saved?.mode || (s.image_url ? 'detail' : 'redesign')); setDetailInstruction(saved?.instruction || ''); setModal('shot');
  };
  const generateSavedShot = (s: Shot) => run(async () => {
    const input = { duration: s.duration ?? 5, content: s.content, scene: s.scene, camera: s.camera,
      motion: s.motion, character_ids: s.character_ids, scene_id: s.scene_id || null,
      prop_ids: s.prop_ids || [], dialogues: s.dialogues };
    onUpdated(await api<Project>(`/projects/${p.id}/shots/${s.id}/preview`,
      json('POST', { mode: 'redesign', instruction: '', shot: input })));
  });
  const openHistory = async () => {
    if (!shot) return;
    const videos = stage === 4;
    setModal(videos ? 'video-history' : 'history'); setHistoryItems([]); setVideoHistoryItems([]); setHistoryLoading(true); setError('');
    try {
      if (videos) {
        const data = await api<{videos: typeof videoHistoryItems}>(`/projects/${p.id}/shots/${shot.id}/video-history`);
        setVideoHistoryItems(data.videos);
      } else {
        const data = await api<{images: typeof historyItems}>(`/projects/${p.id}/shots/${shot.id}/history`);
        setHistoryItems(data.images);
      }
    } catch (e) { setError(e instanceof Error ? e.message : '历史版本加载失败'); }
    finally { setHistoryLoading(false); }
  };

  const adoptVideo = (item: typeof videoHistoryItems[number]) => run(async () => {
    if (!shot) return;
    onUpdated(await api<Project>(`/projects/${p.id}/shots/${shot.id}/adopt-video`, json('POST', {
      video: item.video, revision: shot.revision, current_clip: shot.clip || null,
    })));
    setModal(null); setNotice('已采用此视频及其声音，后续合成使用这一版。');
  });
  const restoreImage = (item: typeof historyItems[number]) => run(async () => {
    if (!shot || !window.confirm(item.has_snapshot ? '采用这张历史图片，并恢复当时的镜头内容？已有视频需要更新。' : '这张旧图没有当时的文字记录。仅替换图片、保留当前镜头文字，已有视频需要更新。继续吗？')) return;
    onUpdated(await api<Project>(`/projects/${p.id}/shots/${shot.id}/restore-image`, json('POST', { image: item.image, revision: shot.revision, current_image: shot.image })));
    setModal(null); setUndoNoticeShot(shot.id); setNotice('已采用历史图片。已有视频需要更新。');
  });
  const confirmCurrent = () => run(async () => {
    if (!shot?.image) return;
    onUpdated(await api<Project>(`/projects/${p.id}/shots/${shot.id}/confirm-image`, json('POST', { image: shot.image, revision: shot.revision })));
    setNotice('已确认使用当前图片，未调用模型。已有视频若标记待更新，仍需单独处理。');
  });
  const checkCandidateStyle = () => run(async () => {
    if (!shot?.image_proposal) return;
    onUpdated(await api<Project>(`/projects/${p.id}/shots/${shot.id}/check-style`, json('POST', { candidate_id: shot.image_proposal.id })));
  });
  const chooseCandidate = (action: 'adopt' | 'discard' | 'undo-image') => run(async () => {
    if (!shot) return;
    onUpdated(await api<Project>(`/projects/${p.id}/shots/${shot.id}/${action}`, json('POST', { candidate_id: shot.image_proposal?.id })));
    setUndoNoticeShot(action === 'adopt' ? shot.id : null);
    if (action === 'undo-image') setModal(null);
    setNotice(action === 'adopt' ? '已采用新图。已有视频需重新生成。' : action === 'discard' ? '已放弃候选，原图保持不变。' : '已撤回采用，恢复原图及镜头内容。');
  });
  const deleteShot = () => run(async () => {
    if (!deleteTarget) return;
    const target = deleteTarget.shot;
    const result = await api<Project>(`/projects/${p.id}/shots/${target.id}`, json('DELETE', { revision: target.revision }));
    onUpdated(result);
    if (activeId === target.id) setActiveId(result.shots[Math.min(deleteTarget.number - 1, result.shots.length - 1)]?.id || result.shots[0]?.id || '');
    setDeleteTarget(null);
    setNotice(`已删除第 ${deleteTarget.number} 镜，其余分镜已重新编号。`);
  });
  const restoreShot = (item: DeletedShot) => run(async () => {
    const result = await api<Project>(`/projects/${p.id}/deleted-shots/${item.id}/restore`, json('POST', {}));
    onUpdated(result);
    setActiveId(item.shot_id);
    setNotice('分镜已恢复，请确认顺序后继续。');
  });
  const originalDraft = p.shots.find(s => s.id === draft?.id);
  const editPlan = draft && originalDraft ? adjustmentPlan(p, originalDraft, draft, stage) : null;
  const previewEditing = stage >= 3 && !!draft && !!originalDraft && (editMode === 'detail' || editMode === 'style' || !editPlan?.changed || (['content', 'scene', 'camera', 'motion', 'scene_id', 'prop_ids', 'character_ids'] as const).some(k => JSON.stringify(draft[k]) !== JSON.stringify(originalDraft[k])));
  const upload = (file: File) => run(async () => {
    if (!shot) return;
    await onUpload(shot.id, file);
    if (stage === 1) {
      try { await onAction('caption', shot.id); }
      catch { throw new Error('图片已保存，准备人物信息失败。请点击底部按钮继续准备。'); }
    }
  });
  let primaryLabel = '', primary: () => void = () => {}, primaryDisabled = disabled;
  if (stage === 0) {
    primaryLabel = '确认剧本，整理创作设定';
    primary = () => void run(async () => { onUpdated(await api<Project>(`/projects/${p.id}/confirm-story`,json('POST',{}))); setRequestedStage(1); });
  } else if (stage === 1) {
    primaryLabel = setupLabel;
  } else if (stage === 2) {
    primaryLabel = p.shots.length ? '确认分镜，开始制作画面' : '生成分镜';
    primaryDisabled = disabled || storyboardEditing || !!p.storyboard_draft;
    primary = () => void run(async () => {
      if (!p.shots.length) { await onAction('split'); return; }
      onUpdated(await api<Project>(`/projects/${p.id}/confirm-storyboard`,json('POST',{}))); setRequestedStage(3); setActiveId(p.shots[0].id);
    });
  } else if (stage === 3 && shot) {
    if (!imageReady(shot)) { primaryLabel = shot.image_url ? '保留这张图，确认使用' : `生成第 ${p.shots.indexOf(shot) + 1} 镜图片`; primary = () => shot.image_url ? void confirmCurrent() : void run(() => onAction('image', shot.id)); }
    else { const next = nextShotStep(p.shots, shot.id, imageReady); primaryLabel = next ? next.returning ? `返回第 ${next.number} 镜，处理待确认图片` : `满意，继续第 ${next.number} 镜` : '图片确认完成，制作视频'; primary = () => next ? setActiveId(next.shot.id) : go(4, p.shots[0].id); primaryDisabled = pending || busy; }
  } else if (stage === 4 && shot) {
    if (!clipReady(shot)) { primaryLabel = nativeAudio ? `生成${shot.duration ?? 5}秒视频（含原声）` : shot.dialogues.length ? `生成${shot.duration ?? 5}秒视频与配音字幕` : `生成${shot.duration ?? 5}秒视频`; primary = () => void run(() => onAction('video', shot.id)); }
    else if (!soundReady(shot)) { primaryLabel = nativeAudio ? '确认原声视频' : shot.dialogues.length ? '完成配音与字幕（保留视频）' : '完成这个片段'; primary = () => void run(() => onAction('sound', shot.id)); }
    else { const next = nextShotStep(p.shots, shot.id, soundReady); primaryLabel = next ? next.returning ? `返回第 ${next.number} 段，完成待处理内容` : `满意，继续第 ${next.number} 段` : '片段确认完成，去合成'; primary = () => next ? setActiveId(next.shot.id) : go(5); primaryDisabled = pending || busy; }
  } else { primaryLabel = '合成短片'; primary = () => void run(() => onAction('assemble')); }
  const reviewingCandidate = ((stage === 3 || stage === 4) && !!shot?.image_proposal) || (stage === 4 && !!shot?.video_proposal);
  const descriptions = ['确认故事内容，再整理人物、场景和道具。', '分别确认角色、场景和关键道具，统一整部短片的设定。', '逐镜确认出场角色、所在场景、使用道具和动作。', '逐张确认图片，满意后再制作视频。', '逐段播放，检查画面、动作和声音，满意后继续。', '预览、合成并导出短片。'];
  const relevantActions = [[], ['settings','asset-image'], ['split'], ['image','preview'], ['video','sound','preview','video-preview'], ['assemble']][stage];
  const job = p.jobs[0];
  const showJob = job && (job.state === 'running' || (['failed', 'interrupted'].includes(job.state) && relevantActions.includes(job.action)));
  return <div className="ink-wizard">
    <nav className="ink-wizard-steps" aria-label="创作步骤">{wizardSteps.map((name, index) => <button key={name} type="button" disabled={index > unlockedStage(p) || pending || busy || storyboardEditing} aria-current={stage === index ? 'step' : undefined} onClick={() => go(index, index === 1 ? referenceShot(p)?.id : undefined)}><span>{index < stage ? <Check size={14} /> : index + 1}</span>{name}</button>)}</nav>
    <header className="ink-wizard-title"><div><p>第 {stage + 1} 步 / 共 6 步</p><h2 ref={stageHeading} tabIndex={-1}>{wizardSteps[stage]}</h2><p>{descriptions[stage]}</p></div><button type="button" className="ink-wizard-text-button" disabled={pending || busy || storyboardEditing} onClick={() => void run(onClone)}>复制项目</button></header>
    {error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}
    {notice ? <p role="status" className="ink-wizard-review">{notice}{undoNoticeShot === shot?.id && shot?.image_undo ? <button type="button" className="ink-wizard-text-button" disabled={disabled} onClick={() => void chooseCandidate('undo-image')}>撤销</button> : null}</p> : null}
    {showJob ? <JobStatus jobs={[job]} /> : null}
    {stage < 2 ? <section className="ink-background-panel" aria-label="故事时代背景"><div><strong>时代背景：{p.background?.era || '不指定'}</strong><span className="ink-wizard-footnote">{p.background?.era ? '用于人物服饰、场景与道具' : '按剧本设定生成'}</span></div><button type="button" disabled={disabled} onClick={()=>{setEraDraft(p.background?.era||'');setEditingBackground(true);}}>修改背景</button>{editingBackground ? <form onSubmit={e=>{e.preventDefault();void run(async()=>{onUpdated(await api<Project>(`/projects/${p.id}/background`,json('PUT',{era:eraDraft})));setEditingBackground(false);setNotice('背景已保存。已有图片保留，请核对人物、场景和道具设定。');});}}><fieldset disabled={disabled} className="ink-era-options"><legend>选择时代背景</legend><div className="ink-era-grid">{eraChoices.map(era=><label key={era || 'none'}><input type="radio" name="era" checked={eraDraft===era} onChange={()=>setEraDraft(era)}/>{era || '不指定'}</label>)}</div></fieldset><p className="ink-wizard-footnote">修改背景不会自动重写原文、服饰描述或已有图片。</p><button disabled={disabled}>保存背景</button><button type="button" disabled={disabled} onClick={()=>setEraDraft('')}>清空朝代</button><button type="button" disabled={disabled} onClick={()=>setEditingBackground(false)}>取消</button></form>:null}</section>:null}
    {stage === 0 ? <section className="ink-wizard-story"><h3>剧本原文</h3><p style={{whiteSpace:'pre-wrap'}}>{p.script}</p><p className="ink-wizard-footnote">已有镜头内容可在“分镜”步骤逐镜调整。</p></section>
    : stage === 1 ? <CreativeSetup onPrimaryLabel={setSetupLabel} project={p} disabled={disabled} run={run} onUpdated={onUpdated} onConfirmed={()=>setRequestedStage(2)} onExtract={()=>onAction('settings')} />
    : stage === 2 ? <StoryboardEditor project={p} disabled={disabled} onGenerate={() => void run(() => onAction('split'))} onSave={onSave} onUpdated={onUpdated}
      onEditingChange={editing => { setStoryboardEditing(editing); onWorkingChange(editing); if (editing) { setError(''); setNotice(''); } }}
      onDelete={(shot, number) => { setError(''); setDeleteTarget({ shot, number }); }} onRestore={item => void restoreShot(item)} />
    : stage < 5 && shot ? <>
      {stage > 2 ? <nav className="ink-wizard-thumbs" aria-label="选择镜头">{p.shots.map((s, i) => <button key={s.id} type="button" disabled={pending || busy} aria-current={s.id === shot.id ? 'true' : undefined} onClick={() => { setActiveId(s.id); setError(''); }}>{s.image_url ? <img src={s.image_url} alt={`第${i + 1}镜`} /> : <Film size={22} />}<span>第 {i + 1} 镜</span><small>{s.image_proposal ? '候选待确认' : stage === 3 ? imageReady(s) ? '图片已就绪' : s.image_url ? '待更新' : '待出图' : soundReady(s) ? '片段已就绪' : clipReady(s) ? '待配音字幕' : '待生成视频'}</small></button>)}</nav> : null}
      <section className="ink-wizard-scene">
        <div className="ink-wizard-media">{stage === 4 && previewVideo(shot) ? <video key={previewVideo(shot)} controls preload="metadata" src={previewVideo(shot)!} /> : shot.image_url ? <img src={shot.image_url} alt={shot.scene || '当前分镜'} /> : <div><Film size={42} /><p>{stage === 1 ? '先生成一张参考图' : '等待生成图片'}</p></div>}</div>
        <div className="ink-wizard-scene-copy"><p className="ink-wizard-eyebrow">{stage === 1 ? '参考画面' : `第 ${p.shots.indexOf(shot) + 1} 镜 · ${shot.duration ?? 5}秒`}</p><h3>{shot.scene || '当前镜头'}</h3><p>{shot.content}</p>
          <div className="ink-wizard-tags">{shot.character_ids.map(id => <span key={id}>{p.characters.find(c => c.id === id)?.name || '角色'}</span>)}<span>{stage === 1 ? '水墨风格' : stage === 3 ? imageReady(shot) ? '图片已就绪' : '待出图' : soundReady(shot) ? '片段已就绪' : clipReady(shot) ? '待配音字幕' : '待生成视频'}</span></div>
          {stage === 4 && previewVideo(shot) && !clipReady(shot) ? <p className="ink-wizard-review" role="status">正在预览已保留的视频，尚未确认用于当前镜头。可在“历史版本”中确认使用，或重新生成。</p> : null}
          {stage === 3 && shot.image_url && shot.image_stale ? <div className="ink-wizard-review" role="status"><strong>图片待确认</strong><p>{shot.image_stale_reason || '此图片此前被标记为待更新，未记录具体原因。请检查是否仍符合当前要求。'}</p><button type="button" disabled={disabled} onClick={() => void generateSavedShot(shot)}>按已保存分镜生成候选</button></div> : null}
          {stage >= 3 ? <><>{stage === 4 ? <p className="ink-wizard-motion">视频动作：{shot.video_settings?.motion ?? shot.motion}</p> : null}</><p className="ink-wizard-footnote">构图：{shot.camera}</p></> : null}
          <div className="ink-wizard-secondary">
            <button type="button" disabled={pending} onClick={() => void openHistory()}>历史版本</button>
            {stage === 4 ? <button type="button" disabled={disabled || !(shot.clip_url || shot.rendered_url)} onClick={() => setModal('video-edit')}>基于此视频调整</button> : null}
            {shot.image_url ? <button type="button" disabled={disabled} onClick={() => stage === 3 ? openShot(shot) : void run(() => onAction('video', shot.id))}>{stage === 4 ? nativeAudio ? '重新生成视频（含原声）' : '重新生成视频与配音字幕' : stage === 1 ? '重新生成参考图' : '修改图片'}</button> : null}
            <button type="button" disabled={disabled} onClick={() => { if(stage===4){setVideoDraft({mode:shot.video_settings?.mode || 'first_frame',end_shot_id:shot.video_settings?.end_shot_id || '',motion:shot.video_settings?.motion ?? shot.motion,camera:shot.video_settings?.camera ?? '',duration:shot.duration ?? 5});setModal('video');}else openShot(shot); }}><Settings2 size={14} />{stage===4?'重新生成设置':'调整'}</button>
            {stage < 4 ? <><input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="上传自己的图片" disabled={disabled} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ''; }} /><button type="button" disabled={disabled} onClick={() => fileInput.current?.click()}><Upload size={14} />上传图片</button></> : nativeAudio ? null : <button type="button" disabled={disabled} onClick={() => { setVoiceDraft(Object.fromEntries(p.characters.map(c => [c.id, p.voices?.[c.id] || (c.id === 'c1' ? 'zh-CN-YunjianNeural' : 'zh-CN-XiaoxiaoNeural')]))); setModal('voices'); }}>声音设置（可选）</button>}
          </div>
          {stage === 4 && shot.dialogues.length ? <details><summary>台词</summary>{shot.dialogues.map((d, i) => <p key={i}>{p.characters.find(c => c.id === d.character_id)?.name}：{d.text}</p>)}</details> : null}
        </div>
      </section>
      {stage === 4 ? <VideoEditPanel key={shot.id} open={modal === 'video-edit'} onOpen={() => setModal('video-edit')} onClose={() => setModal(null)} project={p} shot={shot} disabled={disabled} onUpdated={onUpdated} onWorkingChange={working => { setPending(working); onWorkingChange(working); }} /> : null}
      {stage >= 3 && shot.image_proposal ? <section className="ink-proposal" aria-label="候选图片对比"><h3>新候选 · 尚未采用</h3><div className="ink-proposal-grid"><figure>{shot.image_url ? <img src={shot.image_url} alt="当前使用的原图" /> : <p>尚无原图</p>}<figcaption>当前使用</figcaption></figure><figure><img src={shot.image_proposal.image_url} alt="待确认的新候选" /><figcaption>新候选 · {shot.image_proposal.mode === 'style' ? '画风修正' : shot.image_proposal.mode === 'detail' ? '局部调整' : '重新设计'}</figcaption></figure></div><p>检查人物、动作和画风，采用后才更新当前分镜。</p>{shot.image_proposal.change_warning ? <p role="status" className="ink-wizard-error">{shot.image_proposal.change_warning}</p> : null}{shot.image_proposal.style_check ? <p role="status">{shot.image_proposal.style_check.message}<br />识别特征：{shot.image_proposal.style_check.techniques.join("、") || "无法确定"}{shot.image_proposal.style_check.uncertainties.length ? <><br />待核对：{shot.image_proposal.style_check.uncertainties.join("；")}</> : null}</p> : null}<button type="button" disabled={disabled} onClick={() => void checkCandidateStyle()}>检查画风、景别与空间关系（调用视觉模型）</button><div className="ink-wizard-secondary ink-proposal-actions"><button type="button" disabled={disabled} onClick={() => openShot(shot, true)}>继续调整</button><button type="button" disabled={disabled} onClick={() => void chooseCandidate('discard')}>放弃候选</button><button type="button" className="ink-primary-button" disabled={disabled} onClick={() => void chooseCandidate('adopt')}>采用新图<Check size={16} /></button></div></section> : null}
    </> : <section className="ink-wizard-export">
      {p.final_url ? <><video controls preload="metadata" src={p.final_url} /><p>{p.final_stale ? '内容已修改，请重新合成；这里是上一次的成片。' : '短片已完成，可以预览和下载。'}</p></> : <div className="ink-wizard-empty"><Film size={40} /><p>{p.shots.length} 个片段已准备好，合成后即可观看。</p></div>}
      <label>背景音乐<select value={p.music_credit ? tracks.find(t => t.title === p.music_credit?.title)?.id || '__current' : ''} disabled={disabled} onChange={e => void run(() => onMusic(e.target.value))}><option value="">无背景音乐</option>{p.music_credit && !tracks.some(t => t.title === p.music_credit?.title) ? <option value="__current">{p.music_credit.title}（已保存）</option> : null}{tracks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
      {p.music_credit ? <small>{p.music_credit.license}</small> : <small>保留片段中的配音，不添加背景音乐。</small>}
    </section>}
    <footer className="ink-wizard-footer">{stage === 4 && (job?.action === 'sound' || job?.action === 'video') && ['failed', 'interrupted'].includes(job.state) ? <p role="alert" className="ink-wizard-error">{job.error || '配音字幕未完成，请检查服务连接后重试。'}</p> : null}<button type="button" className="ink-wizard-back" disabled={stage === 0 || pending || busy || storyboardEditing} onClick={() => go(stage - 1)}><ArrowLeft size={16} />上一步</button><span>{busy || pending ? stage === 4 && shot?.media_step === 'sound' ? '视频已完成，正在添加配音字幕…' : '处理中，完成后会自动更新' : storyboardEditing ? '请先保存或取消当前编辑' : `第 ${stage + 1} 步：${wizardSteps[stage]}`}</span>{reviewingCandidate ? <span>请在候选对比下方选择采用或放弃</span> : stage === 5 && p.final_url && !p.final_stale ? <a className="ink-primary-button" href={p.final_url} download>下载短片</a> : <button type={stage === 1 ? "submit" : "button"} form={stage === 1 ? "creative-settings-form" : undefined} className="ink-primary-button" disabled={primaryDisabled} onClick={stage === 1 ? undefined : primary}>{busy || pending ? <><LoaderCircle size={16} className="ink-job-spinner" />处理中…</> : <>{primaryLabel}<ArrowRight size={16} /></>}</button>}</footer>
    {deleteTarget ? <AdjustmentDialog title={`删除第 ${deleteTarget.number} 镜？`} close={() => { if (!pending) setDeleteTarget(null); }}>
      <div className="ink-wizard-dialog-body"><strong>{deleteTarget.shot.scene}</strong><p>删除后不参与后续生成和合成。已有图片、视频保留，可随时恢复分镜。</p>{error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}</div>
      <footer className="ink-delete-footer"><button type="button" autoFocus disabled={pending} onClick={() => setDeleteTarget(null)}>取消</button><button type="button" className="ink-primary-button" disabled={disabled} onClick={() => void deleteShot()}>{pending ? '正在删除…' : '删除分镜'}</button></footer>
    </AdjustmentDialog> : null}
    {modal === 'shot' && draft ? <AdjustmentDialog title="调整首帧画面" close={() => { if (!pending) setModal(null); }}><form onSubmit={e => { e.preventDefault(); void run(async () => {
        if (previewEditing) {
          const shotInput = { duration: draft.duration ?? 5, content: draft.content, scene: draft.scene, camera: draft.camera, motion: draft.motion, character_ids: draft.character_ids, scene_id: draft.scene_id || null, prop_ids: draft.prop_ids || [], dialogues: draft.dialogues.filter(d => d.text.trim()) };
          onUpdated(await api<Project>(`/projects/${p.id}/shots/${draft.id}/preview`, json('POST', { mode: editMode, instruction: detailInstruction, shot: shotInput })));
          setModal(null); setRequestedStage(3); return;
        }
        if (editPlan?.changed) await onSave(draft.id, { duration: draft.duration ?? 5, content: draft.content, scene: draft.scene, camera: draft.camera, motion: draft.motion, character_ids: draft.character_ids, scene_id: draft.scene_id || null, prop_ids: draft.prop_ids || [], dialogues: draft.dialogues.filter(d => d.text.trim()) }); setModal(null);
        if (editPlan?.action) {
          setRequestedStage(editPlan.action === 'image' ? 3 : 4);
          try { await onAction(editPlan.action, draft.id); }
          catch (e) { throw new Error(`调整已保存，但生成未启动。请使用底部按钮重试。${e instanceof Error ? e.message : ''}`); }
        } else if (editPlan?.label === '保存并确定人物画风') { setRequestedStage(1); }
        else { setNotice(editPlan?.hint || '调整已保存'); }
      }); }}>
      <div className="ink-wizard-dialog-body">{stage >= 3 ? <><fieldset><legend>怎么修改？</legend><label><input type="radio" name="image-mode" checked={editMode === 'style'} disabled={!draft.image_url} onChange={() => setEditMode('style')} />修正画风 · 保留画面内容</label><label><input type="radio" name="image-mode" checked={editMode === 'detail'} disabled={!draft.image_url} onChange={() => setEditMode('detail')} />局部调整 · 小动作、表情、细节</label><label><input type="radio" name="image-mode" checked={editMode === 'redesign'} onChange={() => setEditMode('redesign')} />重新设计画面 · 姿势、互动、构图</label></fieldset><p className="ink-wizard-footnote">{editMode === 'style' ? '按项目画风重绘，尽量保留人物、姿势和构图。' : editMode === 'detail' ? '基于当前使用的图片，只改指定部位。支持抬手、转头、视线、持物方式；整体转身或大幅站位变化请选择重新设计。' : '按首帧姿势、素材和画风重画。后续动作请到视频页调整。'}</p></> : null}
      {stage >= 3 && editMode === 'style' ? <><p>目标画风：{p.creative_settings?.style || '请先在创作设定中选择画风'}</p><label>补充要求（选填）<textarea value={detailInstruction} maxLength={1000} rows={2} onChange={e => setDetailInstruction(e.target.value)} placeholder="例如：屋檐和衣纹用大块墨色概括，减少精细描线" /></label></> : stage >= 3 && editMode === 'detail' ? <label>想改哪里？<textarea required value={detailInstruction} onChange={e => setDetailInstruction(e.target.value)} maxLength={1000} placeholder="例如：书生右手抬到胸前，手掌向上；左手仍拿书卷，其他保持不变" /></label> : <>{(['content', 'scene', 'camera'] as const).map(key => <label key={key}>{{content:'首帧画面（静态姿势）',scene:'场景',camera:'构图'}[key]}<textarea required={key === 'content'} value={draft[key]} rows={2} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
      {p.creative_settings ? <><label>使用场景<select required value={draft.scene_id || ''} onChange={e=>{const scene=p.creative_settings!.scenes.find(x=>x.id===e.target.value);setDraft({...draft,scene_id:e.target.value,scene:scene?.name||draft.scene});}}><option value="">请选择已确认场景</option>{p.creative_settings.scenes.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><fieldset><legend>使用道具</legend>{p.creative_settings.props.length ? p.creative_settings.props.map(x=><label key={x.id} className="ink-wizard-check"><input type="checkbox" checked={(draft.prop_ids||[]).includes(x.id)} onChange={e=>setDraft({...draft,prop_ids:e.target.checked?[...(draft.prop_ids||[]),x.id]:(draft.prop_ids||[]).filter(id=>id!==x.id)})} />{x.name}</label>):<span>本剧未设置关键道具</span>}</fieldset></>:null}
      <fieldset><legend>出场人物</legend>{p.characters.map(c => <label className="ink-wizard-check" key={c.id}><input type="checkbox" checked={draft.character_ids.includes(c.id)} onChange={e => setDraft({ ...draft, character_ids: e.target.checked ? [...draft.character_ids, c.id] : draft.character_ids.filter(id => id !== c.id), dialogues: e.target.checked ? draft.dialogues : draft.dialogues.filter(d => d.character_id !== c.id) })} />{c.name}</label>)}</fieldset>
      <fieldset><legend>台词</legend>{draft.dialogues.map((d, i) => <div className="ink-wizard-dialogue" key={i}><select aria-label={`第${i + 1}句角色`} value={d.character_id} onChange={e => setDraft({ ...draft, dialogues: draft.dialogues.map((v, n) => n === i ? { ...v, character_id: e.target.value } : v) })}>{p.characters.filter(c => draft.character_ids.includes(c.id)).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select><input aria-label={`第${i + 1}句台词`} value={d.text} onChange={e => setDraft({ ...draft, dialogues: draft.dialogues.map((v, n) => n === i ? { ...v, text: e.target.value } : v) })} /><button type="button" aria-label="删除台词" onClick={() => setDraft({ ...draft, dialogues: draft.dialogues.filter((_, n) => n !== i) })}>×</button></div>)}<button type="button" disabled={!draft.character_ids.length || draft.dialogues.length >= 8} onClick={() => setDraft({ ...draft, dialogues: [...draft.dialogues, { character_id: draft.character_ids[0], text: '' }] })}>添加一句台词</button></fieldset>
      </>}<p className="ink-wizard-footnote">{stage >= 3 ? '生成候选会调用模型；原图和已有视频保持不变，采用后才更新。' : editPlan?.hint}</p>{error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}</div><footer><button className="ink-primary-button" disabled={disabled || (stage >= 3 && editMode === 'detail' ? !detailInstruction.trim() : !previewEditing && !editPlan?.changed && !editPlan?.action)}>{pending ? '正在提交…' : stage >= 3 && editMode === 'style' ? '生成画风修正版' : stage >= 3 && editMode === 'detail' ? '生成局部调整预览' : previewEditing ? '生成新画面预览' : editPlan?.label || '保存调整'}</button></footer>
    </form></AdjustmentDialog> : null}
    {modal === 'video-history' ? <AdjustmentDialog title={`第 ${shot ? p.shots.indexOf(shot) + 1 : ''} 镜 · 历史视频`} close={() => setModal(null)}><div className="ink-wizard-dialog-body"><p>播放对比历史视频，采用时保留该版本的声音，用于当前镜头和最终合成。</p>{historyLoading ? <p role="status">正在加载视频…</p> : videoHistoryItems.length ? <div className="ink-history-grid">{videoHistoryItems.map(item => <article key={item.video}><video controls preload="metadata" src={item.video_url} aria-label={`${item.current ? '当前使用' : '历史'}${item.kind === 'edited' ? '局部调整版' : item.kind === 'subtitled' ? '配音字幕版' : '原视频'}`} /><strong>{item.current ? item.needs_confirmation ? '待确认 · ' : '当前使用 · ' : ''}{item.kind === 'edited' ? '局部调整版' : item.kind === 'subtitled' ? '配音字幕版' : '原视频'}</strong><small>{new Date(item.created * 1000).toLocaleString('zh-CN')}</small><div><a href={item.video_url} target="_blank" rel="noreferrer">打开视频</a><a href={item.video_url} download>下载视频</a><button type="button" disabled={disabled || (item.current && !item.needs_confirmation)} onClick={() => void adoptVideo(item)}>{item.needs_confirmation ? '确认使用此版本' : item.current ? '当前使用' : '采用此版本'}</button></div></article>)}</div> : <p>暂无已保存的历史视频。</p>}{error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}</div></AdjustmentDialog> : null}
    {modal === 'history' ? <AdjustmentDialog title="历史版本" close={() => { if (!pending) setModal(null); }}><div className="ink-wizard-dialog-body"><p>放弃候选不会删除历史图片。</p>{shot?.image_undo ? <div className="ink-wizard-secondary"><button type="button" disabled={disabled} onClick={() => void chooseCandidate('undo-image')}>恢复上一张</button><span className="ink-wizard-footnote">同时恢复当时的镜头内容，已有视频需更新。</span></div> : null}{historyLoading ? <p role="status">正在加载…</p> : historyItems.length ? <div className="ink-history-grid">{historyItems.map(item => <article key={item.image}><a href={item.image_url} target="_blank" rel="noreferrer" aria-label="查看历史图片大图"><img src={item.image_url} alt="历史分镜图" loading="lazy" /></a><strong>{item.status === 'current' ? '当前使用' : item.status === 'candidate' ? '候选待确认' : item.status === 'discarded' ? '已放弃 · 可恢复' : '历史版本'}</strong><small>{new Date(item.created * 1000).toLocaleString('zh-CN')}</small>{!item.has_snapshot ? <small>旧版本，未记录当时文字</small> : null}<div><a href={item.image_url} target="_blank" rel="noreferrer">查看</a><a href={item.image_url} download>下载</a><button type="button" disabled={disabled || item.status === 'current'} onClick={() => void restoreImage(item)}>{item.status === 'current' ? '正在使用' : '采用此图'}</button></div></article>)}</div> : <p>暂无可查看的历史图片。</p>}{error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}<p className="ink-wizard-footnote">此前已放弃且未记录所属镜头的图片暂无法自动找回。</p></div></AdjustmentDialog> : null}
    {modal === 'video' && shot ? <AdjustmentDialog title="视频模式与动作" close={() => {if(!pending)setModal(null);}}><form onSubmit={e=>{e.preventDefault();void run(async()=>{
      onUpdated(await api<Project>(`/projects/${p.id}/shots/${shot.id}/video-settings`,json('PUT',videoDraft)));
      await onAction('video',shot.id);setModal(null);
    });}}><div className="ink-wizard-dialog-body"><label>生成模式<select value={videoDraft.mode} onChange={e=>{const mode=e.target.value;const ds=p.video_modes?.find(x=>x.id===mode)?.durations || [5];setVideoDraft({...videoDraft,mode,duration:ds.includes(videoDraft.duration)?videoDraft.duration:ds[0]});}}>{(p.video_modes || [{id:'first_frame',label:'首帧生成',supported:true}]).map(x=><option key={x.id} value={x.id} disabled={!x.supported}>{x.label}{!x.supported?' · 请先配置模型':''}</option>)}</select></label><p className="ink-wizard-footnote">{videoDraft.mode==='reference'?'使用本片段已确认的角色和场景图，首帧构图由模型生成。':videoDraft.mode==='start_end_frame'?'从当前画面过渡到所选尾帧。跨场景切换时请谨慎使用。':'以当前分镜图作为视频起始画面。'}</p>{videoDraft.mode==='start_end_frame'?<label>尾帧画面<select value={videoDraft.end_shot_id} onChange={e=>setVideoDraft({...videoDraft,end_shot_id:e.target.value})}><option value="">下一片段画面（默认）</option>{p.shots.filter(x=>x.id!==shot.id&&x.image_url&&!x.image_stale).map(x=><option key={x.id} value={x.id}>第{p.shots.indexOf(x)+1}段 · {x.scene}</option>)}</select></label>:null}<label>人物与环境动作<textarea required maxLength={6000} rows={4} value={videoDraft.motion} onChange={e=>setVideoDraft({...videoDraft,motion:e.target.value})}/></label><label>运镜<textarea maxLength={500} rows={2} placeholder="例如：镜头缓缓推近，或固定镜头" value={videoDraft.camera} onChange={e=>setVideoDraft({...videoDraft,camera:e.target.value})}/></label><label>视频时长<select value={videoDraft.duration} onChange={e=>setVideoDraft({...videoDraft,duration:Number(e.target.value)})}>{(p.video_modes?.find(x=>x.id===videoDraft.mode)?.durations || p.video_durations || [5]).map(n=><option key={n} value={n}>{n}秒</option>)}</select></label>{error?<p role="alert" className="ink-wizard-error">{error}</p>:null}</div><footer><button className="ink-primary-button" disabled={disabled||!videoDraft.motion.trim()}>{pending?'正在提交…':'按设置生成视频'}</button></footer></form></AdjustmentDialog>:null}
    {modal === 'voices' ? <AdjustmentDialog title="配音设置" close={() => { if (!pending) setModal(null); }}><div className="ink-wizard-dialog-body">{p.characters.map(c => <label key={c.id}>{c.name}<select value={voiceDraft[c.id]} onChange={e => setVoiceDraft({ ...voiceDraft, [c.id]: e.target.value })}><option value="zh-CN-YunjianNeural">云健 · 男声</option><option value="zh-CN-XiaoxiaoNeural">晓晓 · 女声</option></select></label>)}<p>保存后，已有配音片段需要重新生成。</p>{error ? <p role="alert">{error}</p> : null}</div><footer><button type="button" className="ink-primary-button" disabled={disabled} onClick={() => void run(async () => { await onVoices(voiceDraft); setModal(null); })}>保存音色</button></footer></AdjustmentDialog> : null}
  </div>;
}
