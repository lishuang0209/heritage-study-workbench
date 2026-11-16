'use client';
import {useId,useState} from 'react';
import {point,type Mark,type Photo} from './state';

export default function PhotoEditor({slot,photo,disabled,dirty,onChange,onUpload}:{slot:'panorama'|'detail';photo:Photo|null;disabled:boolean;dirty:boolean;onChange:(p:Photo|null)=>void;onUpload:(f:File)=>void}) {
 const id=useId();const [size,setSize]=useState({width:3,height:4});const [kind,setKind]=useState<Mark['kind']>('rectangle');
 const [start,setStart]=useState<{x:number;y:number}|null>(null);
 const mark=photo?.mark;
 return <section className="study-photo"><h3>{slot==='panorama'?'现场定位图（必填）':'同一构件特写（可选）'}</h3>
  <label className="study-upload">{photo?'替换照片（将清空标注与确认）':'上传实拍照片'}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled} onChange={e=>{const f=e.target.files?.[0];if(f)onUpload(f);e.target.value='';}} /></label>
  {photo ? <>
   <div className="study-photo-options"><label>标注方式<select disabled={disabled} value={kind} onChange={e=>setKind(e.target.value as Mark['kind'])}><option value="rectangle">矩形框</option><option value="arrow">箭头</option></select></label><button type="button" disabled={disabled||!mark} onClick={()=>onChange({...photo,mark:null})}>清除标注</button>{slot==='detail'?<button type="button" disabled={disabled} onClick={()=>onChange(null)}>移除特写</button>:null}</div>
   <p className="study-hint">在照片上拖动，标出一个目标。也可在下方输入位置百分比。全景和特写须指向同一构件。</p>
   <div className="study-mark-canvas" style={{aspectRatio:`${size.width}/${size.height}`}}>
    <img src={photo.url} alt={slot==='panorama'?'讲解站现场定位原图':'目标构件特写原图'} onLoad={e=>setSize({width:e.currentTarget.naturalWidth,height:e.currentTarget.naturalHeight})} />
    <svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="在照片上标注目标" onPointerDown={e=>{if(disabled)return;e.currentTarget.setPointerCapture(e.pointerId);setStart(point(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect()));}} onPointerMove={e=>{if(!start||disabled)return;const end=point(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect());onChange({...photo,mark:{kind,...start,x2:end.x,y2:end.y}});}} onPointerUp={e=>{if(!start||disabled)return;const end=point(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect());if(Math.abs(end.x-start.x)+Math.abs(end.y-start.y)>.02)onChange({...photo,mark:{kind,...start,x2:end.x,y2:end.y}});setStart(null);}} onPointerCancel={()=>setStart(null)}>
     <defs><marker id={id} markerWidth=".055" markerHeight=".055" refX=".045" refY=".0275" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L.05,.0275 L0,.055" fill="none" stroke="#af2424" strokeWidth=".009" /></marker></defs>
     {mark?.kind==='rectangle'?<rect x={Math.min(mark.x,mark.x2)} y={Math.min(mark.y,mark.y2)} width={Math.abs(mark.x2-mark.x)} height={Math.abs(mark.y2-mark.y)} fill="none" stroke="#af2424" strokeWidth=".007" />:mark?<line x1={mark.x} y1={mark.y} x2={mark.x2} y2={mark.y2} stroke="#af2424" strokeWidth=".007" markerEnd={`url(#${id})`} />:null}
    </svg>
   </div>
   <fieldset disabled={disabled}><legend>标注位置（百分比）</legend><div className="study-coordinates">{(['x','y','x2','y2'] as const).map((key,i)=><label key={key}>{['起点横向','起点纵向','终点横向','终点纵向'][i]}<input type="number" min={0} max={100} step={.5} value={mark?Math.round(mark[key]*1000)/10:''} onChange={e=>onChange({...photo,mark:{kind,x:.2,y:.2,x2:.6,y2:.6,...mark,[key]:Number(e.target.value)/100}})} /></label>)}</div></fieldset>
   <div className="study-two"><label>显示方式<select disabled={disabled} value={photo.mode} onChange={e=>onChange({...photo,mode:e.target.value as Photo['mode']})}><option value="contain">完整保留照片</option><option value="cover">竖屏裁切照片</option></select></label>{photo.mode==='cover'?<>{(['focus_x','focus_y'] as const).map(key=><label key={key}>{key==='focus_x'?'裁切横向位置':'裁切纵向位置'}<input type="range" min={0} max={1} step={.01} disabled={disabled} value={photo[key]} onChange={e=>onChange({...photo,[key]:Number(e.target.value)})}/></label>)}</>:null}</div>
   <label>照片来源（链接或自摄说明）<input maxLength={240} value={photo.source} disabled={disabled} onChange={e=>onChange({...photo,source:e.target.value})}/></label>
   <div className="study-two"><label>作者<input maxLength={80} value={photo.author} disabled={disabled} onChange={e=>onChange({...photo,author:e.target.value})}/></label><label>使用许可说明<input maxLength={200} value={photo.license} disabled={disabled} onChange={e=>onChange({...photo,license:e.target.value})}/></label></div>
   <details><summary>竖屏成片预览</summary>{dirty?<p>请先保存草稿，查看最新照片与标注的导出效果。</p>:<img className="study-portrait-preview" src={photo.preview_url} alt="竖屏裁切、标注、任务与署名预览"/>}</details>
  </>:<p className="study-hint">使用学生现场能看到的真实照片，标注不会由模型自动猜测。</p>}
 </section>;
}
