import test from 'node:test';
import assert from 'node:assert/strict';
import { nextShotStep, imageReady, imageGenerationPlan, adjustmentPlan, unlockedStage, resumeStage, missingCharacters, referenceShot, soundReady, previewVideo, videoEditSource, wizardStepsFor, wizardStorageKey, restoredWizardStage } from './wizard-state.ts';
function project() {
  return { characters: [{ id: 'c1' }, { id: 'c2' }], baseline: null, shots: [
    { id: 's1', character_ids: ['c1'], image_url: null },
    { id: 's2', character_ids: ['c2'], image_url: null },
  ] };
}
function complete() {
  const p = project(); p.creative_settings = {characters:p.characters, scenes:[], props:[], style:'水墨'}; p.storyboard_confirmed=true; p.baseline = { characters: [{ character_id: 'c1' }, { character_id: 'c2' }] };
  for (const s of p.shots) Object.assign(s, { image_url: '/image', clip_url: '/clip', rendered_url: '/sound' });
  return p;
}
test('heritage reviews the storyboard before materials, and keeps ordinary ink order', () => {
  const p={...complete(),id:'study',project_type:'heritage',story_confirmed:true};
  assert.deepEqual(wizardStepsFor(p),['剧本','分镜','素材与画风','画面','视频','成片']);
  p.storyboard_confirmed=false; assert.equal(unlockedStage(p),1);
  p.storyboard_confirmed=true; p.creative_settings=null; assert.equal(unlockedStage(p),2);
  p.creative_settings={characters:[],scenes:[],props:[],style:'水墨'};
  assert.equal(unlockedStage(p),5);
  p.creative_draft=p.creative_settings; assert.equal(unlockedStage(p),2);
  p.heritage_story_stale=true; assert.equal(unlockedStage(p),1);
  assert.deepEqual(wizardStepsFor(complete()).slice(0,3),['剧本','创作设定','分镜']);
});
test('heritage migrates saved setup/storyboard positions by meaning instead of swapping pages', () => {
  const p={...complete(),id:'study',project_type:'heritage'};
  assert.equal(wizardStorageKey(p),'ink.wizard.v3.study');
  assert.equal(restoredWizardStage(p,1,true),2);
  assert.equal(restoredWizardStage(p,2,true),1);
  assert.equal(restoredWizardStage(p,3,true),3);
  assert.equal(restoredWizardStage(p,1),1);
  p.storyboard_confirmed=false;
  assert.equal(restoredWizardStage(p,1,true),1);
  assert.equal(restoredWizardStage(complete(),1,true),1);
});
test('new story starts at step one, with no inaccessible later steps', () => {
  const p = project(); p.shots = [];
  assert.equal(unlockedStage(p), 0); assert.equal(resumeStage(p, 4), 0);
});
test('second character must be confirmed before generating all frames', () => {
  const p = project(); p.baseline = { characters: [{ character_id: 'c1' }] };
  assert.equal(unlockedStage(p), 1); assert.deepEqual(missingCharacters(p), [{ id: 'c2' }]);
  assert.equal(referenceShot(p).id, 's2');
});
test('saved progress returns to the earliest invalidated dependency', () => {
  const p = complete(); assert.equal(resumeStage(p, 5), 5);
  p.shots[1].image_stale = true; assert.equal(resumeStage(p, 5), 3);
  p.shots[1].image_stale = false; p.shots[1].clip_stale = true; assert.equal(resumeStage(p, 5), 4);
  p.shots[1].clip_stale = false; p.shots[1].rendered_stale = true; assert.equal(resumeStage(p, 5), 4);
});
test('existing results do not force a user out of a previous step they are reviewing', () => {
  assert.equal(resumeStage(complete(), 1), 1); assert.equal(resumeStage(complete(), NaN), 5);
});
test('a stale image invalidates even an existing narrated clip', () => {
  const p = complete(); assert.equal(soundReady(p.shots[0]), true);
  p.shots[0].image_stale = true; assert.equal(soundReady(p.shots[0]), false);
});
test('landscape-only stories need style confirmation but no invented characters', () => {
  const p = project(); p.shots.forEach(s => { s.character_ids = []; });
  assert.deepEqual(missingCharacters(p), []); assert.equal(unlockedStage(p), 1);
  p.baseline = { characters: [] }; assert.equal(unlockedStage(p), 1);
  p.creative_settings={characters:[],scenes:[],props:[],style:'水墨'}; assert.equal(unlockedStage(p),2);
});

test('adjustments regenerate the earliest changed output and respect prerequisites', () => {
  const p = complete();
  const s = {...p.shots[0], content:'old', scene:'temple', camera:'wide', motion:'walk', dialogues:[]};
  assert.equal(adjustmentPlan(p,s,{...s,content:'new'},3).action,'image');
  assert.equal(adjustmentPlan(p,s,{...s,content:'new',motion:'run'},4).action,'image');
  assert.equal(adjustmentPlan(p,s,{...s,motion:'run'},4).action,'image');
  assert.equal(adjustmentPlan(p,s,{...s,motion:'run'},3).action,'image');
  assert.equal(adjustmentPlan(p,s,{...s,dialogues:[{character_id:'c1',text:'hi'}]},4).action,'sound');
  assert.equal(adjustmentPlan(p,s,{...s,content:'new'},0).action,'');
  assert.equal(adjustmentPlan(p,s,s,3).changed,false);
  assert.equal(adjustmentPlan(p,s,s,3).action,'image');
  assert.equal(adjustmentPlan(p,s,s,0).action,'');
  assert.equal(adjustmentPlan(p,s,{...s,character_ids:['unknown']},3).action,'');
});

test('next shot proceeds in order and explicitly returns to pending work only at the end', () => {
 const p=complete();
 p.shots.push({...p.shots[1],id:'s3'});
 p.shots[0].image_stale=true;
 assert.equal(nextShotStep(p.shots,'s2',imageReady).shot.id,'s3');
 assert.equal(nextShotStep(p.shots,'s2',imageReady).returning,false);
 assert.equal(nextShotStep(p.shots,'s3',imageReady).shot.id,'s1');
 assert.equal(nextShotStep(p.shots,'s3',imageReady).returning,true);
 p.shots[0].image_stale=false;
 assert.equal(nextShotStep(p.shots,'s3',imageReady),null);
 assert.equal(nextShotStep(p.shots,'s1',imageReady).shot.id,'s2');
});

test('six steps require settings and storyboard confirmation before pictures', () => {
 const p=project(); p.shots=[];
 assert.equal(unlockedStage(p),0);
 p.story_confirmed=true; assert.equal(unlockedStage(p),1);
 p.creative_settings={characters:[],scenes:[],props:[],style:'水墨'};
 assert.equal(unlockedStage(p),2);
 p.shots=[{id:'s1',image_url:null}]; assert.equal(unlockedStage(p),2);
 p.storyboard_confirmed=true; assert.equal(unlockedStage(p),3);
});

test('deleted middle shots are skipped and remaining shots use their current list positions', () => {
  const p = complete();
  p.shots.push({ ...p.shots[1], id: 's5' });
  p.shots = p.shots.filter(s => s.id !== 's2');
  const next = nextShotStep(p.shots, 's1', imageReady);
  assert.equal(next.shot.id, 's5');
  assert.equal(next.number, 2);
  assert.equal(next.returning, false);
  assert.equal(nextShotStep(p.shots, 's5', soundReady), null);
});

test('a changed storyboard returns to confirmation, then permits a one-shot short film', () => {
  const p = complete();
  p.shots = [p.shots[0]];
  p.storyboard_confirmed = false;
  p.final_stale = true;
  assert.equal(resumeStage(p, 5), 2);
  assert.equal(imageReady(p.shots[0]), true);
  assert.equal(soundReady(p.shots[0]), true);
  p.storyboard_confirmed = true;
  assert.equal(unlockedStage(p), 5);
  assert.equal(nextShotStep(p.shots, 's1', soundReady), null);
});

 test('retained stale videos remain previewable without being treated as ready', () => {
  const s = complete().shots[0];
  s.clip_stale = true; s.rendered_stale = true;
  assert.equal(previewVideo(s), '/clip');
  assert.equal(soundReady(s), false);
  s.clip_stale = false; s.rendered_stale = false;
  assert.equal(previewVideo(s), '/sound');
  s.clip_url = null;
  assert.equal(previewVideo(s), '/sound');
  s.rendered_url = null;
  assert.equal(previewVideo(s), null);
});


test('video editing reopens on the currently previewed version after video replacement', () => {
  const old = {video:'old.mp4',video_url:'/old',current:false};
  const fresh = {video:'new.mp4',video_url:'/new',current:true};
  assert.equal(videoEditSource([old, fresh], '/new'), 'new.mp4');
  // Returning to the dialog follows a newly adopted or generated version, not the last selection.
  const adopted = {video:'adopted.mp4',video_url:'/adopted',current:true};
  assert.equal(videoEditSource([old, {...fresh,current:false}, adopted], '/adopted'), 'adopted.mp4');
  assert.equal(videoEditSource([old, fresh], '/old'), 'old.mp4');
  assert.equal(videoEditSource([old, fresh], null), 'new.mp4');
  assert.equal(videoEditSource([old], '/missing'), '');
  assert.equal(videoEditSource([], null), '');
});

test('a retained stale image defaults to regeneration preview rather than confirming the old image', () => {
  const plan=imageGenerationPlan({image_url:'/old.png',image_stale:true},4);
  assert.equal(plan.mode,'preview');
  assert.equal(plan.label,'按新分镜重新生成');
  assert.ok(!plan.label.includes('保留'));
});

test('first image generation and optional regeneration have distinct plans', () => {
  assert.deepEqual(imageGenerationPlan({image_url:null,image_stale:false},6),{label:'生成第 6 镜图片',mode:'direct'});
  assert.deepEqual(imageGenerationPlan({image_url:'/current.png',image_stale:false}),{label:'重新生成图片',mode:'preview'});
});
