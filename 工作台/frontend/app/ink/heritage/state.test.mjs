import test from 'node:test';
import assert from 'node:assert/strict';
import {blankStation,stationPayload,point} from './state.ts';
test('photo save strips display URLs without removing normalized marks or credits',()=>{
 const station=blankStation();station.panorama={image:'photo.jpg',source:'teacher',author:'author',license:'licensed',mark:{kind:'arrow',x:.1,y:.2,x2:.3,y2:.4},mode:'cover',focus_x:.5,focus_y:.5,url:'/asset',preview_url:'/preview'};
 const payload=stationPayload(station);assert.equal(payload.panorama.url,undefined);assert.equal(payload.panorama.preview_url,undefined);assert.deepEqual(payload.panorama.mark,station.panorama.mark);assert.equal(station.panorama.url,'/asset');
});
test('pointer coordinates are scale independent and stay inside the original photograph',()=>{
 assert.deepEqual(point(150,200,{left:50,top:100,width:200,height:400}),{x:.5,y:.25});
 assert.deepEqual(point(-100,900,{left:50,top:100,width:200,height:400}),{x:0,y:1});
});
