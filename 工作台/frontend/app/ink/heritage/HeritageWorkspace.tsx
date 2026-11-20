'use client';
import {useEffect,useState,type ReactNode} from 'react';
import Select from '@/components/Select';
import {ArrowLeft,Check,FileText,Film} from 'lucide-react';
import {api,json,type Project,type Summary} from '../ink-shared';
import JobStatus from '../JobStatus';
import PhotoEditor from './PhotoEditor';
import ResearchMaterial from './ResearchMaterial';
import {MATERIAL_LIMIT} from './material-state';
import {studyNarration,voiceChoice} from './narration-state';
import {blankStation,completeStationDraft,observationGuidance,derivedDetailStale,reviewStation,reviewScript,scriptIsConfirmed,stationPayload,projectTiming,timingError,observationSplit,mergeHistoryMaterial,narrationEstimate,type Station} from './state';
import './heritage.css';

type Case={id:string;title:string;station:Partial<Station>;history?:string;sources?:{title:string;url:string}[]};
const fields = {
 building:['建筑名称',80], component:['目标构件',80], grade:['适用年级',40],
 name:['讲解站名称',80], objective:['教学目标',300],
 instruction:['观察指引',600], question:['观察问题',160],
} as const;
export default function HeritageWorkspace({project:p,projects,story,readonly,working,onUpdated,onWorkingChange}:{project:Project;projects:Summary[];story:(onExport:()=>void)=>ReactNode;readonly:boolean;working:boolean;onUpdated:(p:Project)=>Project;onWorkingChange:(v:boolean)=>void}) {
 const [tab,setTab]=useState(0);const [draft,setDraft]=useState<Station>(p.heritage_station||blankStation());const [dirty,setDirty]=useState(false);
 const [narration,setNarration]=useState(true);const [pending,setPending]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');const [cases,setCases]=useState<Case[]>([]);
 const [selectedCase,setSelectedCase]=useState('');
 const [scriptVerified,setScriptVerified]=useState(false);
 const [scriptError,setScriptError]=useState('');
 const [reuseOpen,setReuseOpen]=useState(false);
 const [trialOpen,setTrialOpen]=useState(false);
 const [timingDraft,setTimingDraft]=useState(()=>projectTiming(p));
 const studyVoice=studyNarration(p);
 const savedTiming=projectTiming(p);const savedTotal=savedTiming.intro+savedTiming.location+savedTiming.task;
 const timingDirty=(['intro','location','task'] as const).some(key=>timingDraft[key]!==savedTiming[key]);
 const durationError=timingError(timingDraft);const total=timingDraft.intro+timingDraft.location+timingDraft.task;
 const observation=observationSplit(timingDraft.location,Boolean(draft.detail));
 const [scriptDraft,setScriptDraft]=useState({intro:'',location:'',task:''});const [scriptDirty,setScriptDirty]=useState(false);
 const [source,setSource]=useState<Project|null>(null);const [selected,setSelected]=useState<string[]>([]);
 const [trial,setTrial]=useState(p.heritage_trial||{participants:1,found_without_hint:0,preparation_minutes:0,notes:''});
 const busy=p.jobs.some(j=>j.state==='running');const disabled=readonly||working||pending||busy;const version=p.heritage_version||0;
 useEffect(()=>{setDraft(p.heritage_station||blankStation());setDirty(false);},[p.id,p.heritage_version]); // Saved revision is the form boundary; switching steps keeps both drafts in this component.
 useEffect(()=>{setTimingDraft(projectTiming(p));setScriptVerified(false);},[p.id,p.heritage_timing_version]);
 useEffect(()=>{const s=p.heritage_script;setScriptDraft({intro:s?.intro||'',location:s?.location||'',task:s?.task||''});setScriptDirty(false);setScriptVerified(false);},[p.id,p.heritage_script?.version]);
 useEffect(()=>{setScriptVerified(false);setScriptError('');},[p.id,p.heritage_version,p.heritage_timing_version,p.heritage_script?.version]);
 useEffect(()=>{let active=true;void api<{templates:Case[]}>('/heritage/templates').then(data=>{if(active)setCases(data.templates);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
 const run=async(fn:()=>Promise<unknown>,scope:'page'|'script'='page')=>{if(disabled)return;setPending(true);onWorkingChange(true);setError('');setScriptError('');setNotice('');try{await fn();}catch(e){const message=e instanceof Error?e.message:'操作失败';if(scope==='script')setScriptError(message);else setError(message);}finally{setPending(false);onWorkingChange(false);}};
 const change=(next:Station)=>{setDraft(next);setDirty(true);};
 const save=async()=>{const next=await api<Project>(`/projects/${p.id}/heritage/station`,json('PUT',{version,station:stationPayload(completeStationDraft(draft))}));onUpdated(next);setDraft(next.heritage_station||blankStation());setDirty(false);return next;};
 const persistTiming=async()=>{
  if(!timingDirty)return p;
  if(durationError)throw new Error(durationError);
  const updated=await api<Project>(`/projects/${p.id}/heritage/timing`,json('PUT',{version:p.heritage_timing_version||0,timing:timingDraft}));
  onUpdated(updated);setScriptVerified(false);return updated;
 };
 const field=(key:keyof typeof fields)=>{
  const [label,max]=fields[key];
  return <label key={key} className={max>100?'study-full':''}>{label}{max>100?<textarea rows={2} maxLength={max} disabled={disabled} value={key==='instruction'?observationGuidance(draft):draft[key]} placeholder={key==='instruction'?'说明往哪里看、找什么；有需要时补充具体观察位置。':undefined} onChange={e=>change({...draft,[key]:e.target.value,...(key==='instruction'?{standing_position:''}:{})})}/>:<input maxLength={max} disabled={disabled} value={draft[key]} onChange={e=>change({...draft,[key]:e.target.value,...(key==='instruction'?{standing_position:''}:{})})}/>}</label>;
 };
 const stationConfirmed=Boolean(p.heritage_ready&&!dirty);
 const wasConfirmed=Boolean(p.heritage_confirmed_snapshot||p.heritage_confirmed_version!=null);
 const continueToScript=()=>{
  if(stationConfirmed){setTab(2);setError('');setNotice('');return;}
  void run(async()=>{
   const reviewed=await reviewStation(p,dirty,save,current=>api<Project>(`/projects/${current.id}/heritage/confirm`,json('POST',{
    version:current.heritage_version||0,teacher_verified:true,same_target_verified:Boolean(current.heritage_station?.detail),
   })));
   onUpdated(reviewed);setTab(2);
  });
 };
 const historyCase=cases.find(c=>c.station.building===draft.building&&c.station.component===draft.component);
 const historySupplement=historyCase?.history?mergeHistoryMaterial(draft.checked_description,historyCase.history,historyCase.sources):draft.checked_description;
 const introEstimate=narrationEstimate(scriptDraft.intro);
 const savedIntroEstimate=narrationEstimate(p.script);
 const script=p.heritage_script;
 const needsHistory=scriptDraft.intro.includes('【待补充历史背景】');
 const scriptOutdated=Boolean(script&&(script.station_version!==version||(script.timing_version||0)!==(p.heritage_timing_version||0)));
 const scriptConfirmed=scriptIsConfirmed(p)&&!dirty&&!scriptDirty&&!timingDirty;
 const scriptReviewHint=dirty?'讲解站资料有修改，请返回第1步或第2步保存。':!script?'请先生成或填写并保存脚本。':needsHistory?'请补充历史引入后保存脚本。':scriptDirty||timingDirty||scriptOutdated?'请先保存脚本，再核对台词。':!scriptConfirmed&&!scriptVerified?'核对三段台词后，勾选审核项即可继续。':'';
 const goToStory=()=>{setTab(3);setReuseOpen(false);setError('');setScriptError('');};
 const continueToStory=()=>{
  if(scriptConfirmed){setNotice('');goToStory();return;}
  void run(async()=>{
   const reviewed=await reviewScript(p,current=>api<Project>(`/projects/${current.id}/heritage/confirm-script`,json('POST',{
    version:current.heritage_script?.version||0,teacher_verified:scriptVerified,timing_version:current.heritage_timing_version||0,
   })));
   onUpdated(reviewed);goToStory();
  },'script');
 };
 const latestJob=p.jobs[0];
 const failedIntroLimit=latestJob?.action==='heritage-export'&&latestJob.state==='failed'
  ? /^历史引入镜头需不超过(\d+)秒/.exec(latestJob.error)
  : null;
 const outdatedTimingError=failedIntroLimit&&Number(failedIntroLimit[1])!==savedTiming.intro;
 const steps=['讲解站资料','实拍标注','研学脚本','水墨故事','导出与试用'];
 const descriptions=['填写基础资料，下一步结合实拍照片核对观察指引。','用学生视角的实拍照片标出目标，确认横屏中的定位线索。','按资料和时长讲清地方历史，再观察实物、布置现场任务。','可复用已有水墨项目中已确认的镜头，或继续制作当前故事。','预览宽屏短片与任务卡，导出同一版已确认内容。'];
 const moveTo=(next:number)=>{
  setTab(next);setError('');setNotice('');setReuseOpen(false);setTrialOpen(false);
 };
 const showHeading=tab!==3||reuseOpen;
 const completedSteps=[
  Boolean(p.heritage_station?.building&&p.heritage_station.component&&p.heritage_station.grade&&!dirty),
  stationConfirmed,
  scriptConfirmed,
  p.shots.length>0&&p.shots.every(shot=>shot.rendered_url&&!shot.rendered_stale&&!shot.clip_stale&&!shot.image_stale),
  Boolean(p.final_url&&!p.final_stale&&p.task_card_url&&!p.task_card_stale),
 ];
 const title=tab===4&&trialOpen?'现场试用记录':steps[tab];
 const caseArt=historyCase&&(['baoguo','ningyuan','taihe'] as const).find(id=>id===historyCase.id);
 const caseSummary=historyCase?.station.instruction||observationGuidance(draft);
 const taskCard=(trialPreview=false)=>{
  const url=p.task_card_url;
  return <section className="study-card study-task-card" data-layout={trialPreview?'trial':'export'}>
   <h3>{trialPreview?'本次试用材料':'观察任务卡'}</h3>
   {url?<div className="study-task-card-body">
    <object className="study-task-thumbnail" data={url+'#toolbar=0&navpanes=0'} type="application/pdf" aria-label="A4 观察任务卡预览">
     <FileText aria-hidden="true" size={32}/>
    </object>
    <div className="study-task-links">
     <p className="study-state" data-tone={p.task_card_stale?'pending':'saved'} role="status">
      <span className="study-form-status-dot" aria-hidden="true"/>
      {p.task_card_stale?'内容已更新，请重新导出任务卡':'A4 任务卡已就绪'}
     </p>
     <div className="study-link-actions"><a href={url} target="_blank" rel="noreferrer">查看任务卡 PDF</a><a href={url} download>下载任务卡</a></div>
     {trialPreview?<><h4>{p.title}</h4>{p.heritage_station?.question?<p className="study-hint">{p.heritage_station.question}</p>:null}</>:null}
     {!trialPreview&&p.heritage_chapters?.length?<><h4>短片章节</h4><ol className="study-chapters">
      {p.heritage_chapters.map(c=><li key={c.video}>{{story:'历史引入',panorama:'全景观察',detail:'同一构件特写',task:'现场任务'}[c.kind]||c.kind} · {c.duration} 秒</li>)}
     </ol></>:null}
    </div>
   </div>:<div className="study-preview-empty"><FileText aria-hidden="true" size={30}/><p>导出后可查看观察任务卡。</p></div>}
  </section>;
 };
 const draftFooterStatus=dirty?'待保存':tab===1?(stationConfirmed?'资料与标注已确认':wasConfirmed?'待重新确认':'资料与标注待确认'):'已保存';
 const scriptState=scriptDirty||timingDirty||dirty?'待保存':!script?'未生成':scriptOutdated?'资料或时长已更新':scriptConfirmed?'已确认':'待确认';
 const scriptTone=scriptConfirmed?'saved':!script&&!scriptDirty&&!timingDirty&&!dirty?'empty':'pending';
 const timingSum=Math.max(1,total);

 return <div className="study-workspace">
  <nav className="study-tabs" aria-label="研学制作步骤">
   {steps.map((label,i)=><button type="button" key={label} disabled={pending||working} data-completed={completedSteps[i]} aria-current={tab===i?'step':undefined} onClick={()=>moveTo(i)}>
    <span className="study-step-marker" aria-hidden="true">{completedSteps[i]&&tab!==i?<Check size={16}/>:String(i+1).padStart(2,'0')}</span>{label}
   </button>)}
  </nav>

  {showHeading?<header className="study-stage-heading">
   <h2>{title}</h2>
   <p>{tab===4&&trialOpen?'导出与试用 · 老师现场记录':descriptions[tab]}</p>
  </header>:null}
  {error?<p role="alert" className="ink-wizard-error study-error">{error}</p>:null}
  {notice?<p role="status" className="ink-wizard-review study-notice">{notice}</p>:null}
  {!outdatedTimingError&&latestJob&&(['heritage-export','heritage-script'].includes(latestJob.action))&&(latestJob.state!=='completed'||(tab===2&&latestJob.action==='heritage-script'))?<JobStatus jobs={[latestJob]}/>:null}

  {tab===0?<div className="study-split">
   <section className="study-card study-intake">
    <header className="study-card-heading"><h3>一个讲解站，一个观察目标</h3></header>
    <label>使用案例模板（可选）
     <Select disabled={disabled||!cases.length} value={selectedCase} onChange={e=>{
      const selected=cases.find(item=>item.id===e.target.value);
      setSelectedCase(e.target.value);
      if(selected){change({...draft,...selected.station});setError('');setNotice(`已填入“${selected.title}”的资料，请核对后保存草稿。`);}
     }}>
      <option value="" disabled>选择案例填入资料</option>
      {cases.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}
     </Select>
    </label>
    {selectedCase?<p className="study-hint" role="status">已选择：{cases.find(item=>item.id===selectedCase)?.title}。{dirty?'请核对下方资料后保存。':'可继续编辑。'}</p>:null}
    <div className="study-three">{(['building','component','grade'] as const).map(field)}</div>
    <ResearchMaterial projectId={p.id} version={version} value={draft.checked_description} disabled={disabled} onChange={text=>change({...draft,checked_description:text})} onWorkingChange={onWorkingChange}/>
    <div className="study-research-meta">
     <p className="study-hint">可补充寺院沿革、建筑价值、修缮历史与资料来源。</p>
     {historyCase?.history&&historySupplement!==draft.checked_description?<button type="button" disabled={disabled||historySupplement.length>MATERIAL_LIMIT} onClick={()=>{change({...draft,checked_description:historySupplement});setNotice('已补入案例历史与来源，请核对后保存。');}}>补入完整案例历史</button>:null}
    </div>
   </section>
   <aside className="study-card study-case-guide" aria-label="本次观察目标">
    <h3>本次观察目标</h3>
    {caseArt?<img className="study-case-art" src={`/heritage-home/${caseArt}.webp`} alt={historyCase?.title||'案例配图'}/>:null}
    {historyCase||draft.component?<><h4>{historyCase?.title||draft.component}</h4>{caseSummary?<p>{caseSummary}</p>:null}</>:<p className="study-hint">选择案例或填写目标构件后，这里会显示观察目标。</p>}
    {historyCase?.sources?.length?<div className="study-case-sources">
     <h4>案例历史来源</h4>
     <ul>{historyCase.sources.map(source=><li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></li>)}</ul>
    </div>:null}
   </aside>
  </div>:null}

  {tab===1?<>
   <section className="study-card study-observation">
    <header className="study-card-heading"><h3>确定观察任务</h3></header>
    <div className="study-observation-fields">{(['instruction','question'] as const).map(field)}</div>
    <details className="study-more"><summary>课程设置（可选）</summary><div className="study-two">{(['name','objective'] as const).map(field)}</div></details>
   </section>
   <div className="study-photo-grid">{(['panorama','detail'] as const).map(slot=>
    <PhotoEditor key={slot} slot={slot} photo={draft[slot]} canGenerate={Boolean(draft.panorama?.mark)}
     derivedStale={slot==='detail'&&derivedDetailStale(draft)} disabled={disabled} dirty={dirty}
     onGenerate={slot==='detail'?()=>void run(async()=>{
      const current=dirty?await save():p;
      onUpdated(await api<Project>(`/projects/${p.id}/heritage/detail-from-mark`,json('POST',{version:current.heritage_version||0})));
      setNotice('特写已从定位图标注区域生成，标注与署名自动关联。');
     }):undefined}
     onChange={photo=>change({...draft,[slot]:photo})}
     onUpload={file=>void run(async()=>{
      const current=dirty?await save():p;
      const form=new FormData();form.append('file',file);
      onUpdated(await api<Project>(`/projects/${p.id}/heritage/photos/${slot}?version=${current.heritage_version||0}`,{method:'POST',body:form}));
      setNotice('照片已保存，已知素材的署名会自动带入，请完成标注。');
     })}/>
   )}</div>
  </>:null}

  {tab<=1?<footer className="study-form-footer">
   <div className="study-form-feedback">
    {tab===1?<button type="button" className="study-return" disabled={pending||working} onClick={()=>moveTo(0)}><ArrowLeft size={16} aria-hidden="true"/>讲解站资料</button>:null}
    <div>
     <p className="study-form-status" role="status" data-state={dirty||(tab===1&&!stationConfirmed)?'pending':'saved'}><span className="study-form-status-dot" aria-hidden="true"/>{draftFooterStatus}</p>
     {tab===1&&!stationConfirmed?<p className="study-review-note">点击确认，即表示历史与构件资料、标注及指引已核对，适合现场使用{draft.detail?(draft.detail.derived_from?'，特写与定位图标注已关联':'，全景与特写指向同一构件'):''}。</p>:null}
    </div>
   </div>
   <div className="study-actions">
    {dirty?<button type="button" disabled={disabled} onClick={()=>void run(async()=>{await save();setNotice('草稿已保存。');})}>保存草稿</button>:null}
    {dirty?<button type="button" disabled={disabled} onClick={()=>{setDraft(p.heritage_station||blankStation());setDirty(false);setSelectedCase('');setNotice('');}}>撤销修改</button>:null}
    {tab===0?<button type="button" className="ink-primary-button" disabled={disabled} onClick={()=>void run(async()=>{
     if(dirty)await save();setTab(1);setNotice('请上传实拍照片，并核对观察指引和问题。');
    })}>{pending?'正在处理…':dirty?'保存并下一步':'下一步：实拍标注'}</button>:<button type="button" className="ink-primary-button" disabled={pending||working||(!stationConfirmed&&(readonly||busy))} onClick={continueToScript}>{pending?'正在确认…':stationConfirmed?'进入研学脚本':'确认并进入研学脚本'}</button>}
   </div>
  </footer>:null}

  {tab===2?<>
   <div className="study-split">
    <section className="study-card study-script-card">
     <header className="study-card-heading">
      <h3>{total} 秒研学脚本</h3>
      <div className="study-actions study-actions-inline">
       <button type="button" disabled={disabled||Boolean(durationError)} onClick={()=>void run(async()=>{
        await persistTiming();onUpdated(await api<Project>(`/projects/${p.id}/heritage/script-template`,json('POST',{})));
       })}>使用资料生成模板</button>
       <button type="button" disabled={disabled||Boolean(durationError)} onClick={()=>void run(async()=>{
        await persistTiming();onUpdated(await api<Project>(`/projects/${p.id}/heritage/script-ai`,json('POST',{})));
       })}>AI 起草（计费）</button>
      </div>
     </header>
     <p className="study-hint">资料模板在本地生成。</p>
     {needsHistory?<p className="ink-wizard-review study-notice">研学资料缺少地方历史。<button type="button" disabled={pending||working} onClick={()=>moveTo(0)}>返回补充历史资料</button></p>:null}
     {(['intro','location','task'] as const).map((key,i)=><label key={key}>
      {[`历史引入 · 0–${timingDraft.intro} 秒`,`实物观察 · ${timingDraft.intro}–${timingDraft.intro+timingDraft.location} 秒`,`现场任务 · ${timingDraft.intro+timingDraft.location}–${total} 秒`][i]}
      <textarea rows={3} maxLength={{intro:400,location:600,task:800}[key]} disabled={disabled} value={scriptDraft[key]} onChange={e=>{setScriptDraft({...scriptDraft,[key]:e.target.value});setScriptDirty(true);setScriptVerified(false);}}/>
      {key==='intro'?<small className="study-hint">{introEstimate.characters} 字，按每秒 3–4 字粗估约 {introEstimate.minimum}–{introEstimate.maximum} 秒；计划 {timingDraft.intro} 秒。{introEstimate.minimum>timingDraft.intro?'请增加历史段时长或精简旁白。拆分镜时会按句核算。':timingDraft.intro<=15?'当前适合简短开场；详细历史介绍可增加时长。':introEstimate.maximum<timingDraft.intro/2?'篇幅较短，可从资料中展开更多历史节点。':''}</small>:null}
     </label>)}
     <p className="study-hint">历史段可讲清沿革、重建、建筑价值及修缮，再引出构件；按资料和时长展开，请核对史实。</p>
    </section>

    <aside className="study-side">
     <section className="study-card study-timing-card">
      <header className="study-card-heading">
       <h3>段落时长</h3><p className="study-hint" role="status">{timingDirty?'时长待保存':`总时长 ${savedTotal} 秒`}</p>
      </header>
      <div className="study-three">
       {(['intro','location','task'] as const).map((key,i)=><label key={key}>{['历史引入','实物观察','现场任务'][i]}（秒）
        <input type="number" min={3} max={180} step={1} value={timingDraft[key]||''} disabled={disabled} onChange={e=>setTimingDraft({...timingDraft,[key]:Number(e.target.value)})}/>
       </label>)}
      </div>
      <div className="study-timing-track" aria-hidden="true">
       {(['intro','location','task'] as const).map(key=><span key={key} style={{flexGrow:Math.max(0,timingDraft[key])/timingSum}}/>)}
      </div>
      <p className="study-hint">{draft.detail?`实物观察：全景 ${observation.panorama} 秒、特写 ${observation.detail} 秒。`:`实物观察：定位图 ${timingDraft.location} 秒。`}</p>
      {timingDirty&&durationError?<p role="alert" className="ink-wizard-error study-error">{durationError}</p>:null}
      <div className="study-actions study-actions-end"><button type="button" disabled={disabled||!timingDirty||Boolean(durationError)} onClick={()=>void run(persistTiming)}>应用时长</button></div>
     </section>
     <section className="study-card study-script-review" aria-label="脚本审核">
      <header className="study-card-heading">
       <h3>脚本审核</h3>
       <span className="study-state" role="status" data-tone={scriptTone}><span className="study-form-status-dot" aria-hidden="true"/>{scriptState}</span>
      </header>
      {!scriptConfirmed?<label className="study-check">
       <input type="checkbox" disabled={disabled||dirty||scriptDirty||timingDirty||scriptOutdated||!script||needsHistory} checked={scriptVerified} onChange={e=>setScriptVerified(e.target.checked)}/>
       <span>我已审核台词，确认历史、构件名称和观察任务与资料一致</span>
      </label>:null}
      {scriptReviewHint?<p id="study-script-review-hint" className="study-review-note">{scriptReviewHint}</p>:null}
      {scriptError?<p id="study-script-error" role="alert" className="ink-wizard-error study-error">{scriptError}</p>:null}
      {stationConfirmed?<p className="study-source-confirmed"><Check size={16} aria-hidden="true"/>讲解站资料与实拍标注已确认</p>:null}
     </section>
    </aside>
   </div>

   <footer className="study-form-footer">
    <div className="study-form-feedback">
     <button type="button" className="study-return" disabled={pending||working} onClick={()=>moveTo(1)}><ArrowLeft size={16} aria-hidden="true"/>实拍标注</button>
     <span className="study-form-status" role="status" data-state={scriptTone}><span className="study-form-status-dot" aria-hidden="true"/>{scriptState}</span>
    </div>
    <div className="study-actions">
     {scriptDirty||timingDirty||scriptOutdated?<button type="button" disabled={disabled||Boolean(durationError)||Object.values(scriptDraft).some(t=>!t.trim())} onClick={()=>void run(async()=>{
      const current=await persistTiming();
      onUpdated(await api<Project>(`/projects/${p.id}/heritage/script`,json('PUT',{...scriptDraft,version:current.heritage_script?.version||0,station_version:current.heritage_version||0,timing_version:current.heritage_timing_version||0})));
     },'script')}>保存脚本</button>:null}
     {scriptDirty?<button type="button" disabled={disabled} onClick={()=>{setScriptDraft({intro:script?.intro||'',location:script?.location||'',task:script?.task||''});setScriptDirty(false);}}>撤销脚本修改</button>:null}
     <button type="button" className="ink-primary-button" aria-describedby={scriptError?'study-script-error':scriptReviewHint?'study-script-review-hint':undefined} disabled={pending||working||(!scriptConfirmed&&(disabled||!scriptVerified||dirty||scriptDirty||timingDirty||scriptOutdated||!script||needsHistory))} onClick={continueToStory}>{pending?'正在处理…':scriptConfirmed?'下一步：水墨故事':'确认并进入水墨故事'}</button>
    </div>
   </footer>
  </>:null}

  {tab===3?<>
   {p.heritage_story_stale?<p className="ink-wizard-review study-notice" role="status">历史旁白已更新，请重新生成分镜并采用新草稿。</p>:null}
   {savedIntroEstimate.minimum>savedTiming.intro?<div className="study-story-timing"><span>口播约 {savedIntroEstimate.minimum}–{savedIntroEstimate.maximum} 秒，历史段已设 {savedTiming.intro} 秒。</span><button type="button" disabled={pending||working} onClick={()=>moveTo(2)}>调整时长</button></div>:null}
   {timingDirty?<p className="ink-wizard-review study-notice">时长设置待保存。<button type="button" disabled={pending||working} onClick={()=>moveTo(2)}>返回应用时长</button></p>:null}
   <div hidden={reuseOpen}>{story(()=>moveTo(4))}</div>
   {!reuseOpen?<div className="study-story-menu"><button type="button" className="study-return" disabled={pending||working||busy} onClick={()=>setReuseOpen(true)}>复用已有镜头（可选）</button></div>:<>
    <section className="study-card study-reuse-card">
     <header className="study-card-heading"><h3>复用已有镜头</h3><span className="study-state" data-tone="pending"><span className="study-form-status-dot" aria-hidden="true"/>可选</span></header>
     <label className="study-source-select">来源项目
      <Select disabled={disabled} value={source?.id||''} onChange={e=>{
       const id=e.target.value;
       setSource(null);setSelected([]);
       if(id)void run(async()=>{setSource(await api<Project>(`/projects/${id}`));});
      }}>
       <option value="">选择来源项目</option>
       {projects.filter(item=>item.id!==p.id&&item.project_type!=='heritage').map(item=><option key={item.id} value={item.id}>{item.title}</option>)}
      </Select>
     </label>
     <p className="study-hint">仅支持导入可用于成片的镜头。总长不超过 {savedTiming.intro} 秒；不足时停帧补齐。</p>
     {source?<><div className="study-source-shots">
      {source.shots.map((shot,i)=><label className="study-source-shot" key={shot.id}>
       {shot.image_url?<img src={shot.image_url} alt=""/>:<div className="study-preview-empty"><Film aria-hidden="true" size={28}/></div>}
       <span><input type="checkbox" disabled={disabled||!shot.rendered_url||shot.image_stale||shot.clip_stale||shot.rendered_stale} checked={selected.includes(shot.id)} onChange={e=>setSelected(e.target.checked?[...selected,shot.id]:selected.filter(id=>id!==shot.id))}/> 第 {i+1} 镜 · {shot.duration||5} 秒{shot.rendered_stale?' · 待更新':''}</span>
      </label>)}
     </div>
     <div className="study-actions study-actions-end"><button type="button" className="ink-primary-button" disabled={disabled||!selected.length||timingDirty} onClick={()=>{
      if(p.shots.length&&!window.confirm('替换本研学项目的故事镜头？原文件保留，来源水墨项目不受影响。'))return;
      void run(async()=>{
       onUpdated(await api<Project>(`/projects/${p.id}/heritage/reuse-story`,json('POST',{source_project:source.id,shot_ids:selected,replace_confirmed:true})));
       setNotice('镜头已复制到本研学项目。');
      });
     }}>导入所选镜头</button></div></>:null}
    </section>
    <footer className="study-form-footer">
     <button type="button" className="study-return" disabled={pending||working} onClick={()=>moveTo(2)}><ArrowLeft size={16} aria-hidden="true"/>研学脚本</button>
     <div className="study-actions"><button type="button" className="ink-primary-button" disabled={pending||working} onClick={()=>setReuseOpen(false)}>继续制作水墨故事</button></div>
    </footer>
   </>}
  </>:null}

  {tab===4&&!trialOpen?<>
   {timingDirty?<p className="ink-wizard-review study-notice">时长设置待保存。<button type="button" disabled={pending||working} onClick={()=>moveTo(2)}>返回应用时长</button></p>:null}
   <div className="study-split study-export-grid">
    <section className="study-card study-export-preview">
     <header className="study-card-heading"><h3>研学短片</h3><span className="study-state" data-tone="empty">{savedTotal} 秒 · 16:9</span></header>
     {p.final_url?<div className="study-output">
      <video key={p.final_url} controls preload="metadata" src={p.final_url}/>
      <div className="study-output-caption"><p>{p.final_stale?'内容、时长或画幅已更新，请重新导出。':`已生成 ${savedTotal} 秒宽屏短片。`}</p><a href={p.final_url} download>下载 MP4</a></div>
     </div>:<div className="study-preview-empty study-preview-video"><Film aria-hidden="true" size={34}/><p>导出后可预览研学短片。</p></div>}
    </section>
    <aside className="study-side">
     <section className="study-card study-export-options">
      <h3>导出短片与观察任务卡</h3>
      {!scriptConfirmed&&p.heritage_ready?<p role="status">历史引入当前为 {savedTiming.intro} 秒。请先<button type="button" className="ink-text-button" onClick={()=>moveTo(2)}>返回确认研学脚本</button>再导出。</p>:null}
      <label className="study-check"><input type="checkbox" checked={narration} disabled={disabled} onChange={e=>setNarration(e.target.checked)}/>统一讲解配音</label>
      {narration?<div className="study-narration-options">
       <label>讲解音色<Select disabled={disabled} value={studyVoice.voice} onChange={e=>{
        const voice=e.target.value;
        void run(async()=>{
         onUpdated(await api<Project>(`/projects/${p.id}/voices`,json('POST',{voices:voiceChoice(p,voice)})));
         setNotice('讲解音色已保存，将用于镜头配音与成片导出。');
        });
       }}>{studyVoice.choices.map(item=><option key={item.voice} value={item.voice}>{item.label}</option>)}</Select></label>
       <p className="study-hint">统一讲解配音将替换视频原声。</p>
      </div>:null}
      <div className="study-actions">{(['both','video','card'] as const).map((kind,i)=><button type="button" key={kind} className={i===0?'ink-primary-button':''} disabled={disabled||!p.heritage_ready||!scriptConfirmed} onClick={()=>void run(async()=>{
       onUpdated(await api<Project>(`/projects/${p.id}/heritage/export`,json('POST',{kind,version,narration,timing_version:p.heritage_timing_version||0})));
      })}>{['导出 MP4 与 A4 任务卡',`导出 ${savedTotal} 秒短片`,'导出 A4 任务卡'][i]}</button>)}</div>
      {!p.heritage_ready?<p className="ink-wizard-error study-error">请先保存并确认实拍照片、有效标注与任务资料。</p>:null}
     </section>
     {taskCard()}
    </aside>
   </div>
   <footer className="study-form-footer">
    <button type="button" className="study-return" disabled={pending||working} onClick={()=>moveTo(3)}><ArrowLeft size={16} aria-hidden="true"/>水墨故事</button>
    <div className="study-actions"><button type="button" disabled={pending||working} onClick={()=>setTrialOpen(true)}>现场试用记录</button></div>
   </footer>
  </>:null}

  {tab===4&&trialOpen?<>
   <div className="study-split">
    <section className="study-card study-trial">
     <h3>现场试用记录（由老师填写）</h3>
     <p>播放短片并发卡后，不再额外提示方向，记录学生是否能独立指出目标。</p>
     <div className="study-three">
      {(['participants','found_without_hint','preparation_minutes'] as const).map((key,i)=><label key={key}>{['参与人数','无额外提示找到目标人数','老师实际备课耗时（分钟）'][i]}<input type="number" min={key==='participants'?1:0} value={trial[key]} disabled={disabled} onChange={e=>setTrial({...trial,[key]:Number(e.target.value)})}/></label>)}
     </div>
     <label>观察记录<textarea rows={6} value={trial.notes} maxLength={1500} disabled={disabled} placeholder="记录学生如何辨认目标构件，以及现场遇到的问题。" onChange={e=>setTrial({...trial,notes:e.target.value})}/></label>
     <div className="study-actions study-actions-end"><button type="button" className="ink-primary-button" disabled={disabled} onClick={()=>void run(async()=>{
      onUpdated(await api<Project>(`/projects/${p.id}/heritage/trial`,json('PUT',trial)));
      setNotice('现场试用记录已保存。');
     })}>保存老师的试用记录</button></div>
    </section>
    <aside>{taskCard(true)}</aside>
   </div>
   <footer className="study-form-footer">
    <div className="study-form-feedback"><button type="button" className="study-return" disabled={pending||working} onClick={()=>{setTrialOpen(false);setNotice('');setError('');}}><ArrowLeft size={16} aria-hidden="true"/>返回导出与试用</button><span className="study-form-status">现场记录由老师确认</span></div>
   </footer>
  </>:null}
 </div>;
}
