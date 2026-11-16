import test from 'node:test';
import assert from 'node:assert/strict';
import { setupSteps, setupSignature, confirmedSetupReviews, isSetupReviewed, nextSetupStep } from './creative-setup-state.ts';

function settings() {
  return {
    characters: [
      { id: 'c1', name: 'Scholar', desc: 'Blue robe', image: 'scholar.png' },
      { id: 'c2', name: 'Girl', desc: 'Long skirt', image: 'girl.png' },
    ],
    scenes: [{ id: 'scene1', name: 'Temple', desc: 'Wooden gate', image: 'gate.png' }],
    props: [
      { id: 'prop1', name: 'Umbrella', desc: 'Paper and bamboo', image: 'umbrella.png' },
      { id: 'prop2', name: 'Scroll', desc: 'Plain paper roll', image: 'scroll.png' },
    ],
    style: 'ink',
  };
}
const checker = (data, local = {}, confirmed = {}) => step => isSetupReviewed(step, data.style, local, confirmed);

test('reopening confirmed settings restores reviews without local progress', () => {
  const saved = settings();
  const confirmed = confirmedSetupReviews(saved);
  const reopened = JSON.parse(JSON.stringify(saved));
  assert.ok(setupSteps(reopened).every(checker(reopened, {}, confirmed)));
  assert.equal(nextSetupStep(setupSteps(reopened), 'props:prop2', checker(reopened, {}, confirmed)), null);
  assert.deepEqual(confirmedSetupReviews(null), {});
  assert.deepEqual(confirmedSetupReviews(undefined), {});
});

test('local confirmations survive a storage JSON roundtrip and use matching signatures', () => {
  const draft = settings();
  const steps = setupSteps(draft);
  const local = Object.fromEntries(steps.slice(0, 3).map(step => [step.key, setupSignature(step, draft.style)]));
  const restored = JSON.parse(JSON.stringify({ reviewed: local })).reviewed;
  assert.deepEqual(steps.map(checker(draft, restored)), [true, true, true, false, false]);
  const confirmed = confirmedSetupReviews(draft);
  assert.equal(isSetupReviewed(steps[0], draft.style, { [steps[0].key]: 'stale local value' }, confirmed), true);
});

test('confirming the last prop finishes instead of returning to already confirmed characters', () => {
  const saved = settings();
  const draft = structuredClone(saved);
  draft.props[1].desc = 'A newly adjusted scroll';
  const steps = setupSteps(draft);
  const reviewed = checker(draft, {}, confirmedSetupReviews(saved));
  assert.equal(reviewed(steps.at(-1)), false);
  assert.equal(nextSetupStep(steps, 'props:prop2', reviewed), null);
});

test('missing reviews return to the named earlier asset only after later pending assets', () => {
  const data = settings();
  const steps = setupSteps(data);
  const local = confirmedSetupReviews(data);
  delete local['characters:c1'];
  delete local['scenes:scene1'];
  const reviewed = checker(data, local);
  assert.deepEqual(nextSetupStep(steps, 'characters:c2', reviewed), { step: steps[2], returning: false });
  assert.deepEqual(nextSetupStep(steps, 'props:prop2', reviewed), { step: steps[0], returning: true });
  local['characters:c1'] = setupSignature(steps[0], data.style);
  assert.deepEqual(nextSetupStep(steps, 'characters:c1', checker(data, local)), { step: steps[2], returning: false });
});

test('changing an image or description invalidates only that asset', () => {
  const saved = settings();
  const confirmed = confirmedSetupReviews(saved);
  for (const [field, value] of [['image', 'new-scroll.png'], ['desc', 'Rolled silk']]) {
    const draft = structuredClone(saved);
    draft.props[1][field] = value;
    assert.deepEqual(setupSteps(draft).map(checker(draft, {}, confirmed)), [true, true, true, true, false]);
    const last = setupSteps(draft).at(-1);
    const local = { [last.key]: setupSignature(last, draft.style) };
    assert.equal(isSetupReviewed(last, draft.style, local, confirmed), true);
  }
});

test('changing the shared style does not silently confirm old reviews', () => {
  const saved = settings();
  const confirmed = confirmedSetupReviews(saved);
  const draft = structuredClone(saved);
  draft.style = 'bold ink';
  assert.ok(setupSteps(draft).every(step => !isSetupReviewed(step, draft.style, confirmed, confirmed)));
  assert.equal(nextSetupStep(setupSteps(draft), 'props:prop2', checker(draft, confirmed, confirmed)).returning, true);
});

test('empty groups retain independent placeholders and reviews are isolated by group key', () => {
  const empty = { characters: [], scenes: [], props: [], style: 'ink' };
  const steps = setupSteps(empty);
  assert.deepEqual(steps.map(step => step.key), ['characters:empty', 'scenes:empty', 'props:empty']);
  assert.ok(steps.every(step => step.asset === null));
  const local = { 'characters:empty': setupSignature(steps[0], empty.style) };
  assert.deepEqual(steps.map(checker(empty, local)), [true, false, false]);
  assert.ok(steps.every(checker(empty, {}, confirmedSetupReviews(empty))));
  const shared = { id: 'same', name: 'Same', desc: 'Same content' };
  const data = { characters: [shared], scenes: [], props: [{ ...shared }], style: 'ink' };
  const assets = setupSteps(data);
  const characterOnly = { 'characters:same': setupSignature(assets[0], data.style) };
  assert.equal(isSetupReviewed(assets[2], data.style, characterOnly, {}), false);
});

test('signature is stable across object key order and omitted versus null images', () => {
  const a = { group: 'props', key: 'props:p1', asset: { id: 'p1', name: 'Scroll', desc: 'Paper' } };
  const b = { group: 'props', key: 'props:p1', asset: { image: null, desc: 'Paper', name: 'Scroll', id: 'p1' } };
  assert.equal(setupSignature(a, 'ink'), setupSignature(b, 'ink'));
  const steps = [a];
  assert.deepEqual(nextSetupStep(steps, 'missing', () => false), { step: a, returning: false });
  assert.equal(nextSetupStep([], 'missing', () => false), null);
});
