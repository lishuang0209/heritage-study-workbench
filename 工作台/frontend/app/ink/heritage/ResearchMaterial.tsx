'use client';
import {useEffect,useId,useRef,useState} from 'react';
import {LoaderCircle,Upload,X} from 'lucide-react';
import {api} from '../ink-shared';
import {importedMaterial,MATERIAL_LIMIT,MATERIAL_FILE_LIMIT,type MaterialPreview} from './material-state';

export default function ResearchMaterial({projectId,version,value,disabled,onChange,onWorkingChange}:{projectId:string;version:number;value:string;disabled:boolean;onChange:(text:string)=>void;onWorkingChange:(working:boolean)=>void}) {
  const id=useId();const fileInput=useRef<HTMLInputElement>(null);
  const previewDialog=useRef<HTMLDialogElement>(null);
  const request=useRef<AbortController|null>(null);
  const [loading,setLoading]=useState(false);const [error,setError]=useState('');
  const [notice,setNotice]=useState('');const [preview,setPreview]=useState<MaterialPreview|null>(null);
  const previewOpen=Boolean(preview);
  useEffect(()=>{
    if(!previewOpen)return;
    const dialog=previewDialog.current;
    dialog?.showModal();
    return()=>dialog?.close();
  },[previewOpen]);
  useEffect(()=>{
    setPreview(null);setError('');setNotice('');setLoading(false);
    return()=>{if(request.current){request.current.abort();request.current=null;onWorkingChange(false);}};
  },[projectId,version,onWorkingChange]);
  const upload=async(file:File)=>{
    if(disabled||loading)return;
    setError('');setNotice('');setPreview(null);
    if(!/\.(docx|pdf|txt)$/i.test(file.name)){setError('请选择Word（.docx）、PDF或TXT文件。');return;}
    if(file.size>MATERIAL_FILE_LIMIT){setError('资料文件不能超过10MB，请精简后重新上传。');return;}
    const controller=new AbortController();request.current=controller;
    setLoading(true);onWorkingChange(true);
    try{
      const form=new FormData();form.append('file',file);
      const result=await api<MaterialPreview>(`/projects/${projectId}/heritage/material/preview?version=${version}`,{method:'POST',body:form,signal:controller.signal});
      if(!controller.signal.aborted)setPreview(result);
    }catch(error){if(!controller.signal.aborted)setError(error instanceof Error?error.message:'资料提取失败，请重新上传。');}
    finally{if(request.current===controller){request.current=null;setLoading(false);onWorkingChange(false);}}
  };
  const apply=(mode:'append'|'replace')=>{
    if(!preview)return;
    try{
      const text=importedMaterial(value,preview.text,preview.filename,mode);
      onChange(text);setPreview(null);setError('');setNotice('已填入资料框，请核对内容后保存草稿。');
    }catch(error){setError(error instanceof Error?error.message:'资料填入失败');}
  };
  return <div className="study-full study-material">
    <div className="study-material-heading"><label htmlFor={id}>研学资料</label>
      <button type="button" disabled={disabled||loading} aria-busy={loading} onClick={()=>fileInput.current?.click()}>{loading?<><LoaderCircle size={14} className="ink-job-spinner"/>正在提取文字…</>:<><Upload size={14}/>上传资料</>}</button>
    </div>
    <input ref={fileInput} type="file" hidden accept=".docx,.pdf,.txt" disabled={disabled||loading} aria-label="选择研学资料文件" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void upload(file);}}/>
    <textarea id={id} rows={4} maxLength={MATERIAL_LIMIT} disabled={disabled||loading} value={value} placeholder="可上传或粘贴地方历史、建筑价值、构件特点与资料来源；提取后仍可修改。" onChange={e=>{onChange(e.target.value);setNotice('');}} aria-describedby={`${id}-hint`}/>
    <div className="study-material-meta" id={`${id}-hint`}><p className="study-hint">支持Word（.docx）、文字版PDF、TXT，单文件10MB以内。</p><span>{value.length.toLocaleString()} / {MATERIAL_LIMIT.toLocaleString()}字</span></div>
    {loading?<div className="study-material-loading" role="status"><progress aria-label="正在提取资料文字"/><span>正在提取文字，原资料保留中…</span></div>:null}
    {error&&!preview?<p role="alert" className="ink-wizard-error study-error">{error}</p>:null}
    {notice?<p role="status" className="study-hint study-material-notice">{notice}</p>:null}
    {preview?<dialog ref={previewDialog} className="ink-wizard-dialog study-material-preview" aria-labelledby={`${id}-preview-title`} onCancel={e=>{e.preventDefault();setPreview(null);setError('');}}>
      <header><h2 id={`${id}-preview-title`}>研学资料提取预览</h2><button type="button" aria-label="关闭提取预览" onClick={()=>{setPreview(null);setError('');}}><X size={16} aria-hidden="true"/></button></header>
      <div className="ink-wizard-dialog-body">
        <p className="study-hint study-material-filename">{preview.filename} · {preview.text.length.toLocaleString()}字{preview.pages!=null?` · ${preview.pages}页`:''}</p>
        <p className="study-hint">可先删改提取文字，再选择追加或替换。</p>
        {preview.warnings.map(warning=><p key={warning} className="study-material-warning">{warning}</p>)}
        <label htmlFor={`${id}-extracted`}>提取的文字</label><textarea id={`${id}-extracted`} rows={8} maxLength={MATERIAL_LIMIT} disabled={disabled} value={preview.text} onChange={e=>{setPreview({...preview,text:e.target.value});setError('');}}/>
        {error?<p role="alert" className="ink-wizard-error study-error">{error}</p>:null}
      </div>
      <footer className="study-actions"><button type="button" disabled={disabled||!preview.text.trim()} onClick={()=>apply('replace')}>替换原资料</button><button type="button" className="ink-primary-button" disabled={disabled||!preview.text.trim()} onClick={()=>apply('append')}>追加到资料</button></footer>
    </dialog>:null}
  </div>;
}
