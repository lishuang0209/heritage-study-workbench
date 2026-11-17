import test from 'node:test';
import assert from 'node:assert/strict';
import {blankStation,completeStationDraft,observationGuidance,selectPhotoCredits,reviewStation,reviewScript,scriptIsConfirmed,derivedDetailStale,projectTiming,timingError,observationSplit,stationPayload,point} from './state.ts';
test('photo save strips display URLs without removing normalized marks or credits',()=>{
 const station=blankStation();station.panorama={image:'photo.jpg',source:'teacher',author:'author',license:'licensed',mark:{kind:'arrow',x:.1,y:.2,x2:.3,y2:.4},mode:'cover',focus_x:.5,focus_y:.5,url:'/asset',preview_url:'/preview'};
 const payload=stationPayload(station);assert.equal(payload.panorama.url,undefined);assert.equal(payload.panorama.preview_url,undefined);assert.deepEqual(payload.panorama.mark,station.panorama.mark);assert.equal(station.panorama.url,'/asset');
});
test('pointer coordinates are scale independent and stay inside the original photograph',()=>{
 assert.deepEqual(point(150,200,{left:50,top:100,width:200,height:400}),{x:.5,y:.25});
 assert.deepEqual(point(-100,900,{left:50,top:100,width:200,height:400}),{x:0,y:1});
});

test('a new station receives editable tasks without invented location or component facts',()=>{
 const station={...blankStation(),building:'测试古建',component:'柱础',grade:'四年级',checked_description:'老师提供的资料'};
 const result=completeStationDraft(station);
 assert.equal(result.name,'找柱础');assert.ok(result.instruction.includes('柱础'));
 assert.ok(result.objective);assert.ok(result.question);
 assert.equal(result.standing_position,'');assert.equal(result.checked_description,station.checked_description);
 assert.equal(station.name,'');assert.equal(completeStationDraft(blankStation()).name,'');
});
test('completing tasks preserves teacher edits and photographs and respects field limits',()=>{
 const station={...blankStation(),component:'构件'.repeat(40),name:'老师命名',question:'老师的问题',instruction:'老师的指令',objective:'老师的目标'};
 station.panorama={image:'photo.jpg',source:'teacher',author:'author',license:'licensed',mark:null,mode:'contain',focus_x:.5,focus_y:.5};
 const result=completeStationDraft(station);assert.deepEqual(result,station);
 const generated=completeStationDraft({...station,name:'',instruction:'',question:'',objective:''});
 assert.ok(generated.name.length<=80);assert.ok(generated.instruction.length<=220);assert.ok(generated.question.length<=160);assert.ok(generated.objective.length<=300);
 assert.deepEqual(generated.panorama,station.panorama);
});

test('legacy position and task remain editable as one guidance without changing the source',()=>{
 const station={...blankStation(),standing_position:'大殿东侧围栏外',instruction:'沿第二根柱子向上找斗拱。'};
 const guidance=observationGuidance(station);
 assert.equal(guidance,'大殿东侧围栏外。沿第二根柱子向上找斗拱。');
 const payload=stationPayload(station);assert.equal(payload.instruction,guidance);assert.equal(payload.standing_position,'');
 assert.equal(station.standing_position,'大殿东侧围栏外');assert.equal(observationGuidance(payload),guidance);
 const edited={...station,instruction:'站在西侧，看第一根柱子。',standing_position:''};
 assert.equal(stationPayload(edited).instruction,edited.instruction);
});
test('legacy guidance handles empty fields and avoids including identical position text twice',()=>{
 const station={...blankStation(),standing_position:'围栏外。',instruction:'围栏外。向上看斗拱。'};
 assert.equal(observationGuidance(station),station.instruction);
 assert.equal(observationGuidance({...station,instruction:''}),'围栏外。');
 assert.equal(observationGuidance({...station,standing_position:''}),station.instruction);
});

test('selecting a source fills credits while keeping the photo and mark unchanged',()=>{
 const photo={image:'local.jpg',source:'',author:'',license:'',mark:{kind:'rectangle',x:.2,y:.2,x2:.6,y2:.6},mode:'contain',focus_x:.5,focus_y:.5};
 for(const kind of ['self','authorized']){
  const selected=selectPhotoCredits(photo,kind);
  assert.equal(selected.credit_kind,kind);assert.ok(selected.source&&selected.author&&selected.license);
  assert.deepEqual(selected.mark,photo.mark);assert.equal(selected.image,photo.image);
  assert.equal(photo.source,'');assert.ok(!selected.license.includes('CC BY'));
 }
});

test('one review saves changes before confirming the newly returned revision',async()=>{
 const current={heritage_version:3,heritage_ready:true,heritage_station:{...blankStation(),instruction:'旧内容'}};
 const saved={...current,heritage_version:4,heritage_ready:false,heritage_station:{...current.heritage_station,instruction:'新内容'}};
 const calls=[];
 const reviewed=await reviewStation(current,true,async()=>{calls.push('save');return saved;},async project=>{
  calls.push('confirm');assert.equal(project.heritage_version,4);assert.equal(project.heritage_station.instruction,'新内容');
  return {...project,heritage_ready:true,heritage_confirmed_version:4};
 });
 assert.deepEqual(calls,['save','confirm']);assert.equal(reviewed.heritage_confirmed_version,4);
 assert.equal(current.heritage_version,3);
});
test('confirmed unchanged content continues without another review request',async()=>{
 const current={heritage_version:4,heritage_ready:true};
 const unexpected=async()=>{throw new Error('unnecessary request');};
 assert.equal(await reviewStation(current,false,unexpected,unexpected),current);
 // Editing a field back to its saved value can leave a local dirty flag, while the server keeps the same confirmed revision.
 assert.equal(await reviewStation(current,true,async()=>current,unexpected),current);
});
test('save or confirmation failure prevents advancing and preserves the current draft',async()=>{
 const current={heritage_version:4,heritage_ready:false,heritage_station:{...blankStation(),instruction:'未保存内容'}};
 let confirmed=false,advanced=false;
 await assert.rejects(reviewStation(current,true,async()=>{throw new Error('save failed');},async project=>{confirmed=true;return project;}).then(()=>{advanced=true;}),/save failed/);
 assert.equal(confirmed,false);assert.equal(advanced,false);
 await assert.rejects(reviewStation(current,false,async()=>current,async()=>{throw new Error('missing mark');}).then(()=>{advanced=true;}),/missing mark/);
 assert.equal(advanced,false);assert.equal(current.heritage_station.instruction,'未保存内容');
});

const reviewedScriptProject=()=>({heritage_version:4,heritage_timing_version:2,heritage_script:{intro:'历史台词',location:'观察台词',task:'任务台词',version:3,station_version:4,timing_version:2,confirmed_version:3}});
test('an already confirmed script continues without another request or review checkbox',async()=>{
 const current=reviewedScriptProject();let advanced=false;
 assert.equal(scriptIsConfirmed(current),true);
 const result=await reviewScript(current,async()=>{throw new Error('unnecessary request');});
 advanced=true;assert.equal(result,current);assert.equal(advanced,true);
 assert.equal(scriptIsConfirmed({heritage_script:{...current.heritage_script,station_version:0,timing_version:undefined}}),true);
});
test('script confirmation waits for a successful response before advancing',async()=>{
 const current=reviewedScriptProject();current.heritage_script.confirmed_version=null;
 let respond,advanced=false;
 const request=reviewScript(current,project=>{
  assert.equal(project,current);assert.equal(project.heritage_script.version,3);
  assert.equal(project.heritage_timing_version,2);
  return new Promise(resolve=>{respond=resolve;});
 }).then(project=>{advanced=true;return project;});
 await Promise.resolve();assert.equal(advanced,false);
 respond(reviewedScriptProject());assert.equal(scriptIsConfirmed(await request),true);
 assert.equal(advanced,true);assert.equal(current.heritage_script.confirmed_version,null);
});
test('failed confirmation stays on the script and can be retried without losing text',async()=>{
 const current=reviewedScriptProject();current.heritage_script.confirmed_version=null;
 let advanced=false;
 await assert.rejects(reviewScript(current,async()=>{throw new Error('资料已更新');}).then(()=>{advanced=true;}),/资料已更新/);
 assert.equal(advanced,false);assert.equal(current.heritage_script.intro,'历史台词');
 assert.equal(scriptIsConfirmed(await reviewScript(current,async()=>reviewedScriptProject())),true);
});
test('a stale or unconfirmed response never advances to story production',async()=>{
 const current=reviewedScriptProject();
 for(const stale of [
  {...current,heritage_version:5},
  {...current,heritage_timing_version:3},
  {...current,heritage_script:{...current.heritage_script,confirmed_version:null}},
 ]){
  assert.equal(scriptIsConfirmed(stale),false);let advanced=false;
  await assert.rejects(reviewScript(stale,async()=>stale).then(()=>{advanced=true;}),/尚未确认成功/);
  assert.equal(advanced,false);
 }
 await assert.rejects(reviewScript({},async()=>{throw new Error('unexpected request');}),/请先生成或保存/);
});

test('derived details track source identity and target geometry while ignoring unrelated text changes',()=>{
 const mark={kind:'rectangle',x:.2,y:.2,x2:.6,y2:.5};
 const photo={image:'source.jpg',source:'teacher',author:'teacher',license:'self',mark,mode:'contain',focus_x:.5,focus_y:.5};
 const station={...blankStation(),panorama:photo,detail:{...photo,image:'detail.jpg',derived_from:photo.image,derived_mark:{...mark}}};
 assert.equal(derivedDetailStale(station),false);
 assert.equal(derivedDetailStale({...station,question:'新问题'}),false);
 assert.equal(derivedDetailStale({...station,panorama:{...photo,image:'replacement.jpg'}}),true);
 assert.equal(derivedDetailStale({...station,panorama:{...photo,mark:{...mark,x:.3}}}),true);
 assert.equal(derivedDetailStale({...station,panorama:null}),true);
 assert.equal(derivedDetailStale({...station,detail:{...photo,image:'manual.jpg'}}),false);
 assert.equal(derivedDetailStale({...station,detail:null}),false);
});

test('legacy timing defaults and custom values are independent copies',()=>{
 const old=projectTiming({});assert.deepEqual(old,{intro:12,location:11,task:7});old.intro=50;
 assert.equal(projectTiming({}).intro,12);
 const project={heritage_timing:{intro:20,location:15,task:10}};
 const copied=projectTiming(project);assert.deepEqual(copied,{intro:20,location:15,task:10});copied.intro=30;assert.equal(project.heritage_timing.intro,20);
});
test('custom timing validates complete integer seconds before requests',()=>{
 assert.equal(timingError({intro:20,location:15,task:10}),'');
 for(const value of [0,2,12.5,181,NaN])assert.ok(timingError({intro:value,location:11,task:7}));
 assert.ok(timingError({intro:180,location:180,task:7}));
});
test('observation split matches displayed chapter durations and preserves the total',()=>{
 assert.deepEqual(observationSplit(11,true),{panorama:6,detail:5});
 assert.deepEqual(observationSplit(15,true),{panorama:9,detail:6});
 assert.deepEqual(observationSplit(20,false),{panorama:20,detail:0});
});
