import test from 'node:test';
import assert from 'node:assert/strict';
import {studyNarration,voiceChoice,unifiedNarration} from './narration-state.ts';

test('study narrator defaults to the same friendly voice and slower rate',()=>{
 const selected=studyNarration({});
 assert.equal(selected.voice,'zh-CN-XiaoxiaoNeural');
 assert.equal(selected.speed,.95);
 assert.equal(studyNarration({voices:{narrator:'zh-CN-YunxiNeural'}}).voice,'zh-CN-YunxiNeural');
});
test('export voice saves preserve cast choices and include the shared narrator',()=>{
 assert.deepEqual(voiceChoice({characters:[{id:'c1'}],voices:{c1:'zh-CN-XiaoxiaoNeural'}},'zh-CN-YunxiNeural'),{c1:'zh-CN-XiaoxiaoNeural',narrator:'zh-CN-YunxiNeural'});
});
test('only study narration replaces native voices; ordinary story and atmosphere stay unchanged',()=>{
 const shot={dialogues:[{character_id:'narrator',text:'历史'}]};
 assert.equal(unifiedNarration({project_type:'heritage'},shot),true);
 assert.equal(unifiedNarration({project_type:'ink'},shot),false);
 assert.equal(unifiedNarration({project_type:'heritage'},{dialogues:[]}),false);
});
