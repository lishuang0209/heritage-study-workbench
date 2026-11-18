import type { HeritageFields } from './heritage/state';
export type Kind = 'text' | 'vl' | 'image' | 'video' | 'speech';
export type Me = { trial_mode: boolean; id: string; local: boolean; limits: Record<Kind, number>; usage: Partial<Record<Kind, number>>; ended: number | null; models: Record<string, string> };
export type InkCaption = {
  characters: { character_id: string | null; desc: string; visibility: string; match_status: string }[];
  scene: { description: string; light_direction: string };
  camera: { shot_size: string; angle: string; composition: string };
  ink_style: { techniques: string[]; whitespace: string; bleed_strength: string; paper_texture: string; palette: string[] };
  uncertainties: string[];
};
export type SettingAsset = { views?: Record<string, { image: string; source: string; style: string; description: string }>; id: string; name: string; desc: string; image?: string | null };
export type CreativeSettings = { characters: SettingAsset[]; scenes: SettingAsset[]; props: SettingAsset[]; style: string };
export type Cast = { id: string; name: string; desc: string };
export type Dialogue = { character_id: string; text: string };
export type ImageDraft = { mode: 'detail' | 'redesign' | 'style'; instruction: string; shot: Pick<Shot, 'duration' | 'content' | 'scene' | 'camera' | 'motion' | 'character_ids' | 'scene_id' | 'prop_ids' | 'dialogues'> };
export type Shot = { video_edit_draft?: {video: string; instruction: string} | null; video_proposal?: {id: string; video: string; video_url: string; source: string; source_url: string; instruction: string} | null; spatial_warnings?: string[]; clip?: string | null; audio_source?: string; media_step?: 'sound' | 'complete'; video_settings?: { mode?: string; end_shot_id?: string | null; motion: string; camera: string }; id: string; duration?: number; content: string; scene: string; camera: string; motion: string; character_ids: string[]; scene_id?: string | null; prop_ids?: string[]; dialogues: Dialogue[];
  study_visit?:{stage:string;label:string;space:'exterior'|'entrance'|'interior';viewpoint:string}; study_topic?: string; research_evidence?: {id: string; source: 'material' | 'narration' | 'instruction'; quote: string; elements: string[]}[];
  image: string | null; image_url: string | null; clip_url: string | null; rendered_url: string | null; image_stale: boolean; image_stale_reason?: string | null; clip_stale: boolean; rendered_stale: boolean;
  image_draft?: ImageDraft | null; image_proposal?: ImageDraft & { id: string; image_url: string; change_warning?: string | null; style_check?: { message: string; techniques: string[]; uncertainties: string[] } } | null; image_undo?: unknown;
  candidate: InkCaption | null; image_versions?: string[]; image_baseline_version?: number; differences: string[]; revision: number };
export type DeletedShot = { id: string; shot_id: string; index: number; scene: string; content: string; deleted_at: number };
export type Job = { id: string; action: string; state: string; error: string; created?: number; progress?: {message:string;completed:number;total:number;updated?:number} | null };
export type SceneLayout = { scene_id: string; enabled: boolean; placements: { character_id: string; anchor: string }[]; relation: string; references: { shot_id: string; image: string }[] };
export type Project = HeritageFields & { scene_layouts?: SceneLayout[]; spatial_version?: number; video_modes?: {id:string;label:string;model:string;supported:boolean;durations:number[];native_audio?:boolean}[]; storyboard_draft?: {shots: Shot[]; characters: Cast[]} | null; video_durations?: number[]; background?: {era: string; source: 'user' | 'unspecified'}; id: string; owner: string; title: string; script: string; characters: Cast[]; shots: Shot[]; deleted_shots?: DeletedShot[];
  story_confirmed?: boolean; storyboard_confirmed?: boolean; creative_settings?: CreativeSettings | null; creative_draft?: CreativeSettings | null;
  baseline: { reference_images?: string[]; version: number; characters: InkCaption['characters']; ink_style: InkCaption['ink_style'] } | null; jobs: Job[];
  voices?: Record<string, string>; final_url: string | null; final_stale: boolean; music_credit: { title: string; license: string } | null;
  feedback: { visual: string; saved_work: string; audio: string; previous_method: string } | null };
export type Summary = Pick<Project, 'id' | 'title' | 'owner' | 'project_type'> & { cover_url?: string | null; archived?: boolean };
export type Track = { id: string; title: string; license: string };

export const names: Record<string, string> = { text: '拆分镜', vl: '读图', image: '出图', video: '视频', speech: '配音', settings: '提取创作设定', 'asset-image': '生成设定图', split: '拆分镜', preview: '生成候选图', 'video-preview': '局部调整视频', 'heritage-script': '研学脚本起草', 'heritage-export': '研学短片与任务卡导出', reference: '准备参考图', caption: '识别人物与画风', sound: '配音与字幕', assemble: '拼接短片' };

export const inkTechniqueLabels: Record<string, string> = {
  '泼墨': '大片墨色', '枯笔飞白': '干笔纹理', '工笔细线条': '细线条',
  '淡墨晕染': '浅墨晕开', '焦墨重墨': '浓墨', '水墨速写': '速写笔触', '简笔写意': '简笔轮廓',
};
export const inkPresets = [
  { id: 'soft', name: '工笔淡彩', description: '细线薄染，清雅淡彩', techniques: ['工笔细线条', '淡墨晕染'], whitespace: '多', bleed_strength: '弱' },
  { id: 'simple', name: '兼工带写', description: '人物细致，衣景写意', techniques: ['工笔细线条', '简笔写意', '淡墨晕染'], whitespace: '多', bleed_strength: '弱' },
  { id: 'bold', name: '泼墨写意', description: '大笔墨韵，留白传神', techniques: ['泼墨', '枯笔飞白', '焦墨重墨'], whitespace: '中', bleed_strength: '中' },
];
export function matchedInkPreset(style: InkCaption['ink_style']) {
  return inkPresets.find(p => p.techniques.length === style.techniques.length && p.techniques.every(tag => style.techniques.includes(tag)) && p.whitespace === style.whitespace && p.bleed_strength === style.bleed_strength);
}

export const inkOptionLabels: Record<string, Record<string, string>> = {
  whitespace: { '少': '空白较少', '中': '空白适中', '多': '空白较多', uncertain: '暂时看不准' },
  bleed_strength: { '无': '没有散开', '弱': '轻微散开', '中': '适度散开', '强': '明显散开', uncertain: '暂时看不准' },
  paper_texture: { '可见': '能看到纸张纹理', '未见': '看不到纸张纹理', uncertain: '暂时看不准' },
};
export const inkPaletteLabels: Record<string, string> = { '低饱和赭石': '柔和的棕黄色', '青灰冷调': '偏冷的青灰色', '素墨黑白': '黑白墨色', '其他': '其他颜色', uncertain: '暂时看不准' };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api/ink' + path, { ...init, credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}），请检查输入后重试`);
  }
  return response.json();
}

export function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
