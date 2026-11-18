import test from 'node:test';
import assert from 'node:assert/strict';
import {missingGuideReference} from './guide-state.ts';

test('a visible study guide requires a shared image while ordinary roles stay optional',()=>{
 const p={project_type:'heritage',heritage_guide:{enabled:true,character_id:'c1'},shots:[{character_ids:['c1']}]};
 const settings={characters:[{id:'c1',image:null}]};
 assert.equal(missingGuideReference(p,settings),true);
 assert.equal(missingGuideReference(p,{characters:[{id:'c1',image:'guide.png'}]}),false);
 assert.equal(missingGuideReference({...p,project_type:'ink'},settings),false);
 assert.equal(missingGuideReference({...p,shots:[{character_ids:[]}]},settings),false);
});
