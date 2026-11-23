import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import styles from "./page.module.css";

const name = "古建研学水墨短片工作台";
const description = "整理讲解资料、标注实拍照片，制作古建研学短片和 A4 观察任务卡。";

export const metadata: Metadata = {
  title: name,
  description,
  openGraph: { title: name, description, type: "website", locale: "zh_CN" },
};

const photoSource = "https://commons.wikimedia.org/wiki/File:Ningbo_Baoguo_Si_2013.07.27_10-34-40.jpg";
const steps = [
  ["整理讲解资料", "录入或上传资料，定下这次要讲的建筑、目标构件和适用年级。"],
  ["标注实拍与审核脚本", "在照片上标出观察点，根据资料起草脚本，由老师核对。"],
  ["制作水墨短片与任务卡", "制作水墨镜头，导出同一确认版本的宽屏短片和 A4 任务卡。"],
] as const;

function Brand() {
  return (
    <a className={styles.brand} href="#top">
      <Image src="/heritage-home/logo.svg" alt="" width={44} height={32} unoptimized />
      <span>{name}</span>
    </a>
  );
}

function Worksheet() {
  return (
    <div className={styles.sheet}>
      <p className={styles.sheetLabel}>古建研学 / 任务卡示意</p>
      <p className={styles.sheetTitle}>保国寺 · 找斗拱</p>
      <Image
        src="/heritage-landing/baoguo-observation.webp"
        alt="保国寺大殿东檐实拍，红框标出本次要观察的木构件"
        width={280}
        height={290}
        unoptimized
      />
      <p className={styles.sheetPrompt}>沿着照片里标出的柱子向上找。</p>
      <p className={styles.sheetQuestion}>哪一层木构件伸得最远？</p>
      <span className={styles.answerLines} aria-hidden="true" />
    </div>
  );
}

export default function HeritageLandingPage() {
  return (
    <div className={styles.page} id="top">
      <a className={styles.skip} href="#main-content">跳到主要内容</a>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Brand />
          <nav className={styles.nav} aria-label="宣传页导航">
            <a className={styles.navLink} href="#case">案例展示</a>
            <a className={styles.navLink} href="#process">制作流程</a>
            <Link className={styles.quietButton} href="/ink" prefetch={false}>
              进入工作台
            </Link>
          </nav>
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        <section className={`${styles.container} ${styles.hero}`} aria-labelledby="hero-title">
          <div>
            <p className={styles.audience}>给研学老师与课程团队</p>
            <h1 id="hero-title" className={styles.heroTitle}>从一处古建构件，<br />做成一站研学课</h1>
            <p className={styles.heroCopy}>
              用水墨故事引出历史，用实拍标注带孩子找到构件。把最后一个问题，留给他们在现场回答。
            </p>
            <a className={styles.primaryButton} href="#case">查看保国寺案例</a>
          </div>
          <figure className={styles.heroArt}>
            <Image
              src="/heritage-home/banner-mobile.webp"
              alt="水墨画中的山寺、松树和石阶"
              width={1200}
              height={679}
              fetchPriority="high"
              loading="eager"
              unoptimized
            />
            <figcaption>山寺水墨意象</figcaption>
          </figure>
        </section>

        <section id="case" className={`${styles.container} ${styles.caseSection}`} aria-labelledby="case-title">
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.kicker}>案例展示</p>
              <h2 id="case-title">保国寺 · 找斗拱</h2>
            </div>
            <p>从认出斗拱，到看清一层层伸出的木构件。</p>
          </div>
          <div className={styles.caseGrid}>
            <figure className={styles.caseArt}>
              <Image
                src="/heritage-home/baoguo.webp"
                alt="用水墨描绘的柱头与多层斗拱"
                width={1152}
                height={480}
                unoptimized
              />
              <figcaption className={styles.format}>水墨示意</figcaption>
            </figure>
            <div className={styles.observation}>
              <p className={styles.kicker}>宁波保国寺大殿</p>
              <h3>哪一层木构件<br />伸得最远？</h3>
              <p className={styles.observationCopy}>
                看完短片，沿着实拍照片标出的柱子向上找，再指一指同一组斗拱里向外伸出的部分。
              </p>
              <p className={styles.objective}>教学目标 · 从照片线索对应到现场实物</p>
            </div>
          </div>
        </section>

        <section className={styles.deliverables} aria-labelledby="deliverables-title">
          <div className={styles.container}>
            <p className={styles.kicker}>课前准备与现场观察</p>
            <h2 id="deliverables-title">一站内容，两种交付物</h2>
            <div className={styles.deliverableGrid}>
              <article className={styles.deliverable}>
                <figure className={styles.film}>
                  <Image
                    src="/heritage-landing/baoguo-film.webp"
                    alt="保国寺研学成片画面，小向导站在水墨绘制的大殿前"
                    width={960}
                    height={540}
                    unoptimized
                  />
                  <figcaption className={styles.format}>16:9 · MP4</figcaption>
                </figure>
                <div className={styles.deliverableCopy}>
                  <h3>宽屏研学短片</h3>
                  <p>在课堂或集合时播放，串联历史引入、实物观察与现场任务。</p>
                </div>
              </article>
              <article className={`${styles.deliverable} ${styles.taskCard}`}>
                <div className={styles.taskCopy}>
                  <p className={styles.format}>A4 · PDF</p>
                  <h3>观察任务卡</h3>
                  <p>带着标注照片、寻找指令和观察问题，到现场观察。</p>
                </div>
                <div className={styles.taskPreview}>
                  <Worksheet />
                </div>
              </article>
            </div>
            <p className={styles.credit}>
              实拍图 <a href={photoSource}>Zhangzhugang · Wikimedia Commons</a>
              {" · "}<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>
              {" · 已裁切及标注"}
            </p>
          </div>
        </section>

        <section id="process" className={`${styles.container} ${styles.process}`} aria-labelledby="process-title">
          <h2 id="process-title">把讲解资料变成研学内容</h2>
          <ol className={styles.steps} role="list">
            {steps.map(([title, text], index) => (
              <li key={title} className={styles.step}>
                <span className={styles.stepNumber} aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={`${styles.container} ${styles.action}`} aria-labelledby="action-title">
          <div className={styles.actionInner}>
            <h2 id="action-title">为下一次研学，备好一站课。</h2>
            <Link className={styles.lightButton} href="/ink" prefetch={false}>进入工作台</Link>
          </div>
        </section>
      </main>

      <footer className={`${styles.container} ${styles.footer}`}><Brand /></footer>
    </div>
  );
}
