import test from 'node:test';
import assert from 'node:assert/strict';
import { newShotFields, reconcileShotFields, shotFields, shotFieldsChanged, storyboardImageStatus } from './storyboard-state.ts';

const shot = () => ({ id: 's1', content: '新保存的画面', scene: '古寺门前', camera: '中景', motion: '递伞', character_ids: ['c1'], scene_id: 'scene1', prop_ids: ['prop1'], dialogues: [{ character_id: 'c1', text: '请用伞' }], image_draft: { shot: { content: '旧候选的画面' } } });
const project = () => ({ characters: [{ id: 'c1' }, { id: 'c2' }], shots: [shot()], creative_settings: { scenes: [{ id: 'scene1', name: '古寺门前' }], props: [{ id: 'prop1', name: '油纸伞' }] } });

test('editing uses saved fields, excludes generation metadata and never mutates source', () => {
  const original = shot();
  const draft = shotFields(original);
  assert.equal(draft.content, '新保存的画面');
  assert.equal('image_draft' in draft, false);
  assert.equal('id' in draft, false);
  draft.character_ids.push('c2'); draft.dialogues[0].text = '新的台词';
  assert.deepEqual(original.character_ids, ['c1']);
  assert.equal(original.dialogues[0].text, '请用伞');
});

test('motion, scene, composition and references alone each count as changes', () => {
  const original = shotFields(shot());
  for (const patch of [{ motion: '转身' }, { scene: '桥头' }, { camera: '远景' }, { scene_id: 'scene2' }, { prop_ids: [] }, { character_ids: [] }, { dialogues: [] }]) {
    assert.equal(shotFieldsChanged(original, { ...original, ...patch }), true);
  }
  assert.equal(shotFieldsChanged(original, structuredClone(original)), false);
  assert.equal(shotFieldsChanged({ ...original, scene_id: undefined, prop_ids: undefined }, { ...original, scene_id: null, prop_ids: [] }), false);
});

test('removed settings are cleared in draft and count as an unsaved correction', () => {
  const p = project(); p.characters = [{ id: 'c2' }]; p.creative_settings = { scenes: [{ id: 'scene2' }], props: [] };
  const original = shotFields(shot());
  const draft = reconcileShotFields(p, original);
  assert.deepEqual(draft.character_ids, []); assert.deepEqual(draft.dialogues, []);
  assert.deepEqual(draft.prop_ids, []); assert.equal(draft.scene_id, null);
  assert.equal(shotFieldsChanged(original, draft), true);
  assert.equal(original.scene_id, 'scene1'); assert.deepEqual(original.prop_ids, ['prop1']);
});

test('a new shot reuses a valid scene, but does not invent actors or overwrite existing shots', () => {
  const p = project(); const before = JSON.stringify(p);
  const blank = newShotFields(p);
  assert.equal(blank.scene_id, 'scene1'); assert.equal(blank.content, '');
  assert.deepEqual(blank.character_ids, []); assert.deepEqual(blank.prop_ids, []);
  assert.deepEqual(blank.dialogues, []); assert.equal(JSON.stringify(p), before);
  p.shots = []; assert.equal(newShotFields(p).scene_id, 'scene1');
  p.creative_settings = null; assert.equal(newShotFields(p).scene_id, null);
});

test('stale images are shown as needing an update even when an older candidate exists', () => {
  assert.equal(storyboardImageStatus({ image_url: '/old', image_stale: true, image_proposal: {} }), '图片待更新');
  assert.equal(storyboardImageStatus({ image_url: '/current', image_stale: false }), '图片已就绪');
  assert.equal(storyboardImageStatus({ image_url: null, image_proposal: {} }), '候选待确认');
  assert.equal(storyboardImageStatus({ image_url: null }), '待出图');
});
