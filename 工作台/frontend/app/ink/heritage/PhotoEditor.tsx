'use client';
import {useId,useState} from 'react';
import {point,selectPhotoCredits,type Mark,type Photo} from './state';

export default function PhotoEditor({slot,photo,disabled,dirty,onChange,onUpload,onGenerate,canGenerate,derivedStale}:{slot:'panorama'|'detail';photo:Photo|null;disabled:boolean;dirty:boolean;onChange:(p:Photo|null)=>void;onUpload:(f:File)=>void;onGenerate?:()=>void;canGenerate?:boolean;derivedStale?:boolean}) {
 const id=useId();const [size,setSize]=useState({width:3,height:4});const [kind,setKind]=useState<Mark['kind']>('rectangle');
 const [start,setStart]=useState<{x:number;y:number}|null>(null);
 const mark=photo?.mark;const linked=Boolean(photo?.derived_from);
 const upload=<label className="study-upload">{slot==='detail'?'上传另一张实拍照片':photo?'替换照片（将清空标注与确认）':'上传实拍照片'}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled} onChange={e=>{const f=e.target.files?.[0];if(f)onUpload(f);e.target.value='';}} /></label>;
 return <section className="study-photo"><h3>{slot==='panorama'?'现场定位图（必填）':'同一构件特写（可选）'}</h3>
  {slot==='detail'?<>
   <div className="study-actions study-detail-actions"><button type="button" className="ink-primary-button" disabled={disabled||!canGenerate} onClick={onGenerate}>{linked?'更新关联特写':'从当前标注生成特写'}</button>{photo?<button type="button" disabled={disabled} onClick={()=>onChange(null)}>移除特写</button>:null}</div>
   {derivedStale?<p role="alert" className="ink-wizard-error study-error">定位图或标注已变化，请更新特写。</p>:<p className="study-hint">{canGenerate?(linked?'特写与定位图的标注关联，无需再次标注。':photo?'生成后将替换当前特写，原照片保留。':'直接使用定位图的标注区域，无需再传照片。'):'先在左侧定位图标出目标，再生成特写。'}</p>}
   <details className="study-extra-upload"><summary>另传实拍特写（可选）</summary><p className="study-hint">另传照片需人工核对是否为同一构件，上传后替换当前特写。</p>{upload}</details>
  </>:upload}
  {photo ? <>
   {!linked?<><div className="study-photo-options"><label>标注方式<select disabled={disabled} value={kind} onChange={e=>setKind(e.target.value as Mark['kind'])}><option value="rectangle">矩形框</option><option value="arrow">箭头</option></select></label><button type="button" disabled={disabled||!mark} onClick={()=>onChange({...photo,mark:null})}>清除标注</button></div>
   <p className="study-hint">在照片上拖动，标出一个目标。也可在下方输入位置百分比。另传特写须指向同一构件。</p></>:null}
   <div className="study-mark-canvas" style={{aspectRatio:`${size.width}/${size.height}`}}>
    <img src={photo.url} alt={slot==='panorama'?'讲解站现场定位原图':'目标构件特写原图'} onLoad={e=>setSize({width:e.currentTarget.naturalWidth,height:e.currentTarget.naturalHeight})} />
    <svg className={linked?'study-linked-mark':undefined} viewBox="0 0 1 1" preserveAspectRatio="none" aria-label={linked?'从定位图继承的目标标注':'在照片上标注目标'} onPointerDown={e=>{if(disabled||linked)return;e.currentTarget.setPointerCapture(e.pointerId);setStart(point(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect()));}} onPointerMove={e=>{if(!start||disabled||linked)return;const end=point(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect());onChange({...photo,mark:{kind,...start,x2:end.x,y2:end.y}});}} onPointerUp={e=>{if(!start||disabled||linked)return;const end=point(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect());if(Math.abs(end.x-start.x)+Math.abs(end.y-start.y)>.02)onChange({...photo,mark:{kind,...start,x2:end.x,y2:end.y}});setStart(null);}} onPointerCancel={()=>setStart(null)}>
     <defs><marker id={id} markerWidth=".055" markerHeight=".055" refX=".045" refY=".0275" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L.05,.0275 L0,.055" fill="none" stroke="#af2424" strokeWidth=".009" /></marker></defs>
     {mark?.kind==='rectangle'?<rect x={Math.min(mark.x,mark.x2)} y={Math.min(mark.y,mark.y2)} width={Math.abs(mark.x2-mark.x)} height={Math.abs(mark.y2-mark.y)} fill="none" stroke="#af2424" strokeWidth=".007" />:mark?<line x1={mark.x} y1={mark.y} x2={mark.x2} y2={mark.y2} stroke="#af2424" strokeWidth=".007" markerEnd={`url(#${id})`} />:null}
    </svg>
   </div>
   {!linked?<><fieldset disabled={disabled}><legend>标注位置（百分比）</legend><div className="study-coordinates">{(['x','y','x2','y2'] as const).map((key,i)=><label key={key}>{['起点横向','起点纵向','终点横向','终点纵向'][i]}<input type="number" min={0} max={100} step={.5} value={mark?Math.round(mark[key]*1000)/10:''} onChange={e=>onChange({...photo,mark:{kind,x:.2,y:.2,x2:.6,y2:.6,...mark,[key]:Number(e.target.value)/100}})} /></label>)}</div></fieldset>
   <div className="study-two"><label>显示方式<select disabled={disabled} value={photo.mode} onChange={e=>onChange({...photo,mode:e.target.value as Photo['mode']})}><option value="contain">完整保留照片</option><option value="cover">竖屏裁切照片</option></select></label>{photo.mode==='cover'?<>{(['focus_x','focus_y'] as const).map(key=><label key={key}>{key==='focus_x'?'裁切横向位置':'裁切纵向位置'}<input type="range" min={0} max={1} step={.01} disabled={disabled} value={photo[key]} onChange={e=>onChange({...photo,[key]:Number(e.target.value)})}/></label>)}</>:null}</div>
   </>:null}
   <div className="study-photo-credit">
    {(!linked&&(photo.credit_kind==='unresolved'||photo.credit_kind==='self'||photo.credit_kind==='authorized'||!photo.source.trim()||!photo.author.trim()||!photo.license.trim()))?<label>照片来源<select disabled={disabled} value={photo.credit_kind==='self'||photo.credit_kind==='authorized'?photo.credit_kind:''} onChange={e=>{if(e.target.value==='self'||e.target.value==='authorized')onChange(selectPhotoCredits(photo,e.target.value));}}><option value="" disabled>选择来源，自动带入署名</option><option value="self">我自己拍摄</option><option value="authorized">供图方已授权用于本次短片与任务卡</option></select></label>:null}
    {photo.source.trim()&&photo.author.trim()&&photo.license.trim()?<><p className="study-hint">{linked?'署名随定位图继承':photo.credit_kind==='catalog'?'已识别素材，署名已自动带入':photo.credit_kind==='self'||photo.credit_kind==='authorized'?'署名已按所选来源带入':'已保留原有照片署名'}</p><details><summary>查看照片署名</summary><dl><dt>来源</dt><dd>{/^https?:\/\//.test(photo.source)?<a href={photo.source} target="_blank" rel="noreferrer">查看来源页面</a>:photo.source}</dd><dt>作者</dt><dd>{photo.author}</dd><dt>使用说明</dt><dd>{photo.license}</dd></dl></details></>:<p className="study-hint">{linked?'请先在定位图选择照片来源，保存后自动继承署名。':'未识别到已知来源，请选择照片归属后继续。'}</p>}
   </div>
   <details><summary>竖屏画面预览</summary>{derivedStale?<p>请先更新特写，查看对应的竖屏画面。</p>:dirty?<p>请先保存草稿，查看最新照片与标注的导出效果。</p>:<img className="study-portrait-preview" src={photo.preview_url} alt="竖屏裁切、标注、任务与署名预览"/>}</details>
  </>:<p className="study-hint">{slot==='detail'?'可以从左侧标注生成特写，也可另传同一构件的实拍。':'使用学生现场能看到的真实照片，标注不会由模型自动猜测。'}</p>}
 </section>;
}
