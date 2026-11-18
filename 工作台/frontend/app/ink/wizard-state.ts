import type { Project, Shot } from './ink-shared';
export const wizardSteps = ['剧本', '创作设定', '分镜', '画面', '视频', '成片'];
const studySteps = ['剧本', '分镜', '素材与画风', '画面', '视频', '成片'];
export const wizardStepsFor = (p: Project) => p.project_type === 'heritage' ? studySteps : wizardSteps;
export const setupStageFor = (p: Project) => p.project_type === 'heritage' ? 2 : 1;
export const storyboardStageFor = (p: Project) => p.project_type === 'heritage' ? 1 : 2;
export const wizardStorageKey = (p: Project) => `ink.wizard.${p.project_type === 'heritage' ? 'v3' : 'v2'}.${p.id}`;
export function restoredWizardStage(p: Project, saved: number | undefined, legacy = false) {
  const mapped = legacy && p.project_type === 'heritage' ? saved === 1 ? 2 : saved === 2 ? 1 : saved : saved;
  return resumeStage(p, mapped);
}
export const imageReady = (s: Shot) => Boolean(s.image_url && !s.image_stale);
export function imageGenerationPlan(shot:Pick<Shot,'image_url'|'image_stale'>,number?:number):{label:string;mode:'direct'|'preview'} {
  if(shot.image_url)return {label:shot.image_stale?'按新分镜重新生成':'重新生成图片',mode:'preview'};
  return {label:number?`生成第 ${number} 镜图片`:'生成图片',mode:'direct'};
}
export const clipReady = (s: Shot) => imageReady(s) && Boolean(s.clip_url && !s.clip_stale);
export const soundReady = (s: Shot) => clipReady(s) && Boolean(s.rendered_url && !s.rendered_stale);
// A retained video remains viewable even when it needs explicit confirmation.
export const previewVideo = (s: Shot) => soundReady(s) ? s.rendered_url : s.clip_url || s.rendered_url;
export function videoEditSource(versions: { video: string; video_url: string; current: boolean }[], currentPreview: string | null | undefined) {
  return versions.find(v => v.video_url === currentPreview)?.video || versions.find(v => v.current)?.video || '';
}
export function missingCharacters(p: Project) {
  const needed = new Set(p.shots.flatMap(s => s.character_ids));
  const known = new Set(p.baseline?.characters.map(c => c.character_id) || []);
  return p.characters.filter(c => needed.has(c.id) && !known.has(c.id));
}
export function unlockedStage(p: Project) {
  if (!p.story_confirmed && !p.shots.length) return 0;
  if (p.project_type === 'heritage') {
    if (!p.shots.length || !p.storyboard_confirmed || p.heritage_story_stale) return 1;
    if (!p.creative_settings || p.creative_draft) return 2;
  } else {
    if (!p.creative_settings) return 1;
    if (!p.shots.length || !p.storyboard_confirmed) return 2;
  }
  if (!p.shots.every(imageReady)) return 3;
  if (!p.shots.every(soundReady)) return 4;
  return 5;
}
export function resumeStage(p: Project, saved?: number) {
  const max = unlockedStage(p);
  return typeof saved === 'number' && Number.isInteger(saved) && saved >= 0 ? Math.min(saved, max) : max;
}
export function referenceShot(p: Project) {
  const missing = new Set(missingCharacters(p).map(c => c.id));
  return p.shots.find(s => s.character_ids.some(id => missing.has(id))) || p.shots[0];
}

export function adjustmentPlan(p: Project, original: Shot, draft: Shot, stage: number) {
  const visual = (['content', 'scene', 'camera', 'motion', 'scene_id', 'prop_ids', 'character_ids'] as const).some(k => JSON.stringify(original[k]) !== JSON.stringify(draft[k]));
  const timing = (original.duration ?? 5) !== (draft.duration ?? 5);
  const dialogue = JSON.stringify(original.dialogues) !== JSON.stringify(draft.dialogues.filter(d => d.text.trim()));
  if (!visual && !dialogue && !timing) {
    if (stage >= 3 && p.baseline && draft.character_ids.every(id => p.baseline!.characters.some(c => c.character_id === id))) {
      return { changed: false, action: 'image', label: original.image_url ? '按当前设定修改图片' : '按当前设定生成图片', hint: '有图片时直接编辑当前图。生成成功后替换显示，原图保留。' };
    }
    return { changed: false, action: '', label: '未作修改', hint: '' };
  }
  if (stage <= 2) return { changed: true, action: '', label: '保存分镜', hint: '保存后，继续确认分镜。' };
  if (visual) {
    const known = new Set(p.baseline?.characters.map(c => c.character_id) || []);
    if (!p.baseline || draft.character_ids.some(id => !known.has(id))) return { changed: true, action: '', label: '保存并确定人物画风', hint: '先确定新增人物，再生成图片。' };
    return { changed: true, action: 'image', label: original.image_url ? '保存并修改当前图片' : '保存并生成图片', hint: '按本次调整生成图片；已有图片作为编辑对象，原图保留。' };
  }
  if (timing) return { changed: true, action: '', label: '保存时长', hint: '时长已保存，已有视频需要重新生成。' };
  if (dialogue && stage >= 4 && clipReady(original)) return { changed: true, action: 'sound', label: '保存并更新配音字幕', hint: '更新本镜配音与字幕，图片和视频画面不变。' };
  return { changed: true, action: '', label: '保存调整', hint: '台词已设定，将在第5步添加配音时应用。' };
}

export function nextShotStep(shots: Shot[], currentId: string, ready: (shot: Shot) => boolean) {
  const index = shots.findIndex(s => s.id === currentId);
  const following = shots[index + 1];
  if (following) return { shot: following, returning: false, number: index + 2 };
  const pending = shots.findIndex(s => !ready(s));
  return pending >= 0 ? { shot: shots[pending], returning: true, number: pending + 1 } : null;
}
