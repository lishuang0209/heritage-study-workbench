import test from 'node:test';
import assert from 'node:assert/strict';
import {shotDescription} from './shot-presentation.ts';

test('visual, framing, style and restrictions are merged into one paragraph without modifying source',()=>{
  const shot={scene:'宁波保国寺大殿',camera:'全景，侧前方平视，殿前空间形成前景',
    content:'从侧前方展示建筑，使用现状作为背景，不补造历史事件现场。\n画面补充：水墨工笔淡彩全景,侧前方平视取景:已确认的宁波保国寺大殿侧向展开,殿身、檐口与殿前空间同框,建筑居于画面中后部,前景留出开阔的殿前空间,远侧以留白与疏淡树影收束;细线薄染、低饱和清雅设色,画面中无人物出镜。'};
  const before=JSON.stringify(shot), result=shotDescription(shot);
  assert.ok(result.startsWith('宁波保国寺大殿侧向展开，殿身、檐口与殿前空间同框。'));
  assert.ok(!result.includes('\n'));
  const all=result;
  for(const important of ['建筑居于画面中后部','前景留出开阔的殿前空间','疏淡树影','细线薄染','低饱和清雅设色','无人物出镜','不补造历史事件现场'])assert.ok(all.includes(important),important);
  assert.equal(JSON.stringify(shot),before);
});

test('negative and compositional requirements survive grouping without clipping',()=>{
  const result=shotDescription({scene:'斗拱',camera:'特写，略仰视，16:9宽屏',content:'斗拱与梁端相接，木构边界清楚，右侧保留柱头，不拆解构件，不猜测内部榫卯，不另造历史场景，不补造历史场景。'});
  const all=result;
  assert.ok(all.includes('16:9宽屏'));
  assert.ok(all.includes('右侧保留柱头'));
  assert.ok(all.includes('不拆解构件'));
  assert.ok(all.includes('不猜测内部榫卯'));
  assert.equal((all.match(/历史场景/g)||[]).length,1);
});

test('short descriptions need no invented detail, and extra visual facts remain outside',()=>{
  const simple=shotDescription({scene:'古建',camera:'',content:'展示柱子与斗拱的连接。'});
  assert.equal(simple,'展示柱子与斗拱的连接。');
  const longer=shotDescription({scene:'古建',camera:'',content:'柱头清楚，斗拱层层向外伸出，梁端与木构相接，木构边界完整。'});
  assert.ok(longer.includes('梁端与木构相接'));
  assert.ok(!longer.includes('\n'));
  assert.equal(shotDescription({scene:'保国寺大殿',camera:'全景',content:''}),'保国寺大殿。全景。');
});
