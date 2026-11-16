'use client';

import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Film, Settings2, Plus, Landmark } from 'lucide-react';
import './ink.css';
import ApiSettings from './ApiSettings';
import InkWizard from './InkWizard';
import HeritageWorkspace from './heritage/HeritageWorkspace';
import './heritage/heritage.css';
import type { Station } from './heritage/state';
import { api, json, names, type Me, type Summary, type Project, type Track, type Kind } from './ink-shared';

export default function InkPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [trialMode, setTrialMode] = useState(false);
  const [token, setToken] = useState('');
  const [projects, setProjects] = useState<Summary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [apiSettingsOpen, setApiSettingsOpen] = useState(false);
  const refresh = useCallback(async () => {
    const [user, list, music] = await Promise.all([api<Me>('/me'), api<{ projects: Summary[] }>('/projects'), api<{ tracks: Track[] }>('/music')]);
    setMe(user); setTrialMode(user.trial_mode); setProjects(list.projects); setTracks(music.tracks);
  }, []);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const settings = await api<{ trial_mode: boolean }>('/mode');
        if (!active) return;
        setTrialMode(settings.trial_mode);
        try { await refresh(); } catch (e) {
          if (active && !settings.trial_mode) setError(e instanceof Error ? e.message : '无法连接工作台');
        }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : '无法连接工作台'); }
      finally { if (active) setLoaded(true); }
    })();
    return () => { active = false; };
  }, [refresh]);
  const busy = Boolean(project?.jobs.some(j => j.state === 'running'));
  const pid = project?.id;
  useEffect(() => {
    if (!pid || !busy) return;
    let active = true;
    const timer = window.setInterval(() => {
      void api<Project>(`/projects/${pid}`).then(p => { if (active) { setProject(p); if (!p.jobs.some(j => j.state === 'running')) void refresh().catch(() => undefined); } }).catch(e => { if (active) setError(e.message); });
    }, 1800);
    return () => { active = false; window.clearInterval(timer); };
  }, [pid, busy, refresh]);
  const perform = async (fn: () => Promise<void>) => { setError(''); setWorking(true); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : '请求失败'); } finally { setWorking(false); } };
  const open = async (id: string) => { setProject(await api<Project>(`/projects/${id}`)); };
  const action = async (name: string, sid?: string, preset?: string): Promise<Project> => {
    if (!project) throw new Error('请先打开项目');
    const params = new URLSearchParams();
    if (sid) params.set('sid', sid);
    if (preset) params.set('preset', preset);
    await api(`/projects/${project.id}/actions/${name}?${params}`, { method: 'POST' });
    const updated = await api<Project>(`/projects/${project.id}`);
    setProject(updated);
    return updated;
  };
  const updateProject = (updated: Project) => { setProject(updated); return updated; };
  const readonly = Boolean(me?.trial_mode && (project?.owner !== me?.id || me?.ended));
  const label = 'block text-xs text-neutral-500 mb-2';
  const button = 'ink-primary-button';

  const studyProjects = projects.filter(item => item.project_type === 'heritage');
  const current = project;
  const wizard = current ? <InkWizard key={current.id} project={current} tracks={tracks} readonly={readonly} onWorkingChange={setWorking}
              onAction={action} onUpdated={updateProject}
              onSave={async (sid, data) => updateProject(await api<Project>(`/projects/${current.id}/shots/${sid}`, json('PATCH', data)))}
              onUpload={async (sid, file) => { const form = new FormData(); form.append('file', file); return updateProject(await api<Project>(`/projects/${current.id}/shots/${sid}/image`, { method: 'POST', body: form })); }}
              onLock={async (sid, data) => updateProject(await api<Project>(`/projects/${current.id}/baseline/${sid}`, json('POST', data)))}
              onVoices={async voices => updateProject(await api<Project>(`/projects/${current.id}/voices`, json('POST', { voices })))}
              onMusic={async id => updateProject(await api<Project>(`/projects/${current.id}/music`, json('POST', { id })))}
              onClone={async () => { const copy = await api<Project>(`/projects/${current.id}/clone`, { method: 'POST' }); setProject(copy); await refresh(); }}
            /> : null;
  const createStudy = async (caseId: string) => {
    const data = await api<{templates:{id:string;title:string;station:Partial<Station>}[]}>('/heritage/templates');
    const example = data.templates.find(x=>x.id===caseId);
    let created = await api<Project>('/projects',json('POST',{project_type:'heritage',title:example?.title||'新建古建讲解站',script:'研学故事待老师编辑与确认。'}));
    if(example) created=await api<Project>(`/projects/${created.id}/heritage/station`,json('PUT',{version:0,station:example.station}));
    setProject(created);await refresh();
  };
  return <main className={`ink-page h-full overflow-y-auto ${project ? 'ink-page-workspace' : 'ink-page-home'}`}>
    <div className="ink-shell">
      <header className="ink-hero">
        <div>
          {project ? <button type="button" disabled={working || busy} onClick={() => { setProject(null); setError(''); }} className="ink-back"><ArrowLeft size={15} aria-hidden="true" />返回创作首页</button> : null}
          <h1>{project ? project.title : '古建研学水墨短片工作台'}</h1>
          <p>{project ? project.project_type === 'heritage' ? '从讲解站资料到实拍定位，让学生自己找到实物。' : '跟着步骤，把故事做成一条水墨短片。' : '从一处古建构件出发，制作讲解短片与观察任务卡'}</p>
        </div>
        {me && !me.trial_mode ? <button type="button" className="ink-secondary-button ink-api-entry" onClick={() => setApiSettingsOpen(true)}><Settings2 size={16} aria-hidden="true" />模型与 API</button> : null}
        {me?.trial_mode ? <div className="text-xs text-neutral-500 space-y-2"><p>{me.local ? '本机开发试用' : '受邀试用'} · {me.id}</p><button type="button" onClick={() => perform(async () => { await api('/logout', { method: 'POST' }); setMe(null); setProject(null); })} className="underline">退出</button></div> : null}
      </header>
      {error ? <p role="alert" className="border border-red-200 bg-white text-red-700 rounded-lg p-4 text-sm mb-5">{error}</p> : null}
      {!loaded ? <p role="status">正在加载工作台…</p> : !me ? !trialMode ? <section className="max-w-lg bg-white border rounded-xl p-7"><h2 className="font-medium">暂时无法连接工作台</h2><p className="text-sm text-neutral-500 mt-3">请确认后端服务已启动，然后刷新页面。</p><button type="button" onClick={() => window.location.reload()} className={button + " mt-4"}>重新连接</button></section> : <section className="max-w-lg bg-white border rounded-xl p-7">
        <h2 className="font-medium text-lg">进入古建研学工作台</h2><p className="text-sm leading-6 text-neutral-500 mt-3 mb-5">仅面向受邀用户。项目和上传素材在试用组内可见；修改他人作品前需要先复制。试用结束后保留7天。</p>
        <form onSubmit={e => { e.preventDefault(); void perform(async () => { await api('/login', json('POST', { token })); await refresh(); }); }}><label className={label}>邀请码（本机未设置邀请时可留空）<input type="password" value={token} autoComplete="off" onChange={e => setToken(e.target.value)} className="mt-2 w-full border rounded-md p-3 text-neutral-900" /></label><button disabled={working} className={button}>进入试用</button></form>
      </section> : <>
        {me.trial_mode ? <div className="flex flex-wrap gap-3 text-xs mb-6">{(Object.keys(names).filter(k => ['text', 'vl', 'image', 'video', 'speech'].includes(k)) as Kind[]).map(k => <span key={k} className="border rounded-md px-3 py-2 bg-white">{names[k]} {me.usage[k] || 0} / {me.limits[k] || 0}次</span>)}</div> : null}
        {me.trial_mode && Object.values(me.limits).every(n => n === 0) ? <p className="text-sm bg-white border rounded-lg p-4 mb-6 text-neutral-600">当前真实生成额度为0。可以创建项目；生成前需由负责人设置额度。试作不会自动调用付费模型。</p> : null}
        {project ? <div className="ink-workspace-toolbar">
          <div className="ink-project-switcher"><select aria-label="切换创作项目" value={project.id} disabled={working || busy} onChange={e => perform(() => open(e.target.value))}>{studyProjects.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select><button type="button" disabled={working || busy} onClick={() => { setProject(null); }} className="ink-icon-button" aria-label="新建创作"><Plus size={18} /></button></div>
        </div> : null}
        <div className="ink-content">
          <div className="min-w-0">
            {!project ? <>
              <section className="study-entry" aria-labelledby="study-entry-title">
                <div className="ink-section-heading"><h2 id="study-entry-title">古建研学</h2><button type="button" className="ink-secondary-button" disabled={working} onClick={()=>void perform(()=>createStudy(''))}><Plus size={14} aria-hidden="true"/>空白讲解站</button></div>
                <p>从一处构件开始，制作水墨故事、实拍定位与观察任务卡。</p>
                <div className="ink-example-grid study-case-grid">{[
                  {id:'baoguo',title:'保国寺 · 找斗拱',description:'沿着柱子向上，观察木构件如何层层伸出',tag:'斗拱 · 实拍定位'},
                  {id:'ningyuan',title:'宁远文庙 · 找柱础',description:'从角柱全景，找到同一柱脚的石狮',tag:'柱础 · 全景与特写'},
                  {id:'taihe',title:'太和殿 · 找小兽',description:'先定位屋角，再观察排成一列的小兽',tag:'屋角 · 远景与特写'},
                ].map(example=><button key={example.id} type="button" className="ink-example-card" disabled={working} onClick={()=>void perform(()=>createStudy(example.id))}><div className="ink-example-media"><Landmark size={25} strokeWidth={1.5} aria-hidden="true"/><span className="ink-example-use">使用模板<ArrowRight size={13} aria-hidden="true"/></span></div><div className="ink-example-copy"><h3>{example.title}</h3><p>{example.description}</p><span>{example.tag}</span></div></button>)}</div>
              </section>
              {studyProjects.length ? <section className="ink-recent" aria-labelledby="ink-recent-title"><div className="ink-section-heading"><h2 id="ink-recent-title">最近创作</h2><span>{studyProjects.length}个项目</span></div><div className="ink-recent-grid">{studyProjects.map(item => <button key={item.id} type="button" className="ink-recent-card" disabled={working} onClick={() => perform(() => open(item.id))}><span className="ink-recent-icon"><Film size={19} strokeWidth={1.5} aria-hidden="true" /></span><span className="ink-recent-copy"><strong>{item.title}</strong><span>{!me.trial_mode || item.owner === me.id ? '继续创作' : '查看项目'}</span></span><ArrowRight size={15} aria-hidden="true" /></button>)}</div></section> : null}
            </> : project.project_type === 'heritage' ? <HeritageWorkspace key={project.id} project={project} projects={projects} readonly={readonly} working={working} onUpdated={updateProject} onWorkingChange={setWorking} story={wizard} /> : wizard}
          </div>
        </div>
        {me.trial_mode ? <footer className="mt-12 border-t pt-5 text-xs text-neutral-500 flex flex-wrap justify-between gap-4"><p>素材与结果在组内共享。模型会处理本次任务所需的内容；请使用有权提供的素材。</p><button type="button" disabled={busy || working || Boolean(me.trial_mode && me.ended)} onClick={() => { if (window.confirm('结束本轮试用？之后仅可查看下载，7天后素材到期清理。')) void perform(async () => { await api('/end-trial', { method: 'POST' }); await refresh(); }); }} className="underline disabled:opacity-35">{me.ended ? '试用已结束，保留期内可下载' : '结束我的试用（开始7天保留期）'}</button></footer> : null}
      </>}
    </div>
    {apiSettingsOpen ? <ApiSettings onClose={() => setApiSettingsOpen(false)} onSaved={refresh} busy={busy} /> : null}
  </main>;
}
