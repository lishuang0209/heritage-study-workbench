'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, LoaderCircle, Pencil, Plus, Trash2, Undo2, X } from 'lucide-react';
import { api, json, type DeletedShot, type Project, type Shot } from './ink-shared';
import { NARRATOR, speakerName } from './dialogue-state';
import { newShotFields, reconcileShotFields, shotFields, shotFieldsChanged, storyboardImageStatus, type ShotFields } from './storyboard-state';

type MotionRow = { shotType: string; duration: string; content: string };
type Editor = { motions: MotionRow[] | null; id: string | null; initial: ShotFields; draft: ShotFields; referencesAdjusted: boolean };
type Props = {
  project: Project;
  disabled: boolean;
  onGenerate: () => void;
  onEditingChange: (editing: boolean) => void;
  onSave: (id: string, data: ShotFields) => Promise<Project>;
  onUpdated: (project: Project) => Project;
  onDelete: (shot: Shot, number: number) => void;
  onRestore: (item: DeletedShot) => void;
};

const shotTypes = ['远景', '全景', '中景', '中近景', '近景', '过肩近景', '特写', '大特写'];
function motionRows(shot: ShotFields): MotionRow[] {
  const parts = [...shot.motion.matchAll(/分镜\s*\d+\s*[：:]\s*\[([\d.]+)秒\]\s*([\s\S]*?)(?=分镜\s*\d+\s*[：:]|$)/g)];
  const rows = parts.length ? parts.map(match => ({ duration: match[1], content: match[2].trim() }))
    : [{ duration: String(shot.duration ?? 5), content: shot.motion || shot.content }];
  return rows.map(row => {
    const match = row.content.match(/^(过肩近景|大特写|中近景|远景|全景|中景|近景|特写)[，,、：: ]*/);
    const cameraType = !parts.length ? shot.camera.match(/过肩近景|大特写|中近景|远景|全景|中景|近景|特写/)?.[0] : '';
    return { ...row, shotType: cameraType || match?.[1] || '', content: match ? row.content.slice(match[0].length) : row.content };
  });
}

export default function StoryboardEditor({ project: p, disabled, onGenerate, onEditingChange, onSave, onUpdated, onDelete, onRestore }: Props) {
  const [editor, setEditor] = useState<Editor | null>(null);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState('');
  const [savedId, setSavedId] = useState('');
  const [message, setMessage] = useState('');
  const container = useRef<HTMLElement>(null);
  const editorForm = useRef<HTMLFormElement>(null);
  const adding = !!editor && editor.id === null;
  const dirty = !!editor && shotFieldsChanged(editor.initial, editor.draft);
  const deleted = [...(p.deleted_shots || [])].sort((a, b) => b.deleted_at - a.deleted_at);
  const draft = editor?.draft;
  const editorKey = editor ? editor.id || 'new' : null;
  const canRestore = p.shots.length < 30;
  const durations = p.video_durations || [5];
  const totalDuration = p.shots.reduce((sum, shot) => sum + (shot.duration ?? 5), 0);

  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);
  useEffect(() => {
    if (!editorKey) return;
    editorForm.current?.scrollIntoView({ block: 'nearest', behavior: 'auto' });
    editorForm.current?.querySelector<HTMLSelectElement>('select[aria-label="镜头时长"]')?.focus({ preventScroll: true });
  }, [editorKey]);

  const begin = (shot?: Shot) => {
    if (disabled || editor) return;
    const initial = shot ? shotFields(shot) : newShotFields(p);
    const draft = reconcileShotFields(p, initial);
    setEditor({ motions: motionRows(draft), id: shot?.id || null, initial, draft, referencesAdjusted: shotFieldsChanged(initial, draft) });
    setError(''); setMessage(''); onEditingChange(true);
  };
  const finish = (id?: string) => {
    setEditor(null); setError(''); onEditingChange(false);
    requestAnimationFrame(() => {
      const buttons = container.current?.querySelectorAll<HTMLButtonElement>('button[data-edit-shot]');
      const target = Array.from(buttons || []).find(button => button.dataset.editShot === id);
      (target || container.current?.querySelector<HTMLButtonElement>('[data-add-shot]'))?.focus({ preventScroll: true });
    });
  };
  const cancel = () => {
    if (savingRef.current) return;
    if (dirty && !window.confirm('放弃尚未保存的分镜修改？')) return;
    finish(editor?.id || undefined);
  };
  const change = (patch: Partial<ShotFields>) => setEditor(current => current ? { ...current, draft: { ...current.draft, ...patch } } : current);
  const setMotions = (motions: MotionRow[]) => setEditor(current => {
    if (!current) return current;
    const motion = motions.length === 1 ? `${motions[0].shotType ? motions[0].shotType + '，' : ''}${motions[0].content}` : '分镜列表：\n' + motions.map((row, i) => `分镜${i + 1}：[${row.duration}秒] ${row.shotType ? row.shotType + '，' : ''}${row.content}`).join('\n');
    const duration = Math.round(motions.reduce((sum, row) => sum + (Number(row.duration) || 0), 0) * 100) / 100;
    const camera = motions.length === 1 && motions[0].shotType
      ? motions[0].shotType + '，' + current.draft.camera.replace(/^(过肩近景|大特写|中近景|远景|全景|中景|近景|特写)[，,、：: ]*/, '')
      : current.draft.camera;
    return { ...current, motions, draft: { ...current.draft, motion, duration, camera } };
  });
  const changeMotion = (index: number, patch: Partial<MotionRow>) => {
    if (editor?.motions) setMotions(editor.motions.map((row, i) => i === index ? { ...row, ...patch } : row));
  };
  const motionTotal = editor?.motions?.reduce((sum, row) => sum + (Number(row.duration) || 0), 0);
  const motionInvalid = !!editor?.motions?.some(row => !row.content.trim() || !Number.isFinite(Number(row.duration)) || Number(row.duration) <= 0) || (draft?.motion.length ?? 0) > 6000;
  const submit = async () => {
    if (!editor || disabled || savingRef.current || motionInvalid || !dirty || !editor.draft.content.trim() || !Number.isInteger(editor.draft.duration) || editor.draft.duration! < 2 || editor.draft.duration! > 15) return;
    savingRef.current = true; setSaving(true); setError('');
    try {
      const data = shotFields(editor.draft);
      data.content = data.content.trim();
      const result = editor.id ? await onSave(editor.id, data)
        : onUpdated(await api<Project>(`/projects/${p.id}/shots`, json('POST', data)));
      const saved = result.shots.find(shot => shot.id === editor.id) || result.shots.at(-1)!;
      const number = result.shots.indexOf(saved) + 1;
      setSavedId(saved.id);
      setMessage(`第 ${number} 镜已保存。${saved.image_url && saved.image_stale ? '已有图片待更新，请在下一步重新生成。' : saved.clip_stale ? '已有视频待更新，分镜图保留。' : '确认全部分镜后，点击底部按钮制作画面。'}`);
      finish(saved.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存失败，请重试');
    } finally { savingRef.current = false; setSaving(false); }
  };

  const chooseDraft = async (choice: 'adopt' | 'discard') => {
    if (disabled || savingRef.current) return;
    if (choice === 'adopt' && !window.confirm('采用新分镜后需重新制作画面和视频。旧分镜素材会保留在项目存档中。继续？')) return;
    savingRef.current = true; setSaving(true); setError('');
    try { onUpdated(await api<Project>(`/projects/${p.id}/storyboard-draft/${choice}`, json('POST', {}))); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败'); }
    finally { savingRef.current = false; setSaving(false); }
  };

  const form = editor && draft ? <form ref={editorForm} id="ink-storyboard-editor" className="ink-board-form" onSubmit={event => { event.preventDefault(); void submit(); }}>
    <div className="ink-board-form-heading"><strong>{adding ? `添加第 ${p.shots.length + 1} 镜` : `编辑第 ${p.shots.findIndex(shot => shot.id === editor.id) + 1} 片段`}</strong><span>{dirty ? '未保存' : '修改后保存'}</span><button type="button" aria-label="关闭分镜编辑" disabled={saving} onClick={cancel}><X size={17} /></button></div>
    {editor.referencesAdjusted ? <p className="ink-board-reference-note">已移除失效的人物或道具引用，请核对场景后保存。</p> : null}
    <fieldset disabled={disabled || saving} className="ink-board-fields">
      <section className="ink-board-wide ink-base-edit-table">
        <div className="ink-base-edit-summary">片段时长：<strong>{motionTotal} 秒</strong><span>随各镜头时长自动汇总</span></div>
        <div className="ink-base-table-wrap"><table className="ink-base-table"><thead><tr><th>#</th><th>景别</th><th>时长（秒）</th><th>分镜内容描述</th><th></th></tr></thead><tbody>
        {editor.motions?.map((row, index) => <tr key={index}>
          <td>{index + 1}</td><td><select aria-label={`镜头 ${index + 1} 景别`} value={row.shotType} onChange={event => changeMotion(index, { shotType: event.target.value })}><option value="">未指定</option>{shotTypes.map(type => <option key={type}>{type}</option>)}</select></td>
          <td><input aria-label={`镜头 ${index + 1} 时长`} type="number" required min="1" max="15" step="1" value={row.duration} onChange={event => changeMotion(index, { duration: event.target.value })} /></td>
          <td><textarea aria-label={`镜头 ${index + 1} 内容`} required rows={3} maxLength={6000} value={row.content} onChange={event => changeMotion(index, { content: event.target.value })} /></td>
          <td><button type="button" aria-label={`删除镜头 ${index + 1}`} disabled={editor.motions!.length <= 1} onClick={() => setMotions(editor.motions!.filter((_, i) => i !== index))}><Trash2 size={15} /></button></td>
        </tr>)}</tbody></table></div>
        <button disabled={!draft.motion.startsWith('分镜列表：')} title="独立分镜请使用顶部添加分镜" className="ink-base-add" type="button" onClick={() => setMotions([...(editor.motions || []), { shotType: '近景', duration: '1', content: '' }])}><Plus size={14} />插入新分镜点</button>
        {(motionTotal ?? 0) < 2 || (motionTotal ?? 0) > 15 || !Number.isInteger(motionTotal) ? <p role="alert">片段总时长需为 2–15 秒的整数，请调整镜头时长。</p> : !durations.includes(motionTotal!) ? <p>分镜可保存；当前视频模型支持 {durations.join('、')} 秒，生成视频前需调整时长或更换模型。</p> : null}
        {draft.motion.length > 6000 ? <p role="alert">内容超过 6000 字，请精简后保存。</p> : null}
      </section>
      <label className="ink-board-wide">首帧画面<textarea required maxLength={3000} rows={3} value={draft.content} onChange={event => change({ content: event.target.value })} /></label>
      <label>首帧构图（仅用于出图）<textarea maxLength={1000} rows={2} value={draft.camera} placeholder="例如：中景、平视，人物分立左右" onChange={event => change({ camera: event.target.value })} /></label>
      <label>场景描述<input maxLength={2000} value={draft.scene} placeholder="例如：古寺门前，傍晚小雨" onChange={event => change({ scene: event.target.value })} /></label>
      {p.creative_settings ? <label>场景素材<select required value={draft.scene_id || ''} onChange={event => {
        const scene = p.creative_settings!.scenes.find(item => item.id === event.target.value);
        change({ scene_id: scene?.id || null, scene: scene?.name || draft.scene });
      }}><option value="">选择场景</option>{p.creative_settings.scenes.map(scene => <option value={scene.id} key={scene.id}>{scene.name}</option>)}</select></label> : null}
      <fieldset className="ink-board-choice"><legend>出场人物</legend><div>{p.characters.length ? p.characters.map(character => <label key={character.id}><input type="checkbox" checked={draft.character_ids.includes(character.id)} onChange={event => change({
        character_ids: event.target.checked ? [...draft.character_ids, character.id] : draft.character_ids.filter(id => id !== character.id),
        dialogues: event.target.checked ? draft.dialogues : draft.dialogues.filter(line => line.character_id !== character.id),
      })} />{character.name}</label>) : <span>无人出镜，可使用旁白讲解</span>}</div></fieldset>
      <fieldset className="ink-board-choice"><legend>使用道具</legend><div>{p.creative_settings?.props.length ? p.creative_settings.props.map(prop => <label key={prop.id}><input type="checkbox" checked={(draft.prop_ids || []).includes(prop.id)} onChange={event => change({ prop_ids: event.target.checked ? [...(draft.prop_ids || []), prop.id] : (draft.prop_ids || []).filter(id => id !== prop.id) })} />{prop.name}</label>) : <span>无道具</span>}</div></fieldset>
      <fieldset className="ink-board-dialogues ink-board-wide"><legend>台词与旁白（可选）</legend>{draft.dialogues.map((line, index) => <div key={index}>
        <select aria-label={`第 ${index + 1} 句说话人`} value={line.character_id} onChange={event => change({ dialogues: draft.dialogues.map((item, i) => i === index ? { ...item, character_id: event.target.value } : item) })}><option value={NARRATOR}>旁白（画外音）</option>{p.characters.filter(character => draft.character_ids.includes(character.id)).map(character => <option value={character.id} key={character.id}>{character.name}</option>)}</select>
        <input required maxLength={300} aria-label={`第 ${index + 1} 句台词`} value={line.text} placeholder="输入台词" onChange={event => change({ dialogues: draft.dialogues.map((item, i) => i === index ? { ...item, text: event.target.value } : item) })} />
        <button type="button" aria-label={`删除第 ${index + 1} 句台词`} onClick={() => change({ dialogues: draft.dialogues.filter((_, i) => i !== index) })}><X size={16} /></button>
      </div>)}<button type="button" className="ink-board-text-action" disabled={draft.dialogues.length >= 8} onClick={() => change({ dialogues: [...draft.dialogues, { character_id: draft.character_ids[0] || NARRATOR, text: '' }] })}><Plus size={14} />{draft.character_ids.length?'添加台词或旁白':'添加旁白'}</button></fieldset>
    </fieldset>
    {error ? <p role="alert" className="ink-wizard-error">{error}</p> : null}
    <div className="ink-board-form-footer"><span>保存文字后，在下一步生成画面。</span><button type="button" disabled={saving} onClick={cancel}>取消</button><button type="submit" className="ink-primary-button" disabled={disabled || saving || motionInvalid || !dirty || !draft.content.trim() || (!Number.isInteger(draft.duration) || draft.duration! < 2 || draft.duration! > 15)}>{saving ? <><LoaderCircle size={15} className="ink-job-spinner" />保存中…</> : <><Check size={15} />{adding ? '保存新分镜' : '保存修改'}</>}</button></div>
  </form> : null;

  return <section ref={container} className="ink-wizard-story ink-board" aria-label="分镜列表">
    {error && !editor ? <p role="alert" className="ink-wizard-error">{error}</p> : null}
    {p.storyboard_draft ? <section className="ink-board-draft" aria-label="新分镜草稿"><h3>新分镜 · 待采用</h3><p>下方原分镜保持不变。采用新分镜后，再制作画面。</p><ol>{p.storyboard_draft.shots.map((s, i) => <li key={i}><strong>第 {i + 1} 镜 · {s.duration ?? 5} 秒 · {s.scene}</strong><p>{s.content}</p><p>动作：{s.motion}</p><p>构图：{s.camera}</p>{s.dialogues.map((d,j)=><p key={j}>{speakerName(p.storyboard_draft?.characters || [],d.character_id)}：{d.text}</p>)}</li>)}</ol><div className="ink-board-row-actions"><button disabled={disabled || saving || !!editor} onClick={() => void chooseDraft('discard')}>放弃草稿</button><button className="ink-primary-button" disabled={disabled || saving || !!editor} onClick={() => void chooseDraft('adopt')}>采用新分镜</button></div></section> : null}
    <div className="ink-board-toolbar"><div><strong>{p.shots.length} 个分镜</strong><span>预计 {totalDuration} 秒 · 新分镜逐镜出图、逐镜生成视频</span></div><button type="button" disabled={disabled || saving || !!editor || !!p.storyboard_draft} onClick={onGenerate}>{p.shots.length ? '重新生成分镜' : '生成分镜'}</button><button type="button" data-add-shot disabled={disabled || !!editor || p.shots.length >= 30} title={p.shots.length >= 30 ? '当前最多 30 个分镜' : undefined} onClick={() => begin()}><Plus size={16} />{p.shots.length >= 30 ? '已达 30 镜上限' : '添加分镜'}</button></div>
    {message ? <p role="status" className="ink-board-saved"><Check size={15} />{message}</p> : null}
    {deleted.length ? <div className="ink-storyboard-undo"><span>已删除 {deleted.length} 个分镜，可恢复</span><button type="button" disabled={disabled || !!editor || !canRestore} title={!canRestore ? '最多保留 6 镜，请先删除一镜' : undefined} onClick={() => onRestore(deleted[0])}><Undo2 size={14} />撤销上次删除</button></div> : null}
    <div className="ink-base-episode"><strong>第 1 集：{p.title}</strong><span>总计 {totalDuration}s</span></div>
    <div className="ink-base-segments">{p.shots.map((shot, index) => <article key={shot.id}>
      <header className="ink-base-segment-bar"><span>#{index + 1}</span><strong>{p.creative_settings?.scenes.find(scene => scene.id === shot.scene_id)?.name || shot.scene || '未命名场景'}</strong>
        <div>{shot.character_ids.map(id => <span className="ink-base-person" key={id}>{p.characters.find(c => c.id === id)?.name || id}</span>)}</div><span className="ink-base-time">{editor?.id === shot.id ? motionTotal : shot.duration ?? 5}s</span>
        <button type="button" data-edit-shot={shot.id} disabled={disabled || !!editor} onClick={() => begin(shot)}><Pencil size={14} />编辑</button><button type="button" disabled={disabled || !!editor || p.shots.length <= 1} onClick={() => onDelete(shot, index + 1)} aria-label={`删除片段 ${index + 1}`}><Trash2 size={14} /></button>
      </header>
      {editor?.id === shot.id ? form : <>
        <div className="ink-base-table-wrap"><table className="ink-base-table"><thead><tr><th>#</th><th>景别</th><th>时长</th><th>分镜内容描述</th></tr></thead><tbody>{motionRows(shot).map((row, i) => <tr key={i}><td>{i + 1}</td><td><span className="ink-base-shot-type" data-type={row.shotType}>{row.shotType || '未指定'}</span></td><td>{row.duration}s</td><td>{row.content}</td></tr>)}</tbody></table></div>
        <details className="ink-segment-start"><summary>首帧与素材设定 · {storyboardImageStatus(shot)}{savedId === shot.id ? ' · 已保存' : ''}</summary><p>首帧：{shot.content}</p><p>构图：{shot.camera}</p><p>道具：{(shot.prop_ids || []).map(id => p.creative_settings?.props.find(prop => prop.id === id)?.name || id).join('、') || '无'}</p>{shot.dialogues.map((line, i) => <p key={i}>{speakerName(p.characters,line.character_id)}：{line.text}</p>)}</details>
      </>}
    </article>)}</div>
    {!p.shots.length && !adding ? <p className="ink-board-empty">点击“生成分镜”自动规划片段，或手动添加。</p> : null}
    {adding ? form : null}
    {deleted.length ? <details className="ink-deleted-shots"><summary><ChevronDown size={14} />已删除分镜（{deleted.length}）</summary><ul>{deleted.map(item => <li key={item.id}><div><span>原第 {item.index + 1} 镜 · {item.scene || '未命名场景'}</span><p title={item.content}>{item.content}</p></div><button type="button" disabled={disabled || !!editor || !canRestore} title={!canRestore ? '最多保留 6 镜，请先删除一镜' : undefined} aria-label={`恢复原第 ${item.index + 1} 镜：${item.scene}`} onClick={() => onRestore(item)}>恢复分镜</button></li>)}</ul></details> : null}
  </section>;
}
