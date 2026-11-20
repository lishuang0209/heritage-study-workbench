'use client';

import { useCallback, useEffect, useState } from 'react';
import Select from '@/components/Select';
import { ArrowLeft, Settings2, Plus } from 'lucide-react';
import Image from 'next/image';
import './ink.css';
import ApiSettings from './ApiSettings';
import InkWizard from './InkWizard';
import HeritageHome, { HeritageHeader } from './heritage/HeritageHome';
import HeritageWorkspace from './heritage/HeritageWorkspace';
import './heritage/heritage.css';
import './heritage/workflow-brand.css';
import type { Station } from './heritage/state';
import { api, json, names, type Me, type Summary, type Project, type Track } from './ink-shared';

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
    window.scrollTo(0, 0);
  }, [pid]);
  useEffect(() => {
    if (!pid || !busy) return;
    let active = true;
    const timer = window.setInterval(() => {
      void api<Project>(`/projects/${pid}`).then(p => { if (active) { setProject(p); if (!p.jobs.some(j => j.state === 'running')) void refresh().catch(() => undefined); } }).catch(e => { if (active) setError(e.message); });
    }, 1800);
    return () => { active = false; window.clearInterval(timer); };
  }, [pid, busy, refresh]);
  const perform = async (fn: () => Promise<void>) => { setError(''); setWorking(true); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : '请求失败'); } finally { setWorking(false); } };
  const open = async (id: string) => {
    let opened = await api<Project>(`/projects/${id}`);
    const canEdit = !me?.trial_mode || (opened.owner === me.id && !me.ended);
    if (opened.project_type === 'heritage' && canEdit && !opened.jobs.some(j => j.state === 'running') &&
        [opened.heritage_station?.panorama, opened.heritage_station?.detail].some(photo => photo && (!photo.source.trim() || !photo.author.trim() || !photo.license.trim()))) {
      opened = await api<Project>(`/projects/${id}/heritage/photo-credits`, json('POST', {version: opened.heritage_version || 0}));
    }
    setProject(opened);
  };
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
  const studyProjects = projects.filter(item => item.project_type === 'heritage' && !item.archived);
  const baoguoExample = projects.find(item => item.id === '81ba6cf4f7f944ee80467852db0c6c71');
  const current = project;
  const wizard = (onExport?:()=>void) => current ? <InkWizard key={current.id} project={current} tracks={tracks} readonly={readonly} onWorkingChange={setWorking} onExport={onExport}
              onAction={action} onUpdated={updateProject}
              onSave={async (sid, data) => updateProject(await api<Project>(`/projects/${current.id}/shots/${sid}`, json('PATCH', data)))}
              onUpload={async (sid, file) => { const form = new FormData(); form.append('file', file); return updateProject(await api<Project>(`/projects/${current.id}/shots/${sid}/image`, { method: 'POST', body: form })); }}
              onLock={async (sid, data) => updateProject(await api<Project>(`/projects/${current.id}/baseline/${sid}`, json('POST', data)))}
              onVoices={async voices => updateProject(await api<Project>(`/projects/${current.id}/voices`, json('POST', { voices })))}
              onMusic={async id => updateProject(await api<Project>(`/projects/${current.id}/music`, json('POST', { id })))}
              onClone={async () => { const copy = await api<Project>(`/projects/${current.id}/clone`, { method: 'POST' }); setProject(copy); await refresh(); }}
            /> : null;
  const createStudy = async (caseId: string) => {
    if (caseId === 'baoguo' && baoguoExample) {
      const copy = await api<Project>(`/projects/${baoguoExample.id}/clone`, { method: 'POST' });
      setProject(copy);
      await refresh();
      return;
    }
    const data = await api<{templates:{id:string;title:string;station:Partial<Station>}[]}>('/heritage/templates');
    const example = data.templates.find(x=>x.id===caseId);
    let created = await api<Project>('/projects',json('POST',{project_type:'heritage',title:example?.title||'新建古建讲解站',script:'研学故事待老师编辑与确认。'}));
    if(example) created=await api<Project>(`/projects/${created.id}/heritage/station`,json('PUT',{version:0,station:example.station}));
    setProject(created);await refresh();
  };
  const account = me?.trial_mode ? <div className="text-xs text-neutral-500 space-y-2 shrink-0">
    <p>{me.local ? '本机开发试用' : '受邀试用'} · {me.id}</p>
    <button type="button" onClick={() => perform(async () => {
      await api('/logout', { method: 'POST' });
      setMe(null);
      setProject(null);
    })} className="underline">退出</button>
  </div> : null;

  const problem = error ? <p role="alert" className="heritage-workspace-alert">{error}</p> : null;
  const loading = !loaded ? <p role="status">正在加载工作台…</p> : null;

  const trialOverview = me?.trial_mode ? <>
    <div className="flex flex-wrap gap-3 text-xs mb-6">
      {(['text', 'vl', 'image', 'video', 'speech'] as const).map(kind => <span key={kind} className="border rounded-md px-3 py-2 bg-white">
        {names[kind]} {me.usage[kind] || 0} / {me.limits[kind] || 0}次
      </span>)}
    </div>
    {Object.values(me.limits).every(n => n === 0) ? <p className="text-sm bg-white border rounded-lg p-4 mb-6 text-neutral-600">当前真实生成额度为0。可以创建项目；生成前需由负责人设置额度。试作不会自动调用付费模型。</p> : null}
  </> : null;
  const trialFooter = me?.trial_mode ? <footer className="mt-12 border-t pt-5 text-xs text-neutral-500 flex flex-wrap justify-between gap-4">
    <p>素材与结果在组内共享。模型会处理本次任务所需的内容；请使用有权提供的素材。</p>
    <button type="button" disabled={busy || working || Boolean(me.ended)} onClick={() => {
      if (window.confirm('结束本轮试用？之后仅可查看下载，7天后素材到期清理。')) {
        void perform(async () => { await api('/end-trial', { method: 'POST' }); await refresh(); });
      }
    }} className="underline disabled:opacity-35">
      {me.ended ? '试用已结束，保留期内可下载' : '结束我的试用（开始7天保留期）'}
    </button>
  </footer> : null;
  const settings = apiSettingsOpen ? <ApiSettings onClose={() => setApiSettingsOpen(false)} onSaved={refresh} busy={busy} /> : null;
  const goHome = () => { setProject(null); setError(''); };

  if (loaded && !me) {
    const heading = trialMode ? '进入古建研学工作台' : '暂时无法连接工作台';
    return <main className="ink-page ink-page-home heritage-access min-h-screen">
      <HeritageHeader />
      <div className="heritage-home-frame heritage-access-inner">
        <section className="heritage-access-card" aria-labelledby="heritage-access-title">
          <div className="heritage-access-copy">
            {!trialMode ? <p className="heritage-access-status"><span aria-hidden="true" />连接未建立</p> : null}
            <h1 id="heritage-access-title">{heading}</h1>
            {trialMode ? <>
              <p>仅面向受邀用户。项目和上传素材在试用组内可见。<br />修改他人作品前需要先复制，试用结束后保留 7 天。</p>
              <form onSubmit={e => {
                e.preventDefault();
                void perform(async () => { await api('/login', json('POST', { token })); await refresh(); });
              }}>
                <label>邀请码
                  <input type="password" value={token} placeholder="本机未设置邀请时可留空" autoComplete="off" onChange={e => setToken(e.target.value)} />
                </label>
                {problem}
                <button type="submit" disabled={working} className="ink-primary-button">{working ? '正在进入…' : '进入试用'}</button>
              </form>
            </> : <>
              <p>请确认后端服务已启动，然后刷新页面。</p>
              {problem}
              <button type="button" onClick={() => window.location.reload()} className="ink-primary-button">重新连接</button>
            </>}
          </div>
          <Image className="heritage-access-art" src={trialMode ? '/heritage-home/baoguo.webp' : '/heritage-home/banner-mobile.webp'} alt="" width={920} height={512} unoptimized />
        </section>
      </div>
    </main>;
  }

  if (!project) {
    return <main className="ink-page ink-page-home min-h-screen">
      <HeritageHome me={me} projects={studyProjects} working={working} account={account}
        feedback={problem || loading || trialOverview ? <>{problem}{loading}{trialOverview}</> : null}
        onSettings={() => setApiSettingsOpen(true)}
        onCreate={caseId => void perform(() => createStudy(caseId))}
        onOpen={id => void perform(() => open(id))}
        onRemove={item => {
          if (window.confirm(`从最近创作移除“${item.title}”？项目资料会保留在本机。`)) {
            void perform(async () => { await api(`/projects/${item.id}`, { method: 'DELETE' }); await refresh(); });
          }
        }}
      />
      {trialFooter ? <div className="heritage-home-frame pb-10">{trialFooter}</div> : null}
      {settings}
    </main>;
  }

  if (project.project_type === 'heritage') {
    return <main className="ink-page ink-page-workspace ink-page-heritage min-h-screen">
      <HeritageHeader onGoHome={goHome} homeDisabled={working || busy}>
        {me && !me.trial_mode ? <button type="button" className="ink-secondary-button heritage-workspace-settings" onClick={() => setApiSettingsOpen(true)}>模型与 API</button> : account}
      </HeritageHeader>
      <div className="ink-shell">
        <nav className="heritage-workspace-breadcrumb" aria-label="当前位置">
          <ol>
            <li><button type="button" disabled={working || busy} onClick={goHome}>创作首页</button></li>
            <li aria-hidden="true" className="heritage-workspace-breadcrumb-divider">/</li>
            <li aria-current="page">{project.title}</li>
          </ol>
        </nav>
        {problem}
        {trialOverview}
        <HeritageWorkspace key={project.id} project={project} projects={projects.filter(item => !item.archived)} readonly={readonly} working={working} onUpdated={updateProject} onWorkingChange={setWorking} story={wizard} />
        {trialFooter}
      </div>
      {settings}
    </main>;
  }

  return <main className="ink-page ink-page-workspace h-full overflow-y-auto">
    <div className="ink-shell">
      <header className="ink-hero">
        <div>
          <button type="button" disabled={working || busy} onClick={goHome} className="ink-back"><ArrowLeft size={15} aria-hidden="true" />返回创作首页</button>
          <h1>{project.title}</h1>
          <p>跟着步骤，把故事做成一条水墨短片。</p>
        </div>
        {me && !me.trial_mode ? <button type="button" className="ink-secondary-button ink-api-entry" onClick={() => setApiSettingsOpen(true)}><Settings2 size={16} aria-hidden="true" />模型与 API</button> : account}
      </header>
      {problem}
      {loading || <>
        {trialOverview}
        <div className="ink-workspace-toolbar">
          <div className="ink-project-switcher">
            <Select aria-label="切换创作项目" value={project.id} disabled={working || busy} onChange={e => perform(() => open(e.target.value))}>
              {studyProjects.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
            </Select>
            <button type="button" disabled={working || busy} onClick={() => setProject(null)} className="ink-icon-button" aria-label="新建创作"><Plus size={18} aria-hidden="true" /></button>
          </div>
        </div>
        <div className="ink-content">
          <div className="min-w-0">
            {wizard()}
          </div>
        </div>
        {trialFooter}
      </>}
    </div>
    {settings}
  </main>;
}
