import type { CreativeSettings, SettingAsset, Job } from './ink-shared';

export type SetupGeneration = {key:string;name:string;style:string;job:Job};

export function setupMaterialSettings(settings:CreativeSettings,heritage=false):CreativeSettings {
  if(!heritage)return settings;
  return {...settings,...Object.fromEntries((['scenes','props'] as const).map(group=>[group,settings[group].map(asset=>{
    const legacy=asset.desc.trim()==='依据已上传实拍中的可见建筑与空间关系，不补造不可见结构。' ||
      asset.desc.trim()===`依据实拍标注中的${asset.name}，保留可见形制及连接关系。`;
    return legacy?{...asset,desc:group==='scenes'?`依据研学资料呈现${asset.name}的完整外观、建筑体量与整体布局。`:`依据研学资料呈现${asset.name}的完整形制、层叠与连接关系。`}:asset;
  })]))};
}

export function setupImagePresentation(group:SetupStep['group'],heritage:boolean,hasImage:boolean) {
  if(heritage && group!=='characters') {
    const scene=group==='scenes';
    return {view:'front' as const,label:hasImage?'重新生成图片':'生成图片',
      placeholder:scene?'生成一张建筑全景图':'生成一张完整构件图',
      hint:scene?'依据研学资料生成单张建筑全景。':'依据研学资料生成单张完整构件图。'};
  }
  return {view:group==='characters'?'sheet' as const:'front' as const,
    label:group==='characters'?'生成三视图':hasImage?'重新生成':'生成图片',
    placeholder:group==='characters'?'生成正面、侧面、背面三视图':'可以生成或上传参考图',
    hint:group==='characters' && hasImage?'依据当前角色生成正面、侧面、背面三视图，采用所选画风。':'生成时参考对应样张的笔墨，主体按当前设定。'};
}

// A fresh click owns feedback immediately, before the API returns a persisted job.
export function setupGenerationJob(jobs:Job[], generation:SetupGeneration|null, currentKey:string):Job|undefined {
  if (generation) {
    if (generation.key !== currentKey) return undefined;
    return jobs.find(job => job.id === generation.job.id) || generation.job;
  }
  const latest=jobs[0];
  return latest?.action === 'asset-image' && latest.state !== 'completed' ? latest : undefined;
}

export type SetupStep = {
  group: 'characters' | 'scenes' | 'props';
  asset: SettingAsset | null;
  key: string;
};
const groups = ['characters', 'scenes', 'props'] as const;

export function setupSteps(settings: CreativeSettings, skipEmpty = false): SetupStep[] {
  return groups.flatMap<SetupStep>(group => settings[group].length
    ? settings[group].map(asset => ({ group, asset, key: `${group}:${asset.id}` }))
    : skipEmpty && group !== 'scenes' ? [] : [{ group, asset: null, key: `${group}:empty` }]);
}

export function setupSignature(step: SetupStep, style: string): string {
  const asset = step.asset;
  return JSON.stringify([asset ? [asset.id, asset.name, asset.desc, asset.image ?? null, asset.views?.side ?? null, asset.views?.back ?? null] : null, style]);
}

export function confirmedSetupReviews(settings: CreativeSettings | null | undefined): Record<string, string> {
  if (!settings) return {};
  return Object.fromEntries(setupSteps(settings).map(step => [step.key, setupSignature(step, settings.style)]));
}

export function isSetupReviewed(
  step: SetupStep,
  style: string,
  localReviews: Record<string, string>,
  confirmedReviews: Record<string, string>,
): boolean {
  const signature = setupSignature(step, style);
  return localReviews[step.key] === signature || confirmedReviews[step.key] === signature;
}

export function nextSetupStep(
  steps: SetupStep[],
  currentKey: string,
  reviewed: (step: SetupStep) => boolean,
): { step: SetupStep; returning: boolean } | null {
  const index = steps.findIndex(step => step.key === currentKey);
  const following = steps.slice(index + 1).find(step => !reviewed(step));
  if (following) return { step: following, returning: false };
  if (index < 0) return null;
  const previous = steps.slice(0, index).find(step => !reviewed(step));
  return previous ? { step: previous, returning: true } : null;
}
