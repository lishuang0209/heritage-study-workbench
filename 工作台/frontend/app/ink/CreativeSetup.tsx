'use client';
import { useEffect, useRef, useState } from 'react';
import { Film, Plus, Settings2, Upload, X, LoaderCircle, Trash2, RotateCcw } from 'lucide-react';
import { api, json, inkPresets, type CreativeSettings, type Project, type SettingAsset } from './ink-shared';
import { setupSteps, setupSignature, confirmedSetupReviews, isSetupReviewed, nextSetupStep, setupGenerationJob, setupMaterialSettings, setupImagePresentation, type SetupStep, type SetupGeneration } from './creative-setup-state';
import JobStatus from './JobStatus';
import {missingGuideReference} from './heritage/guide-state';
import { HistoryBadge, HistoryVersions, type HistoryMeta } from './HistoryVersions';

type Props = { project: Project; disabled: boolean; run: (fn: () => Promise<unknown>) => Promise<void>; onUpdated: (p: Project) => Project; onConfirmed: () => void; onExtract: () => Promise<Project>; onPrimaryLabel: (label: string) => void };
type Group = SetupStep['group'];
const styleSampleSuffix: Record<Group, string> = { characters: '', scenes: '-empty', props: '-props' };
const presetStyle = (preset: typeof inkPresets[number]) => `水墨风格 · ${preset.name}，${preset.description}，${preset.techniques.join('、')}，留白${preset.whitespace}，晕染${preset.bleed_strength}，低饱和配色，${preset.id === 'soft' ? '细微绢本质感' : '自然宣纸质感'}`;
const selectedPreset = (style: string) => inkPresets.find(preset => style.includes(preset.name) || (preset.id === 'bold' && style.includes('泼墨大写意')) || style.includes(({soft:'清淡柔和',simple:'简单干净',bold:'浓墨有力'} as Record<string,string>)[preset.id]));
type SettingVersion = HistoryMeta & {image:string; image_url:string; created:number; source:string; style:string};
const labels = { characters:'角色', scenes:'场景', props:'道具' };
function initial(p: Project): CreativeSettings {
  return setupMaterialSettings(p.creative_draft || p.creative_settings || {
    characters:p.characters.map(c=>({...c,desc:p.baseline?.characters.find(x=>x.character_id===c.id)?.desc||c.desc})),
    scenes:[...new Set(p.shots.map(s=>s.scene).filter(Boolean))].map((name,i)=>({id:`scene${i+1}`,name,desc:name})),
    props:[],style:presetStyle(inkPresets[1]),
  },p.project_type==='heritage');
}
export default function CreativeSetup({project:p,disabled,run,onUpdated,onConfirmed,onExtract,onPrimaryLabel}:Props) {
  const seed=JSON.stringify(initial(p));
  const [data,setData]=useState<CreativeSettings>(()=>initial(p));
  const [selected,setSelected]=useState('');
  const [reviewed,setReviewed]=useState<Record<string,string>>({});
  const reviewStorageKey = 'ink.setup.review.v1.' + p.id;
  const [restoredReviewKey,setRestoredReviewKey]=useState('');
  useEffect(()=>{
    let saved: {reviewed?:Record<string,unknown>;selected?:unknown} | null = null;
    try { saved=JSON.parse(localStorage.getItem(reviewStorageKey)||'null'); } catch { /* Keep working if storage is unavailable. */ }
    const entries=saved?.reviewed && typeof saved.reviewed==='object' ? Object.entries(saved.reviewed) : [];
    setReviewed(Object.fromEntries(entries.filter((entry): entry is [string,string] => typeof entry[1]==='string')));
    setSelected(typeof saved?.selected==='string'?saved.selected:'');
    setRestoredReviewKey(reviewStorageKey);
  },[reviewStorageKey]);
  useEffect(()=>{
    if(restoredReviewKey!==reviewStorageKey)return;
    try { localStorage.setItem(reviewStorageKey,JSON.stringify({reviewed,selected})); } catch { /* Keep working if storage is unavailable. */ }
  },[reviewStorageKey,restoredReviewKey,reviewed,selected]);
  const [editor,setEditor]=useState<{group:Group;asset:SettingAsset;isNew:boolean;style:string}|null>(null);
  const dialog=useRef<HTMLDialogElement>(null);
  const upload=useRef<HTMLInputElement>(null);
  const historyDialog=useRef<HTMLDialogElement>(null);
  const [history,setHistory]=useState<{group:Group;asset:SettingAsset;items:SettingVersion[]}|null>(null);
  const [historyMessage,setHistoryMessage]=useState('');
  const [historyError,setHistoryError]=useState('');
  useEffect(()=>{if(history&&!historyDialog.current?.open)historyDialog.current?.showModal();},[history]);
  const [editError,setEditError]=useState('');
  const [generation,setGeneration]=useState<SetupGeneration|null>(null);
  const feedbackRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{setData(JSON.parse(seed));},[seed]);
  useEffect(()=>{if(editor) dialog.current?.showModal();},[editor]);
  const heritage=p.project_type==='heritage';
  const steps=setupSteps(data,heritage);
  const index=Math.max(0,steps.findIndex(x=>x.key===selected));
  const current=steps[index];
  const item=current.asset;
  const presentation=setupImagePresentation(current.group,heritage,!!item?.image);
  const signature=(step:SetupStep)=>setupSignature(step,data.style);
  const needsGuideReference=missingGuideReference(p,data);
  const guideSelected=current.group==='characters'&&item?.id===p.heritage_guide?.character_id;
  const savedReviews=confirmedSetupReviews(p.creative_settings);
  const isReviewed=(step:SetupStep)=>!(needsGuideReference&&step.asset?.id===p.heritage_guide?.character_id)&&isSetupReviewed(step,data.style,reviewed,savedReviews);
  const needsExtraction=!data.characters.length&&!data.scenes.length&&!data.props.length;
  const next=nextSetupStep(steps,current.key,isReviewed);
  const reviewedCount=steps.filter(isReviewed).length;
  const nextName=next?.step.asset?.name || (next ? labels[next.step.group] : '');
  const label=needsExtraction?'从剧本整理设定':!item&&current.group==='scenes'?'添加场景':next
    ? '确认'+labels[current.group]+'，'+(next.returning?'返回检查':'继续')+nextName
    : heritage?'确认素材与画风，进入画面':'确认完成，进入分镜';
  useEffect(()=>{onPrimaryLabel(label);},[label,onPrimaryLabel]);
  const openEditor=(isNew=false,group:Group=current.group)=>{
    const id=group==='characters'?['c1','c2'].find(id=>!data.characters.some(c=>c.id===id)):`${group}_${crypto.randomUUID().slice(0,8)}`;
    if(isNew&&!id)return;
    setEditError('');setEditor({group,isNew,asset:isNew?{id:id!,name:'',desc:''}:{...item!},style:data.style});
  };
  const generateImage = (redesign = false) => {
    if(disabled || !item)return;
    const request:SetupGeneration={key:current.key,name:item.name,style:selectedPreset(data.style)?.name || '所选画风',
      job:{id:crypto.randomUUID(),action:'asset-image',state:'submitting',error:'',created:Date.now()/1000}};
    setGeneration(request);
    void run(async () => {
      try {
        const updated = await api<Project>(`/projects/${p.id}/generate-setting-image`, json('POST', {
          settings: data, group: current.group, asset_id: item.id, redesign,
          view: presentation.view,
        }));
        const job=updated.jobs[0];
        if(!job || job.action!=='asset-image')throw new Error('暂未读到生成任务状态，请重新打开项目查看任务记录。');
        setGeneration(previous=>previous?.job.id===request.job.id?{...request,job}:previous);
        onUpdated(updated);
      } catch(error) {
        setGeneration(previous=>previous?.job.id===request.job.id?{...request,job:{...request.job,state:'submit-failed',error:error instanceof Error?error.message:'生成请求提交失败，请检查连接。'}}:previous);
      }
    });
  };
  const generationJob=setupGenerationJob(p.jobs,generation,current.key);
  const generating=generationJob?.state==='running'||generationJob?.state==='submitting';
  const feedbackId=`setting-generation-feedback-${p.id}`;
  useEffect(()=>{
    if(generation?.key!==current.key || !generationJob)return;
    const frame=window.requestAnimationFrame(()=>feedbackRef.current?.scrollIntoView({block:'nearest'}));
    return()=>window.cancelAnimationFrame(frame);
  },[generation?.key,current.key,generationJob?.id,generationJob?.state]);
  const confirm=()=>void run(async()=>{
    if(needsExtraction){await onExtract();return;}
    if(!item&&current.group==='scenes'){openEditor(true);return;}
    if(needsGuideReference&&(guideSelected||!next))throw new Error('请先生成或上传小向导角色参考图，再确认继续。');
    setReviewed(previous=>({...previous,[current.key]:signature(current)}));
    if(next){setSelected(next.step.key);return;}
    onUpdated(await api<Project>(`/projects/${p.id}/creative-settings`,json('PUT',data)));onConfirmed();
  });

  const changeHistory=(version:SettingVersion,restore=false)=>void run(async()=>{
    if(!history)return;
    setHistoryMessage('');setHistoryError('');
    try {
      const scope=encodeURIComponent(history.group+':'+history.asset.id);
      const path=`/projects/${p.id}/history/setting/${scope}/${encodeURIComponent(version.image)}`;
      await api(path+(restore?'/restore':''),json(restore?'POST':'DELETE',{}));
      const result=await api<{items:SettingVersion[]}>(`/projects/${p.id}/setting-history/${history.group}/${history.asset.id}?include_deleted=true`);
      setHistory(previous=>previous?{...previous,items:result.items}:previous);
      setHistoryMessage(restore?'已恢复到历史列表，当前图片保持不变。':'已移到“已删除版本”，可随时恢复。');
    } catch(error) {setHistoryError(error instanceof Error?error.message:'历史版本操作失败，请重试');}
  });

  return <>
    <form id="creative-settings-form" className="ink-setup-form" onSubmit={e=>{e.preventDefault();confirm();}}>
      <div className="ink-setup-toolbar"><div><h3>{heritage?'分镜所需素材':'设定素材'}</h3>{!needsExtraction ? <span className="ink-story-status" data-ready={reviewedCount === steps.length || undefined}>已确认 {reviewedCount} / {steps.length}</span> : null}</div>{heritage ? <p className="ink-wizard-footnote">建筑与构件素材依据研学资料生成。</p> : !needsExtraction?<details className="ink-setup-more"><summary>更多</summary><button type="button" disabled={disabled} onClick={e=>{e.currentTarget.closest('details')?.removeAttribute('open');if(window.confirm('重新整理会调用文本模型并替换未确认的设定草稿，继续吗？'))void run(onExtract);}}>重新从剧本整理</button></details>:null}</div>
      {heritage&&(!data.characters.length||!data.props.length)?<div className="ink-wizard-secondary">{!data.characters.length?<button type="button" disabled={disabled} onClick={()=>openEditor(true,'characters')}><Plus size={14}/>添加角色（可选）</button>:null}{!data.props.length?<button type="button" disabled={disabled} onClick={()=>openEditor(true,'props')}><Plus size={14}/>添加构件或道具（可选）</button>:null}</div>:null}
      <nav className="ink-wizard-thumbs ink-setup-asset-rail" aria-label="角色场景道具">{steps.map((step,i)=><button type="button" key={step.key} disabled={disabled} aria-current={i===index?'true':undefined} onClick={()=>setSelected(step.key)}>
        <span className="ink-setup-tile-preview">{step.asset?.image ? <img src={`/api/ink/projects/${p.id}/assets/${step.asset.image}`} alt=""/> : <Film size={22}/>}</span>
        <span className="ink-setup-tile-copy"><strong>{step.asset?.name||labels[step.group]}</strong><small>{labels[step.group]}</small>{isReviewed(step) ? <span className="ink-story-status" data-ready="true">已确认</span> : null}</span>
      </button>)}<button type="button" className="ink-setup-add" disabled={disabled||(current.group==='characters'&&data.characters.length>=2)||(current.group==='scenes'&&data.scenes.length>=12)||(current.group==='props'&&data.props.length>=20)} onClick={()=>openEditor(true)} title={current.group==='characters'&&data.characters.length>=2?'最多支持两位角色':`添加${labels[current.group]}`}><Plus size={22}/><span>添加{labels[current.group]}</span></button></nav>
      {next?.returning?<p className="ink-wizard-footnote" role="status">前面还有设定未确认，确认当前{labels[current.group]}后将返回检查“{nextName}”。</p>:null}
      <section className="ink-wizard-scene ink-story-media-layout ink-setup-media-layout">
        <div className="ink-story-media-panel"><div className={`ink-wizard-media ${current.group==='characters'?'ink-character-sheet':''}`}>{item?.image?<a href={`/api/ink/projects/${p.id}/assets/${item.image}`} target="_blank" rel="noreferrer"><img src={`/api/ink/projects/${p.id}/assets/${item.image}`} alt={`${item.name}设定图`}/></a>:<div><Film size={42}/><p>{presentation.placeholder}</p></div>}</div></div>

        <div className="ink-wizard-scene-copy ink-story-media-copy"><p className="ink-wizard-eyebrow">{labels[current.group]} · {index+1} / {steps.length}</p><h3>{item?.name||`确认${labels[current.group]}`}</h3><p>{item?.desc||(current.group==='scenes'?'添加故事发生的场景。':`没有${labels[current.group]}可以直接继续。`)}</p>
          {guideSelected&&!item?.image?<p className="ink-wizard-review" role="status">先生成或上传小向导参考图，后续出镜画面会复用同一形象。</p>:null}
          {item?<><div className="ink-wizard-style-picker"><fieldset className="ink-style-options"><legend>水墨类型</legend><div className="ink-style-card-grid">{inkPresets.map(preset=><label key={preset.id} className={`ink-style-choice ${selectedPreset(data.style)?.id===preset.id?'is-selected':''} ${disabled?'is-disabled':''}`}><img src={`/ink-styles/${preset.id}${styleSampleSuffix[current.group]}.png?v=asset-types-20261111`} alt=""/><span className="ink-style-choice-name"><input type="radio" name="creative-ink-style" value={preset.id} checked={selectedPreset(data.style)?.id===preset.id} disabled={disabled} onChange={()=>{setData(d=>({...d,style:presetStyle(preset)}));}}/><strong>{preset.name}</strong></span><small>{preset.description}</small></label>)}</div></fieldset><p className="ink-wizard-footnote" role="status">当前画风：{selectedPreset(data.style)?.name || '自定义'}。{presentation.hint}</p></div>
          <div className="ink-wizard-secondary ink-setup-image-actions"><button type="button" className="ink-primary-button" disabled={disabled||generating||!data.scenes.length} aria-busy={generating} aria-describedby={generationJob?feedbackId:undefined} onClick={()=>generateImage()}>{generating?<><LoaderCircle size={15} className="ink-job-spinner"/>{generationJob?.state==='submitting'?'正在提交…':'正在生成…'}</>:presentation.label}</button>{current.group==='characters' && item.image ? <button type="button" disabled={disabled} onClick={()=>{if(window.confirm('重新设计将按当前文字生成新形象，不参考当前角色图。原图保留在历史图片中。'))generateImage(true);}}>重新设计角色</button>:null}<button type="button" disabled={disabled} onClick={()=>openEditor()}><Settings2 size={14}/>调整</button><button type="button" disabled={disabled} onClick={()=>upload.current?.click()}><Upload size={14}/>上传图片</button><button type="button" disabled={disabled} onClick={()=>void run(async()=>{const result=await api<{items:SettingVersion[]}>(`/projects/${p.id}/setting-history/${current.group}/${item.id}?include_deleted=true`);setHistoryMessage('');setHistoryError('');setHistory({group:current.group,asset:item,items:result.items});})}>历史图片</button></div></>:null}

          {generationJob ? <div ref={feedbackRef} id={feedbackId} className="ink-setup-feedback"><JobStatus jobs={[generationJob]} title={generation?.key===current.key?`生成${labels[current.group]}图 · ${generation.name}`:undefined} successHint={generation?`已按${generation.style}完成生成并更新图片，请核对主体与画风后再确认。`:undefined}/></div> : null}
          <p className="ink-wizard-footnote">{guideSelected?'小向导参考图用于统一脸型、发型和服装。':'设定图可选。整理剧本和生成图片会调用模型，确认继续不会。'}</p>
        </div>
      </section>
      <input ref={upload} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" disabled={disabled} aria-label="上传设定参考图" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file&&item)void run(async()=>{const form=new FormData();form.append('file',file);const result=await api<{image:string}>(`/projects/${p.id}/setting-image`,{method:'POST',body:form});onUpdated(await api<Project>(`/projects/${p.id}/select-setting-image`,json('POST',{settings:data,group:current.group,asset_id:item.id,image:result.image,source:'upload'})));});}}/>
    </form>
    {history?<dialog ref={historyDialog} className="ink-wizard-dialog" data-layout="history" aria-labelledby="setting-history-title" onCancel={e=>{e.preventDefault();if(!disabled)setHistory(null);}}>
      <header><h2 id="setting-history-title">{history.asset.name} · 历史图片</h2><button type="button" aria-label="关闭历史图片" disabled={disabled} onClick={()=>setHistory(null)}><X size={20}/></button></header>
      <div className="ink-wizard-dialog-body"><p>采用只替换图片，保留文字和画风。删除的版本可以恢复，使用中的版本不能删除。</p>
        {historyMessage?<p role="status" className="ink-history-feedback">{historyMessage}</p>:null}
        {historyError?<p role="alert" className="ink-wizard-error">{historyError}</p>:null}
        <HistoryVersions items={history.items} itemKey={version=>version.image} renderItem={version=><>
          <a href={version.image_url} target="_blank" rel="noreferrer"><img src={version.image_url} alt={`${history.asset.name}历史版本`}/></a>
          <div className="ink-history-meta"><strong>{version.source==='generated'?'生成图片':version.source==='upload'?'上传图片':'已保存图片'}</strong>
            {version.deleted_at?<HistoryBadge state="deleted">已删除</HistoryBadge>:history.asset.image===version.image?<HistoryBadge state="using">正在使用</HistoryBadge>:version.can_delete===false?<HistoryBadge state="reference">设定使用中</HistoryBadge>:null}
          </div><small>{new Date(version.created*1000).toLocaleString('zh-CN')}</small>
          <div className="ink-history-actions"><a href={version.image_url} target="_blank" rel="noreferrer">查看</a><a href={version.image_url} download>下载</a>
            {version.deleted_at?<button type="button" disabled={disabled} onClick={()=>changeHistory(version,true)}><RotateCcw size={14}/>恢复版本</button>:<>
              {history.asset.image!==version.image?<button type="button" disabled={disabled} onClick={()=>void run(async()=>{onUpdated(await api<Project>(`/projects/${p.id}/select-setting-image`,json('POST',{settings:data,group:history.group,asset_id:history.asset.id,image:version.image,source:'history'})));setHistory(null);})}>采用这一版</button>:null}
              <button type="button" disabled={disabled||version.can_delete===false||history.asset.image===version.image} title={version.delete_block_reason||undefined} onClick={()=>changeHistory(version)}><Trash2 size={14}/>删除</button>
            </>}
          </div></>}/>
      </div></dialog>:null}
    {editor?<dialog ref={dialog} className="ink-wizard-dialog" aria-labelledby="setup-edit-title" onCancel={e=>{e.preventDefault();if(!disabled)setEditor(null);}}><header><h2 id="setup-edit-title">{editor.isNew?'添加':'调整'}{labels[editor.group]}</h2><button type="button" disabled={disabled} aria-label="关闭调整" onClick={()=>setEditor(null)}><X size={20}/></button></header><form onSubmit={e=>{e.preventDefault();if(!editor.asset.name.trim()||!editor.asset.desc.trim()||!editor.style.trim()){setEditError('请填写名称、固定特征和画风');return;}const items=editor.isNew?[...data[editor.group],editor.asset]:data[editor.group].map(x=>x.id===editor.asset.id?editor.asset:x);setData({...data,[editor.group]:items,style:editor.style});setSelected(`${editor.group}:${editor.asset.id}`);setEditor(null);}}><div className="ink-wizard-dialog-body"><label>名称<input required maxLength={40} value={editor.asset.name} onChange={e=>setEditor({...editor,asset:{...editor.asset,name:e.target.value}})}/></label><label>{editor.group==='characters'?'外貌与服饰':editor.group==='scenes'?'环境与布局':'外观与材质'}<textarea required rows={4} maxLength={1500} value={editor.asset.desc} onChange={e=>setEditor({...editor,asset:{...editor.asset,desc:e.target.value}})}/></label><details><summary>调整统一画风</summary><textarea required maxLength={1000} value={editor.style} onChange={e=>setEditor({...editor,style:e.target.value})}/></details>{editError?<p role="alert">{editError}</p>:null}{!editor.isNew?<button type="button" className="ink-wizard-text-button" disabled={disabled} onClick={()=>{setData({...data,[editor.group]:data[editor.group].filter(x=>x.id!==editor.asset.id)});setSelected('');setEditor(null);}}>移除这个{labels[editor.group]}</button>:null}</div><footer><button className="ink-primary-button" disabled={disabled}>保存调整</button></footer></form></dialog>:null}
  </>;
}
