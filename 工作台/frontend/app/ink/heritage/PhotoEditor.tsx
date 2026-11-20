'use client';

import { ImageIcon, Upload, X } from 'lucide-react';
import Select from '@/components/Select';
import { useId, useRef, useState, type PointerEvent } from 'react';
import { point, selectPhotoCredits, type Mark, type Photo } from './state';
import './photo-editor-layout.css';

type PhotoEditorProps = {
  slot: 'panorama' | 'detail';
  photo: Photo | null;
  disabled: boolean;
  dirty: boolean;
  onChange: (photo: Photo | null) => void;
  onUpload: (file: File) => void;
  onGenerate?: () => void;
  canGenerate?: boolean;
  derivedStale?: boolean;
};

const displayModes = { contain: '完整保留照片', cover: '横屏裁切照片（16:9）' } as const;
const coordinates = [
  ['x', '起点横向'], ['y', '起点纵向'], ['x2', '终点横向'], ['y2', '终点纵向'],
] as const;

export default function PhotoEditor({ slot, photo, disabled, dirty, onChange, onUpload, onGenerate, canGenerate, derivedStale }: PhotoEditorProps) {
  const id = useId();
  const uploadInput = useRef<HTMLInputElement>(null);
  const previewDialog = useRef<HTMLDialogElement>(null);
  const start = useRef<Pick<Mark, 'x' | 'y'> | null>(null);
  const [kind, setKind] = useState<Mark['kind']>(photo?.mark?.kind ?? 'rectangle');
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewError, setPreviewError] = useState(false);
  const detail = slot === 'detail';
  const title = detail ? '同一构件特写' : '现场定位图';
  const uploadLabel = detail ? '另传实拍特写' : photo ? '替换照片' : '上传实拍照片';
  const mark = photo?.mark;
  const linked = Boolean(photo?.derived_from);
  const manualCredit = photo?.credit_kind === 'self' || photo?.credit_kind === 'authorized';
  const hasCredit = Boolean(photo?.source.trim() && photo.author.trim() && photo.license.trim());

  function markStart(event: PointerEvent<SVGSVGElement>) {
    if (disabled || linked) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    start.current = point(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect());
  }

  function markTarget(event: PointerEvent<SVGSVGElement>) {
    if (!photo || !start.current || disabled || linked) return;
    const origin = start.current;
    const end = point(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect());
    if (event.type === 'pointerup') start.current = null;
    if (event.type === 'pointermove' || Math.abs(end.x - origin.x) + Math.abs(end.y - origin.y) > .02) {
      onChange({ ...photo, mark: { kind, ...origin, x2: end.x, y2: end.y } });
    }
  }

  function openPreview() {
    setPreviewError(false);
    setPreviewOpen(true);
    previewDialog.current?.showModal();
  }

  return (
    <section className="study-photo" aria-labelledby={`${id}-title`}>
      <header className="study-photo-heading">
        <div><h3 id={`${id}-title`}>{title}</h3><span data-required={!detail}>{detail ? '可选' : '必填'}</span></div>
        {detail && photo ? <button type="button" disabled={disabled} onClick={() => onChange(null)}>移除特写</button> : null}
        {!detail ? <button type="button" disabled={disabled} onClick={() => uploadInput.current?.click()}><Upload size={14} aria-hidden="true" />{uploadLabel}</button> : null}
      </header>
      <input ref={uploadInput} type="file" accept="image/jpeg,image/png,image/webp" className="study-photo-file" hidden disabled={disabled} aria-label={uploadLabel} onChange={event => {
        const file = event.currentTarget.files?.[0];
        if (file) onUpload(file);
        event.currentTarget.value = '';
      }} />
      <div className="study-photo-layout">
        <figure className="study-photo-figure">
          {photo ? (
            <div className="study-mark-canvas">
              <img src={photo.url} alt={`${title}原照`} />
              <svg className={linked ? 'study-linked-mark' : undefined} viewBox="0 0 1 1" preserveAspectRatio="none" aria-label={linked ? '从定位图继承的目标标注' : '在照片上标注目标'} onPointerDown={markStart} onPointerMove={markTarget} onPointerUp={markTarget} onPointerCancel={() => { start.current = null; }}>
                <defs><marker id={id} markerWidth=".055" markerHeight=".055" refX=".045" refY=".0275" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L.05,.0275 L0,.055" fill="none" stroke="#af2424" strokeWidth=".009" /></marker></defs>
                {mark?.kind === 'rectangle' ? <rect x={Math.min(mark.x, mark.x2)} y={Math.min(mark.y, mark.y2)} width={Math.abs(mark.x2 - mark.x)} height={Math.abs(mark.y2 - mark.y)} fill="none" stroke="#af2424" strokeWidth=".007" /> : mark ? <line x1={mark.x} y1={mark.y} x2={mark.x2} y2={mark.y2} stroke="#af2424" strokeWidth=".007" markerEnd={`url(#${id})`} /> : null}
              </svg>
            </div>
          ) : <div className="study-photo-empty"><ImageIcon size={26} aria-hidden="true" /><span>待上传照片</span></div>}
          {photo ? <figcaption>{linked ? '与定位图标注关联' : mark ? '实拍原照 · 已标注' : '实拍原照 · 待标注'}</figcaption> : null}
        </figure>
        <div className="study-photo-controls">
          {detail ? <>
            <div className="study-actions study-detail-actions">
              <button type="button" className="ink-primary-button" disabled={disabled || !canGenerate} onClick={onGenerate}>{linked ? '更新关联特写' : '从当前标注生成特写'}</button>
              <button type="button" disabled={disabled} onClick={() => uploadInput.current?.click()}>{uploadLabel}</button>
            </div>
            {derivedStale ? <p role="alert" className="ink-wizard-error study-error">定位图或标注已变化，请更新特写。</p> : <p className="study-hint">{linked ? '特写与定位图的标注关联。' : '另传照片时，请核对两张照片是否为同一构件。'}{!canGenerate && ' 标出定位图目标后，可从标注区域生成特写。'}</p>}
          </> : !photo ? <p className="study-hint">上传学生现场能看到的照片，再标出目标。</p> : null}
          {photo && !linked ? <>
            <div className="study-photo-options">
              <label>标注方式<Select disabled={disabled} value={kind} onChange={event => setKind(event.target.value as Mark['kind'])}><option value="rectangle">矩形框</option><option value="arrow">箭头</option></Select></label>
              <button type="button" disabled={disabled || !mark} onClick={() => onChange({ ...photo, mark: null })}>清除标注</button>
            </div>
            <p className="study-hint">在照片上拖动标出目标，或输入位置百分比。</p>
            <fieldset disabled={disabled}>
              <legend>标注位置（百分比）</legend>
              <div className="study-coordinates">{coordinates.map(([key, label]) => <label key={key}>{label}<input type="number" min={0} max={100} step={.5} value={mark ? Math.round(mark[key] * 1000) / 10 : ''} onChange={event => onChange({ ...photo, mark: { kind, x: .2, y: .2, x2: .6, y2: .6, ...mark, [key]: Number(event.target.value) / 100 } })} /></label>)}</div>
            </fieldset>
            <div className="study-photo-display">
              <label>显示方式<Select disabled={disabled} value={photo.mode} onChange={event => onChange({ ...photo, mode: event.target.value as Photo['mode'] })}><option value="contain">{displayModes.contain}</option><option value="cover">{displayModes.cover}</option></Select></label>
              {photo.mode === 'cover' ? (['focus_x', 'focus_y'] as const).map(key => <label key={key}>{key === 'focus_x' ? '裁切横向位置' : '裁切纵向位置'}<input type="range" min={0} max={1} step={.01} disabled={disabled} value={photo[key]} onChange={event => onChange({ ...photo, [key]: Number(event.target.value) })} /></label>) : null}
            </div>
          </> : null}
          {photo ? <div className="study-photo-credit">
            {!linked && (photo.credit_kind === 'unresolved' || manualCredit || !hasCredit) ? <label>照片来源<Select disabled={disabled} value={manualCredit ? photo.credit_kind : ''} onChange={event => {
              const source = event.target.value;
              if (source === 'self' || source === 'authorized') onChange(selectPhotoCredits(photo, source));
            }}><option value="" disabled>选择来源，自动带入署名</option><option value="self">我自己拍摄</option><option value="authorized">供图方已授权用于本次短片与任务卡</option></Select></label> : null}
            {hasCredit ? <details><summary>{linked ? '查看随定位图继承的署名' : `署名 · ${photo.author}`}</summary><dl><dt>来源</dt><dd>{/^https?:\/\//.test(photo.source) ? <a href={photo.source} target="_blank" rel="noreferrer">查看来源页面</a> : photo.source}</dd><dt>作者</dt><dd>{photo.author}</dd><dt>使用说明</dt><dd>{photo.license}</dd></dl></details> : <p className="study-hint">{linked ? '保存定位图的照片来源后，特写会继承署名。' : '请选择照片来源，自动补入署名。'}</p>}
          </div> : null}
          {mark ? <button type="button" className="study-photo-preview-trigger" onClick={openPreview}>横屏画面预览（16:9）</button> : null}
        </div>
      </div>
      <dialog ref={previewDialog} className="study-photo-preview-dialog" aria-labelledby={`${id}-preview-title`} onClose={() => setPreviewOpen(false)}>
        <header><h2 id={`${id}-preview-title`}>横屏画面预览（16:9）</h2><button type="button" aria-label="关闭预览" onClick={() => previewDialog.current?.close()}><X size={20} aria-hidden="true" /></button></header>
        {previewOpen ? <div className="study-photo-preview-content">
          <div className="study-photo-preview-image">
            {derivedStale ? <p role="status">请先更新特写，查看对应的横屏画面。</p> : dirty ? <p role="status">保存草稿后可查看最新照片和标注。</p> : previewError || !photo?.preview_url ? <p role="status">暂时无法加载预览，请关闭后重试。</p> : <img className="study-landscape-preview" src={photo.preview_url} alt="横屏照片、标注、任务与署名预览" onError={() => setPreviewError(true)} />}
          </div>
          <aside><h3>{title}</h3><dl><dt>显示方式</dt><dd>{displayModes[photo?.mode ?? 'contain']}</dd></dl><p>检查目标构件在宽屏中是否清晰可见。</p><button type="button" onClick={() => previewDialog.current?.close()}>返回实拍标注</button></aside>
        </div> : null}
      </dialog>
    </section>
  );
}
