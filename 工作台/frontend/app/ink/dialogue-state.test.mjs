import test from 'node:test';
import assert from 'node:assert/strict';
import {NARRATOR, retainDialogues, speakerName, voiceSpeakers} from './dialogue-state.ts';

test('empty-cast projects expose a narrator name and voice without inventing a cast member', () => {
  const project={characters:[]};
  assert.equal(speakerName(project.characters,NARRATOR),'旁白');
  assert.deepEqual(voiceSpeakers(project),[{id:NARRATOR,name:'旁白（画外音）'}]);
  assert.deepEqual(project.characters,[]);
});

test('dialogue editing preserves narration when all visible characters are deselected', () => {
  const lines=[{character_id:'c1',text:'看这里'},{character_id:NARRATOR,text:'观察木构件'}];
  assert.deepEqual(retainDialogues(lines,[]),[lines[1]]);
  assert.deepEqual(retainDialogues(lines,['c1']),lines);
  assert.equal(speakerName([{id:'c1',name:'学生'}],'c1'),'学生');
});
