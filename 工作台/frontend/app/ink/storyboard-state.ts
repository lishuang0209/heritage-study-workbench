import type { Project, Shot } from './ink-shared';

export type ShotFields = Pick<Shot, 'duration' | 'content' | 'scene' | 'camera' | 'motion' | 'character_ids' | 'scene_id' | 'prop_ids' | 'dialogues'>;

// Edit the saved storyboard, never a pending image candidate's snapshot.
export function shotFields(shot: ShotFields): ShotFields {
  return {
    duration: shot.duration ?? 5, content: shot.content, scene: shot.scene, camera: shot.camera, motion: shot.motion,
    character_ids: [...shot.character_ids], scene_id: shot.scene_id || null,
    prop_ids: [...(shot.prop_ids || [])], dialogues: shot.dialogues.map(line => ({ ...line })),
  };
}

export function newShotFields(project: Project): ShotFields {
  const settings = project.creative_settings || (project.project_type === 'heritage' ? project.creative_draft : null);
  const last = project.shots.at(-1);
  const scene = settings?.scenes.find(item => item.id === last?.scene_id)
    || settings?.scenes[0];
  return { duration: project.video_durations?.includes(5) !== false ? 5 : project.video_durations[0], content: '', scene: scene?.name || '', scene_id: scene?.id || null,
    camera: '', motion: '', character_ids: [], prop_ids: [], dialogues: [] };
}

export function shotFieldsChanged(original: ShotFields, draft: ShotFields): boolean {
  return JSON.stringify(shotFields(original)) !== JSON.stringify(shotFields(draft));
}

export function storyboardImageStatus(shot: Shot): string {
  if (shot.image_stale && shot.image_url) return '图片待更新';
  if (shot.image_proposal) return '候选待确认';
  if (shot.image_url) return '图片已就绪';
  return '待出图';
}

// Removed settings must remain visible as an unsaved correction, not hidden IDs
// that make the editor impossible to save.
export function reconcileShotFields(project: Project, shot: ShotFields): ShotFields {
  const result = shotFields(shot);
  result.character_ids = result.character_ids.filter(id => project.characters.some(item => item.id === id));
  result.dialogues = result.dialogues.filter(line => line.character_id === 'narrator' || result.character_ids.includes(line.character_id));
  const settings = project.creative_settings || (project.project_type === 'heritage' ? project.creative_draft : null);
  if (settings) {
    result.prop_ids = result.prop_ids!.filter(id => settings.props.some(item => item.id === id));
    if (!settings.scenes.some(item => item.id === result.scene_id)) result.scene_id = null;
  }
  return result;
}
