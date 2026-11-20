import { ArrowRight, Film, Plus, Trash2 } from 'lucide-react';
import Image from 'next/image';
import type { ReactNode } from 'react';
import { heritageBrandName } from '@/config/brand';
import type { Me, Summary } from '../ink-shared';
import './heritage-home.css';

const art = '/heritage-home';
const templates = [
  { id: 'baoguo', title: '保国寺 · 找斗拱' },
  { id: 'ningyuan', title: '宁远文庙 · 找柱础' },
  { id: 'taihe', title: '太和殿 · 找小兽' },
];

type HeritageHomeProps = {
  me: Me | null;
  projects: Summary[];
  working: boolean;
  account: ReactNode;
  feedback: ReactNode;
  onSettings: () => void;
  onCreate: (caseId: string) => void;
  onOpen: (id: string) => void;
  onRemove: (project: Summary) => void;
};

type HeritageHeaderProps = {
  children?: ReactNode;
  onGoHome?: () => void;
  homeDisabled?: boolean;
};

export function HeritageHeader({ children, onGoHome, homeDisabled }: HeritageHeaderProps) {
  const logo = <Image src={`${art}/logo.svg`} width={44} height={32} alt="" unoptimized />;
  return <header className="heritage-home-header">
    <div className="heritage-home-frame heritage-home-header-inner">
      <div className="heritage-home-brand">
        {onGoHome ? (
          <button type="button" className="heritage-home-brand-mark" aria-label="返回创作首页" title="返回创作首页" disabled={homeDisabled} onClick={onGoHome}>
            {logo}
          </button>
        ) : <span className="heritage-home-brand-mark">{logo}</span>}
        <span>{heritageBrandName}</span>
      </div>
      {children}
    </div>
  </header>;
}

export default function HeritageHome({ me, projects, working, account, feedback, onSettings, onCreate, onOpen, onRemove }: HeritageHomeProps) {
  return <>
    <HeritageHeader>
      {me && !me.trial_mode ? <button type="button" className="heritage-home-settings" onClick={onSettings}>模型与 API</button> : account}
    </HeritageHeader>

    <section className="heritage-home-hero" aria-labelledby="heritage-home-title">
      <picture className="heritage-home-hero-art">
        <source media="(max-width: 899px)" srcSet={`${art}/banner-mobile.webp`} />
        <img src={`${art}/banner.webp`} width={1920} height={368} alt="" fetchPriority="high" />
      </picture>
      <div className="heritage-home-frame heritage-home-hero-inner">
        <div className="heritage-home-hero-copy">
          <h1 id="heritage-home-title">让古建故事，走进孩子的<span className="heritage-home-title-mark">眼里</span></h1>
          <p>从一处古建构件出发，制作讲解短片与观察任务卡</p>
          <button type="button" className="heritage-home-create" disabled={!me || working} onClick={() => onCreate('')}>
            <Plus size={16} aria-hidden="true" />新建讲解站
          </button>
        </div>
      </div>
    </section>

    {feedback ? <div className="heritage-home-frame heritage-home-feedback">{feedback}</div> : null}

    {me ? <div className="heritage-home-frame heritage-home-content">
      <section className="heritage-home-templates" aria-labelledby="heritage-home-templates">
        <h2 id="heritage-home-templates" className="heritage-home-section-title">案例模板</h2>
        <div className="heritage-home-grid">
          {templates.map(template => <button key={template.id} type="button" className="heritage-home-template" disabled={working} onClick={() => onCreate(template.id)}>
            <Image className="heritage-home-template-art" src={`${art}/${template.id}.webp`} width={1152} height={480} alt="" unoptimized />
            <span className="heritage-home-template-footer">
              <strong>{template.title}</strong>
              <span className="heritage-home-template-action">使用模板<ArrowRight size={15} aria-hidden="true" /></span>
            </span>
          </button>)}
        </div>
      </section>

      {projects.length ? <section className="heritage-home-recent" aria-labelledby="heritage-home-recent">
        <h2 id="heritage-home-recent" className="heritage-home-section-title">最近创作</h2>
        <div className="heritage-home-grid">
          {projects.map(project => {
            const editable = !me.trial_mode || (project.owner === me.id && !me.ended);
            return <div key={project.id} className="heritage-home-project">
              <button type="button" className="heritage-home-project-open" disabled={working} onClick={() => onOpen(project.id)} title={project.title}>
                <span className="heritage-home-project-art">
                  {project.cover_url ? <Image src={project.cover_url} width={144} height={64} alt="" unoptimized /> : <Film size={20} strokeWidth={1.5} aria-hidden="true" />}
                </span>
                <span className="heritage-home-project-copy">
                  <strong>{project.title}</strong>
                  <span>{editable ? '讲解短片 · 观察任务卡' : '查看项目'}</span>
                </span>
              </button>
              {editable ? <button type="button" className="heritage-home-project-remove" disabled={working} aria-label={`移除项目 ${project.title}`} title="移除项目" onClick={() => onRemove(project)}>
                <Trash2 size={16} aria-hidden="true" />
              </button> : null}
            </div>;
          })}
        </div>
      </section> : null}
    </div> : null}
  </>;
}
