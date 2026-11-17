'use client';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {api,json,type Project,type Summary} from '../ink-shared';
import JobStatus from '../JobStatus';
import PhotoEditor from './PhotoEditor';
import {blankStation,completeStationDraft,observationGuidance,derivedDetailStale,reviewStation,reviewScript,scriptIsConfirmed,stationPayload,projectTiming,timingError,observationSplit,type Station} from './state';
import './heritage.css';

type Case={id:string;title:string;station:Partial<Station>;history?:string;sources?:{title:string;url:string}[]};
const fields = {
 building:['建筑名称',80], component:['目标构件',80], grade:['适用年级',40],
 checked_description:['研学资料',1500],
 name:['讲解站名称',80], objective:['教学目标',300],
 instruction:['观察指引',600], question:['观察问题',160],
} as const;
export default function HeritageWorkspace({project:p,projects,story,readonly,working,onUpdated,onWorkingChange}:{project:Project;projects:Summary[];story:ReactNode;readonly:boolean;working:boolean;onUpdated:(p:Project)=>Project;onWorkingChange:(v:boolean)=>void}) {
 const [tab,setTab]=useState(0);const [draft,setDraft]=useState<Station>(p.heritage_station||blankStation());const [dirty,setDirty]=useState(false);
 const [narration,setNarration]=useState(false);const [pending,setPending]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');const [cases,setCases]=useState<Case[]>([]);
 const [selectedCase,setSelectedCase]=useState('');
 const [scriptVerified,setScriptVerified]=useState(false);
 const [scriptError,setScriptError]=useState('');
 const stageHeading=useRef<HTMLHeadingElement>(null);
 const [timingDraft,setTimingDraft]=useState(()=>projectTiming(p));
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
  return <label key={key} className={max>100?'study-full':''}>{label}{max>100?<textarea rows={key==='checked_description'?3:2} maxLength={max} disabled={disabled} value={key==='instruction'?observationGuidance(draft):draft[key]} placeholder={key==='checked_description'?'粘贴地方历史、构件特点及资料来源。例如：历史背景：……；观察重点：……。内容由老师核对。':key==='instruction'?'说明往哪里看、找什么；有需要时补充具体观察位置。':undefined} onChange={e=>change({...draft,[key]:e.target.value,...(key==='instruction'?{standing_position:''}:{})})}/>:<input maxLength={max} disabled={disabled} value={draft[key]} onChange={e=>change({...draft,[key]:e.target.value,...(key==='instruction'?{standing_position:''}:{})})}/>}</label>;
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
 const historySupplement=historyCase?.history?`历史背景：${historyCase.history}\n${draft.checked_description}\n资料来源：${historyCase.sources?.map(s=>`${s.title} ${s.url}`).join('；')||''}`:'';
 const script=p.heritage_script;
 const needsHistory=scriptDraft.intro.includes('【待补充历史背景】');
 const scriptOutdated=Boolean(script&&(script.station_version!==version||(script.timing_version||0)!==(p.heritage_timing_version||0)));
 const scriptConfirmed=scriptIsConfirmed(p)&&!dirty&&!scriptDirty&&!timingDirty;
 const scriptReviewHint=dirty?'讲解站资料有修改，请返回第1步或第2步保存。':!script?'请先生成或填写并保存脚本。':needsHistory?'请补充历史引入后保存脚本。':scriptDirty||timingDirty||scriptOutdated?'请先保存脚本，再核对台词。':!scriptConfirmed&&!scriptVerified?'核对三段台词后，勾选审核项即可继续。':'';
 const goToStory=()=>{setTab(3);setError('');setScriptError('');stageHeading.current?.focus({preventScroll:true});stageHeading.current?.scrollIntoView({block:'start'});};
 const continueToStory=()=>{
  if(scriptConfirmed){setNotice('');goToStory();return;}
  void run(async()=>{
   const reviewed=await reviewScript(p,current=>api<Project>(`/projects/${current.id}/heritage/confirm-script`,json('POST',{
    version:current.heritage_script?.version||0,teacher_verified:scriptVerified,timing_version:current.heritage_timing_version||0,
   })));
   onUpdated(reviewed);setNotice('研学脚本已确认，可继续制作水墨故事。');goToStory();
  },'script');
 };
 const steps=['讲解站资料','实拍标注','研学脚本','水墨故事','导出与试用'];
 const descriptions=['先填四项基础资料，保存时自动补全空白的任务草稿。','用学生视角的实拍照片标出目标，确认竖屏中的定位线索。','先讲一条地方历史，再观察实物、布置现场任务。','复用已确认镜头，或继续制作水墨故事段。','预览短片与任务卡，导出同一版已确认内容。'];
 return <div className="study-workspace">
  <nav className="ink-wizard-steps study-tabs" aria-label="研学制作步骤">{steps.map((label,i)=><button type="button" key={label} disabled={pending||working} aria-current={tab===i?'step':undefined} onClick={()=>{setTab(i);setError('');setNotice('');}}><span aria-hidden="true">{i+1}</span>{label}</button>)}</nav>
  <header className="ink-wizard-title study-stage-heading"><div><p>第 {tab+1} 步 / 共 {steps.length} 步</p><h2 ref={stageHeading} tabIndex={-1}>{steps[tab]}</h2><p>{descriptions[tab]}</p></div></header>
  {error?<p role="alert" className="ink-wizard-error study-error">{error}</p>:null}{notice?<p role="status" className="ink-wizard-review study-notice">{notice}</p>:null}
  {p.jobs[0]&&(['heritage-export','heritage-script'].includes(p.jobs[0].action))?<JobStatus jobs={[p.jobs[0]]}/>:null}
  {tab<=1?<>
   {tab===0?<section className="study-card"><header><h2>一个讲解站，一个观察目标</h2><p>填写建筑、观察目标、适用年级和研学资料即可开始，也可使用案例模板。第2步结合照片核对观察指引和问题。</p></header>
    <label>使用案例模板（可选）<select disabled={disabled||!cases.length} value={selectedCase} onChange={e=>{const c=cases.find(x=>x.id===e.target.value);setSelectedCase(e.target.value);if(c){change({...draft,...c.station});setError('');setNotice(`已填入“${c.title}”的资料，请核对后保存草稿。`);}}}><option value="" disabled>选择案例填入资料</option>{cases.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
    {selectedCase?<p className="study-hint" role="status">已选择：{cases.find(c=>c.id===selectedCase)?.title}。资料已填入下方表单，{dirty?'请核对后点击“保存草稿”。':'可继续编辑。'}</p>:null}
    <div className="study-two">{(['building','component','grade','checked_description'] as const).map(field)}</div>
    <div className="study-research-meta"><p className="study-hint">历史引入使用这里的地方历史，构件特点用于实物观察。</p>{historyCase?.history&&!draft.checked_description.includes(historyCase.history)?<button type="button" disabled={disabled||historySupplement.length>1500} onClick={()=>{change({...draft,checked_description:historySupplement});setNotice('已补入案例历史与来源，原有资料保留，请核对后保存。');}}>补入本案例历史</button>:null}{historyCase?.sources?.map(source=><a key={source.url} href={source.url} target="_blank" rel="noreferrer">历史资料来源</a>)}</div>
   </section>:<><section className="study-card"><h2>结合实拍照片，确定观察任务</h2><p>写清往哪里看、找什么；需要时在观察指引中补充具体位置。</p><div className="study-two">{(['instruction','question'] as const).map(field)}</div><details className="study-more"><summary>课程设置（可选）</summary><div className="study-two">{(['name','objective'] as const).map(field)}</div></details></section><div className="study-photo-grid">{(['panorama','detail'] as const).map(slot=><PhotoEditor key={slot} slot={slot} photo={draft[slot]} canGenerate={Boolean(draft.panorama?.mark)} derivedStale={slot==='detail'&&derivedDetailStale(draft)} onGenerate={slot==='detail'?()=>void run(async()=>{const current=dirty?await save():p;onUpdated(await api<Project>(`/projects/${p.id}/heritage/detail-from-mark`,json('POST',{version:current.heritage_version||0})));setNotice('特写已从定位图标注区域生成，标注与署名自动关联。');}):undefined} disabled={disabled} dirty={dirty} onChange={photo=>change({...draft,[slot]:photo})} onUpload={file=>void run(async()=>{const current=dirty?await save():p;const form=new FormData();form.append('file',file);onUpdated(await api<Project>(`/projects/${p.id}/heritage/photos/${slot}?version=${current.heritage_version||0}`,{method:'POST',body:form}));setNotice('照片已保存，已知素材的署名会自动带入，请完成标注。');})}/>)}</div></>}
   <footer className="study-form-footer">
    <p className="study-form-status" role="status">{tab===1?(stationConfirmed?'已确认':wasConfirmed?'待重新确认':'待确认'):dirty?'待保存':p.heritage_ready?'已确认':'已保存'}</p>
    {tab===1&&!stationConfirmed?<p className="study-review-note">点击确认，即表示历史与构件资料、标注及指引已核对，适合现场使用{draft.detail?(draft.detail.derived_from?'，特写与定位图标注已关联':'，全景与特写指向同一构件'):''}。</p>:null}
    <div className="study-actions">
     <button type="button" disabled={disabled||!dirty} onClick={()=>void run(async()=>{await save();setNotice('草稿已保存。');})}>保存草稿</button>
     {dirty?<button type="button" disabled={disabled} onClick={()=>{setDraft(p.heritage_station||blankStation());setDirty(false);setSelectedCase('');setNotice('');}}>撤销修改</button>:null}
     {tab===0?<button type="button" className="ink-primary-button" disabled={disabled} onClick={()=>void run(async()=>{if(dirty)await save();setTab(1);setNotice('请上传实拍照片，并核对观察指引和问题。');})}>{pending?'正在处理…':dirty?'保存并下一步':'下一步：实拍标注'}</button>:<button type="button" className="ink-primary-button" disabled={pending||working||(!stationConfirmed&&(readonly||busy))} onClick={continueToScript}>{pending?'正在确认…':stationConfirmed?'进入研学脚本':'确认并进入研学脚本'}</button>}
    </div>
   </footer>
  </>:null}
  {tab===2?<section className="study-card"><h2>{total}秒研学脚本</h2>
   <div className="study-timing">
    <div className="study-timing-fields">{(['intro','location','task'] as const).map((key,i)=><label key={key}>{['历史引入','实物观察','现场任务'][i]}（秒）<input type="number" min={3} max={180} step={1} value={timingDraft[key]||''} disabled={disabled} onChange={e=>setTimingDraft({...timingDraft,[key]:Number(e.target.value)})}/></label>)}</div>
    <div className="study-actions"><button type="button" disabled={disabled||!timingDirty||Boolean(durationError)} onClick={()=>void run(persistTiming)}>应用时长</button><span>{timingDirty?'时长待保存':`总时长 ${savedTotal} 秒`}</span></div>
    {timingDirty&&durationError?<p role="alert" className="ink-wizard-error study-error">{durationError}</p>:null}
   </div>
   <p>历史引入{timingDraft.intro}秒 → 实物观察{timingDraft.location}秒 → 现场任务{timingDraft.task}秒。{draft.detail?`实物观察按全景${observation.panorama}秒、特写${observation.detail}秒播放。`:''}</p>
   <div className="study-actions"><button disabled={disabled||Boolean(durationError)} onClick={()=>void run(async()=>{await persistTiming();onUpdated(await api<Project>(`/projects/${p.id}/heritage/script-template`,json('POST',{})));})}>使用资料生成模板（不调用模型）</button><button disabled={disabled||Boolean(durationError)} onClick={()=>void run(async()=>{await persistTiming();onUpdated(await api<Project>(`/projects/${p.id}/heritage/script-ai`,json('POST',{})));})}>AI起草（计费）</button></div>
   {needsHistory?<p className="ink-wizard-review study-notice">研学资料缺少地方历史。<button type="button" disabled={pending||working} onClick={()=>{setTab(0);setError('');setNotice('');}}>返回补充历史资料</button></p>:null}
   {(['intro','location','task'] as const).map((key,i)=><label key={key}>{[`历史引入 · 0–${timingDraft.intro}秒`,`实物观察 · ${timingDraft.intro}–${timingDraft.intro+timingDraft.location}秒`,`现场任务 · ${timingDraft.intro+timingDraft.location}–${total}秒`][i]}<textarea rows={3} maxLength={{intro:400,location:600,task:800}[key]} disabled={disabled} value={scriptDraft[key]} onChange={e=>{setScriptDraft({...scriptDraft,[key]:e.target.value});setScriptDirty(true);setScriptVerified(false);}}/></label>)}
   <footer className="study-script-footer">
    <div className="study-script-help">
     <p>历史段先讲一个重点，再引出构件；请核对模板和 AI 文案中的史实。</p>
     <p>未启用额外配音时，故事沿用原声，实拍段以字幕呈现任务。</p>
    </div>
    <section className="study-script-review" aria-label="脚本审核">
     <div className="study-script-review-heading"><h3>脚本审核</h3><span className="study-script-status" role="status">{scriptDirty||timingDirty||dirty?'待保存':!script?'未生成':scriptOutdated?'资料或时长已更新':scriptConfirmed?'已确认':'待确认'}</span></div>
     {!scriptConfirmed?<label className="study-check"><input type="checkbox" disabled={disabled||dirty||scriptDirty||timingDirty||scriptOutdated||!script||needsHistory} checked={scriptVerified} onChange={e=>setScriptVerified(e.target.checked)}/><span>我已审核台词，确认历史、构件名称和观察任务与资料一致</span></label>:null}
     <div className="study-actions study-script-actions">
      <button type="button" disabled={disabled||(!scriptDirty&&!timingDirty&&!scriptOutdated)||Boolean(durationError)||Object.values(scriptDraft).some(t=>!t.trim())} onClick={()=>void run(async()=>{const current=await persistTiming();onUpdated(await api<Project>(`/projects/${p.id}/heritage/script`,json('PUT',{...scriptDraft,version:current.heritage_script?.version||0,station_version:current.heritage_version||0,timing_version:current.heritage_timing_version||0})));},'script')}>保存脚本</button>
      {scriptDirty?<button type="button" disabled={disabled} onClick={()=>{setScriptDraft({intro:script?.intro||'',location:script?.location||'',task:script?.task||''});setScriptDirty(false);}}>撤销脚本修改</button>:null}
      <button type="button" className="ink-primary-button" aria-describedby={scriptError?'study-script-error':scriptReviewHint?'study-script-review-hint':undefined} disabled={pending||working||(!scriptConfirmed&&(disabled||!scriptVerified||dirty||scriptDirty||timingDirty||scriptOutdated||!script||needsHistory))} onClick={continueToStory}>{pending?'正在处理…':scriptConfirmed?'下一步：水墨故事':'确认并进入水墨故事'}</button>
     </div>
     {scriptReviewHint?<p id="study-script-review-hint" className="study-review-note">{scriptReviewHint}</p>:null}
     {scriptError?<p id="study-script-error" role="alert" className="ink-wizard-error study-error">{scriptError}</p>:null}
    </section>
   </footer>
  </section>:null}
  {tab===3?<>{timingDirty?<p className="ink-wizard-review study-notice">时长设置待保存。<button type="button" disabled={pending||working} onClick={()=>setTab(2)}>返回应用时长</button></p>:null}<section className="study-card"><h2>复用或制作水墨故事段</h2><p>选用不超过{savedTiming.intro}秒的已确认镜头。短于{savedTiming.intro}秒时，导出会停留在最后一帧补齐；不自动截掉对白。</p><label>从已有水墨项目选镜头<select disabled={disabled} value={source?.id||''} onChange={e=>{setSource(null);setSelected([]);if(e.target.value)void run(async()=>{setSource(await api<Project>(`/projects/${e.target.value}`));});}}><option value="">选择来源项目</option>{projects.filter(x=>x.id!==p.id&&x.project_type!=='heritage').map(x=><option key={x.id} value={x.id}>{x.title}</option>)}</select></label>
    {source?<><div className="study-source-shots">{source.shots.map((s,i)=><label className="study-check" key={s.id}><input type="checkbox" disabled={disabled||!s.rendered_url||s.image_stale||s.clip_stale||s.rendered_stale} checked={selected.includes(s.id)} onChange={e=>setSelected(e.target.checked?[...selected,s.id]:selected.filter(id=>id!==s.id))}/>第{i+1}镜 · {s.duration||5}秒{s.rendered_stale?' · 待更新':''}</label>)}</div><button disabled={disabled||!selected.length||timingDirty} onClick={()=>{if(p.shots.length&&!window.confirm('替换本研学项目的故事镜头？原文件保留，来源水墨项目不受影响。'))return;void run(async()=>{onUpdated(await api<Project>(`/projects/${p.id}/heritage/reuse-story`,json('POST',{source_project:source.id,shot_ids:selected,replace_confirmed:true})));setNotice('镜头已复制到本研学项目，来源项目保持原样。');});}}>导入所选镜头</button></>:null}
    <p className="study-hint">也可以继续使用下方原水墨流程制作角色、场景和故事镜头。最终{savedTotal}秒合成请回到“导出与试用”。</p></section>{story}</>:null}
  {tab===4?<>{timingDirty?<p className="ink-wizard-review study-notice">时长设置待保存。<button type="button" disabled={pending||working} onClick={()=>setTab(2)}>返回应用时长</button></p>:null}<section className="study-card"><h2>导出短片与观察任务卡</h2><p>两份交付物使用同版已确认照片、标注和任务。未现场核对前，不应直接用于带团。</p><label className="study-check"><input type="checkbox" checked={narration} disabled={disabled} onChange={e=>setNarration(e.target.checked)}/>为三段台词配音（调用在线语音，替换故事段原声）</label><div className="study-actions">{(['both','video','card'] as const).map((kind,i)=><button key={kind} className={i===0?'ink-primary-button':''} disabled={disabled||!p.heritage_ready||timingDirty} onClick={()=>void run(async()=>{onUpdated(await api<Project>(`/projects/${p.id}/heritage/export`,json('POST',{kind,version,narration,timing_version:p.heritage_timing_version||0})));})}>{['导出MP4与A4任务卡',`导出${savedTotal}秒短片`,'导出A4任务卡'][i]}</button>)}</div>{!p.heritage_ready?<p className="ink-wizard-error study-error">请先保存并确认实拍照片、有效标注与任务资料。</p>:null}
    {p.final_url?<div className="study-output"><video key={p.final_url} controls preload="metadata" src={p.final_url}/><p>{p.final_stale?'内容或时长已更新，此短片需重新导出。':`${savedTotal}秒短片已就绪。`}</p><a href={p.final_url} download>下载MP4</a></div>:null}
    {p.task_card_url?<div className="study-output"><p>{p.task_card_stale?'内容已更新，此任务卡需重新导出。':'一页A4观察任务卡已就绪。'}</p><a href={p.task_card_url} target="_blank" rel="noreferrer">查看任务卡PDF</a><a href={p.task_card_url} download>下载任务卡</a></div>:null}
    {p.heritage_chapters?<ol>{p.heritage_chapters.map((c,i)=><li key={c.video}>{i+1}. {{story:'历史引入',panorama:'全景观察',detail:'同一构件特写',task:'现场任务'}[c.kind]||c.kind} · {c.duration}秒</li>)}</ol>:null}
   </section><section className="study-card"><h3>现场试用记录（由老师填写）</h3><p>播放短片并发卡后，不再额外提示方向，记录学生是否能独立指出目标。</p><div className="study-two">{(['participants','found_without_hint','preparation_minutes'] as const).map((key,i)=><label key={key}>{['参与人数','无额外提示找到目标人数','老师实际备课耗时（分钟）'][i]}<input type="number" min={key==='participants'?1:0} value={trial[key]} disabled={disabled} onChange={e=>setTrial({...trial,[key]:Number(e.target.value)})}/></label>)}</div><label>观察记录<textarea value={trial.notes} maxLength={1500} disabled={disabled} onChange={e=>setTrial({...trial,notes:e.target.value})}/></label><button disabled={disabled} onClick={()=>void run(async()=>{onUpdated(await api<Project>(`/projects/${p.id}/heritage/trial`,json('PUT',trial)));setNotice('现场试用记录已保存。');})}>保存老师的试用记录</button></section></>:null}
 </div>;
}
