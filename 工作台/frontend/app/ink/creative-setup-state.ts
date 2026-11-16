import type { CreativeSettings, SettingAsset } from './ink-shared';

export type SetupStep = {
  group: 'characters' | 'scenes' | 'props';
  asset: SettingAsset | null;
  key: string;
};
const groups = ['characters', 'scenes', 'props'] as const;

export function setupSteps(settings: CreativeSettings): SetupStep[] {
  return groups.flatMap<SetupStep>(group => settings[group].length
    ? settings[group].map(asset => ({ group, asset, key: `${group}:${asset.id}` }))
    : [{ group, asset: null, key: `${group}:empty` }]);
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
