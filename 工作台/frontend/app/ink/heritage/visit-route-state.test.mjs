import test from 'node:test';
import assert from 'node:assert/strict';
import {visitRoute,visitTitle} from './visit-route-state.ts';

test('a route shows actual saved stops and collapses consecutive labels',()=>{
 const shots=['外观全貌','走近建筑','内部空间','木构关系','木构关系','构件细节'].map(label=>({study_visit:{label}}));
 assert.equal(visitRoute(shots),'外观全貌 → 走近建筑 → 内部空间 → 木构关系 → 构件细节');
 assert.equal(visitRoute([{}]),'');
});
test('titles identify the visit step and keep historical facts without inventing new stops',()=>{
 assert.equal(visitTitle({scene:'大殿',study_topic:'前槽天花',study_visit:{label:'内部空间'}}),'内部空间 · 前槽天花');
 assert.equal(visitTitle({scene:'大殿'}),'大殿');
});
