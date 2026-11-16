import copy
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from PyPDF2 import PdfReader

from test_ink_demo import setup, project, api
from scenarios.heritage_study import api as study_api
from scenarios.heritage_study.domain import crop_bounds, snapshot
from scenarios.heritage_study.media import task_card, annotated_photo, photo_frame
from scenarios.heritage_study.templates import CASES


def picture(color='white',size=(900,1200)):
    data=io.BytesIO();Image.new('RGB',size,color).save(data,'JPEG');return data.getvalue()


def clean(station):
    value=copy.deepcopy(station)
    for slot in ('panorama','detail'):
        if value.get(slot):
            value[slot].pop('url',None);value[slot].pop('preview_url',None)
    return value


def create(client):
    r=client.post('/api/ink/projects',json={'title':'保国寺找斗拱','script':'测试故事','project_type':'heritage'})
    assert r.status_code==200
    return r.json()


def save(client,p,station):
    r=client.put(f"/api/ink/projects/{p['id']}/heritage/station",json={'version':p['heritage_version'],'station':clean(station)})
    assert r.status_code==200,r.text
    return r.json()


def prepared(setup, detail=False, case_index=0):
    store,client=setup;p=create(client);base=f"/api/ink/projects/{p['id']}"
    for slot in ('panorama','detail') if detail else ('panorama',):
        r=client.post(base+f'/heritage/photos/{slot}',params={'version':p['heritage_version']},files={'file':('field.jpg',picture(),'image/jpeg')})
        assert r.status_code==200;r=r.json();p=r
    station={**p['heritage_station'],**CASES[case_index]['station']}
    for slot in ('panorama','detail'):
        if station[slot]:station[slot].update(source='技术测试照片，不可作为建筑证据',author='测试作者',license='测试素材',mark={'kind':'rectangle','x':.2,'y':.2,'x2':.6,'y2':.5})
    p=save(client,p,station)
    r=client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True,'same_target_verified':detail})
    assert r.status_code==200,r.text;p=r.json()
    r=client.post(base+'/heritage/script-template');assert r.status_code==200;p=r.json()
    r=client.post(base+'/heritage/confirm-script',json={'version':p['heritage_script']['version'],'teacher_verified':True})
    assert r.status_code==200
    return r.json()


def test_station_persists_and_legacy_type_remains_editable(setup):
    store,client=setup;old=project(store)
    assert 'project_type' not in store.load(old['id'])
    assert client.get('/api/ink/projects/'+old['id']).json()['project_type']=='ink'
    p=create(client);station=p['heritage_station'];station.update(CASES[0]['station']);p=save(client,p,station)
    reopened=client.get('/api/ink/projects/'+p['id']).json()
    assert reopened['heritage_station']['component']=='斗拱'
    assert reopened['project_type']=='heritage'
    assert client.get('/api/ink/projects').json()['projects'][0]['project_type']=='heritage'
    assert client.put('/api/ink/projects/'+old['id']+'/heritage/station',json={'version':0,'station':station}).status_code==422


def test_missing_annotations_credits_and_human_review_block_export(setup):
    _,client=setup;p=create(client);base=f"/api/ink/projects/{p['id']}"
    assert client.post(base+'/heritage/export',json={'kind':'both','version':0}).status_code==422
    r=client.post(base+'/heritage/confirm',json={'version':0,'teacher_verified':True})
    assert r.status_code==422 and '补齐' in r.json()['detail']
    p=prepared(setup)
    station=p['heritage_station'];station['panorama']['author']='';p=save(client,p,station)
    r=client.post(base.replace(base.split('/')[-1],p['id'])+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True})
    assert r.status_code==422 and '来源' in r.json()['detail']


def test_replacing_photo_clears_mark_confirmation_and_both_exports(setup):
    store,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    stored=store.load(p['id']);stored.update(final='old.mp4',task_card='old.pdf',heritage_export_stamp=snapshot(stored));store.save(stored)
    r=client.post(base+'/heritage/photos/panorama',params={'version':p['heritage_version']},files={'file':('replacement.png',picture('blue'),'image/png')})
    assert r.status_code==200;q=r.json()
    assert q['heritage_station']['panorama']['mark'] is None
    assert q['heritage_station']['panorama']['author']==''
    assert not q['heritage_ready'] and q['final_stale'] and q['task_card_stale']
    assert store.asset(p['id'],p['heritage_station']['panorama']['image']).is_file()


def test_task_edits_invalidate_exports_and_script_review(setup):
    store,client=setup;p=prepared(setup)
    saved=store.load(p['id']);saved.update(final='old.mp4',task_card='old.pdf');store.save(saved)
    station=p['heritage_station'];station['question']='哪一层更向外伸？';p=save(client,p,station)
    assert p['final_stale'] and p['task_card_stale'] and not p['heritage_ready']
    assert p['heritage_script']['station_version']!=p['heritage_version']
    assert client.post(f"/api/ink/projects/{p['id']}/heritage/export",json={'kind':'both','version':p['heritage_version']}).status_code==422


def test_crop_protection_and_scaled_arrow_preview(setup):
    _,client=setup;p=prepared(setup);station=p['heritage_station'];photo=station['panorama']
    photo.update(mode='cover',mark={'kind':'arrow','x':.2,'y':.02,'x2':.3,'y2':.06})
    # A landscape image's central portrait crop cannot contain this corner target.
    base=f"/api/ink/projects/{p['id']}"
    p=client.post(base+'/heritage/photos/panorama',params={'version':p['heritage_version']},files={'file':('landscape.jpg',picture(size=(1600,900)),'image/jpeg')}).json()
    station['panorama']['image']=p['heritage_station']['panorama']['image'];station['panorama'].update(source='test',author='teacher',license='test')
    p=save(client,p,station)
    r=client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True})
    assert r.status_code==422 and '裁切' in r.json()['detail']
    station['panorama']['mode']='contain';p=save(client,p,station)
    r=client.get(p['heritage_station']['panorama']['preview_url'])
    assert r.status_code==200 and Image.open(io.BytesIO(r.content)).size==(720,1280)
    assert client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':False}).status_code==422


@pytest.mark.parametrize('index',[0,1,2])
def test_templates_support_single_target_and_optional_detail_confirmation(setup,index):
    _,client=setup;p=prepared(setup,detail=index>0,case_index=index)
    assert p['heritage_ready']
    assert p['heritage_script']['confirmed_version']==p['heritage_script']['version']
    assert p['heritage_station']['component']==CASES[index]['station']['component']
    if index:
        assert client.post(f"/api/ink/projects/{p['id']}/heritage/confirm",json={'version':p['heritage_version'],'teacher_verified':True}).status_code==422


def test_foreign_asset_cross_slot_revision_and_readonly_guards(setup):
    store,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    station=p['heritage_station'];station['panorama']['image']='other.jpg'
    assert client.put(base+'/heritage/station',json={'version':p['heritage_version'],'station':clean(station)}).status_code==422
    assert client.put(base+'/heritage/station',json={'version':999,'station':clean(station)}).status_code==409
    assert client.post('/api/ink/login',json={'token':'bob-test'}).status_code==200
    assert client.get(base).status_code==200
    assert client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True}).status_code==403
    assert client.post(base+'/heritage/export',json={'kind':'both','version':p['heritage_version']}).status_code==403


def test_reuse_copies_only_selected_ready_story_and_keeps_source_independent(setup):
    store,client=setup;source=project(store);s=source['shots'][0]
    s.update(duration=3,image='frame.png',clip='clip.mp4',rendered='clip.mp4',image_stale=False,clip_stale=False,rendered_stale=False)
    store.asset(source['id'],'clip.mp4').write_bytes(b'original');store.asset(source['id'],'frame.png').write_bytes(b'original frame');store.save(source)
    p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    r=client.post(base+'/heritage/reuse-story',json={'source_project':source['id'],'shot_ids':[s['id']]})
    assert r.status_code==200,r.text
    shot=r.json()['shots'][0]
    assert shot['rendered']!='clip.mp4' and shot['duration']==3
    assert store.asset(p['id'],shot['rendered']).read_bytes()==b'original'
    assert store.load(source['id'])['shots'][0]['rendered']=='clip.mp4'
    assert client.post(base+'/actions/assemble').status_code==422


def test_card_is_one_a4_page_and_uses_same_annotation_geometry(setup,tmp_path):
    store,client=setup;p=prepared(setup);station=clean(p['heritage_station'])
    target=tmp_path/'card.pdf';task_card(store,p['id'],station,target)
    reader=PdfReader(str(target));assert len(reader.pages)==1
    box=reader.pages[0].mediabox;assert abs(float(box.width)-595.2)<1 and abs(float(box.height)-841.92)<1
    photo=annotated_photo(store,p['id'],station['panorama'])
    # The mark is at normalized x=.2,y=.2 on a 3:4 image (720x960 output).
    assert photo.getpixel((144,192))[0]>100
    assert photo.getpixel((144,192))[1]<100


def test_export_success_failure_retains_previous_files_and_human_trial_numbers(setup,monkeypatch):
    store,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    def video(api,p,station,script,folder,target):target.write_bytes(b'test video');return [{'kind':'story','duration':12,'video':'story.mp4'},{'kind':'panorama','duration':11,'video':'photo.mp4'},{'kind':'task','duration':7,'video':'task.mp4'}]
    monkeypatch.setattr(study_api,'export_video',video)
    r=client.post(base+'/heritage/export',json={'kind':'both','version':p['heritage_version']})
    assert r.status_code==200,r.text;q=r.json()
    assert q['jobs'][0]['state']=='completed' and not q['final_stale'] and not q['task_card_stale']
    assert client.get(q['task_card_url']).content.startswith(b'%PDF')
    assert client.get(q['final_url']).content==b'test video'
    def failure(*args):raise UserError('测试导出失败')
    from scenarios.ink_drama.domain import UserError
    monkeypatch.setattr(study_api,'task_card',failure)
    r=client.post(base+'/heritage/export',json={'kind':'both','version':p['heritage_version']}).json()
    assert r['jobs'][0]['state']=='failed' and r['final']==q['final'] and r['task_card']==q['task_card']
    assert client.put(base+'/heritage/trial',json={'participants':10,'found_without_hint':11,'preparation_minutes':30}).status_code==422
    assert client.put(base+'/heritage/trial',json={'participants':10,'found_without_hint':7,'preparation_minutes':30}).status_code==200


def test_ai_script_uses_teacher_data_and_only_changes_script_after_valid_result(setup,monkeypatch):
    from models.llm_client import LLM
    _,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    def query(self,prompt,**kwargs):
        assert p['heritage_station']['grade'] in prompt and '不补充年代' in prompt
        return json.dumps({'intro':'木匠抬头观察。','location':'对照照片标注。','task':'找到目标，说说伸出方向。'},ensure_ascii=False)
    monkeypatch.setattr(LLM,'query',query)
    q=client.post(base+'/heritage/script-ai').json()
    assert q['heritage_script']['intro']=='木匠抬头观察。'
    assert q['heritage_script']['confirmed_version'] is None
    monkeypatch.setattr(LLM,'query',lambda *args,**kwargs:'not json')
    q=client.post(base+'/heritage/script-ai').json()
    assert q['jobs'][0]['state']=='failed' and q['heritage_script']['intro']=='木匠抬头观察。'


@pytest.mark.parametrize('case_index',[1,2])
def test_real_detail_movie_goes_from_panorama_to_same_target_detail(setup,tmp_path,case_index):
    from types import SimpleNamespace
    import subprocess
    from scenarios.ink_drama.providers import Providers,checked_ffmpeg,ffmpeg_executable
    from scenarios.heritage_study.media import export_video
    store,client=setup;p=prepared(setup,detail=True,case_index=case_index)
    for slot,color in (('panorama','green'),('detail','blue')):
        Image.new('RGB',(900,1200),color).save(store.asset(p['id'],p['heritage_station'][slot]['image']))
    story=store.asset(p['id'],'story.mp4')
    checked_ffmpeg(['-f','lavfi','-i','color=c=red:s=180x320:r=24:d=2','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(story)])
    p['shots']=[{'id':'story','rendered':story.name,'image_stale':False,'clip_stale':False,'rendered_stale':False}]
    target=tmp_path/f'{case_index}-study.mp4';facade=SimpleNamespace(store=store,providers=Providers())
    chapters=export_video(facade,p,clean(p['heritage_station']),p['heritage_script'],tmp_path,target)
    assert [(x['kind'],x['duration']) for x in chapters]==[('story',12),('panorama',6),('detail',5),('task',7)]
    assert abs(Providers().duration(target)-30)<.1
    for time,color in ((.5,(255,0,0)),(12.5,(0,128,0)),(18.5,(0,0,255)),(23.5,(0,0,255))):
        pixel=subprocess.check_output([ffmpeg_executable(),'-v','error','-ss',str(time),'-i',str(target),'-frames:v','1','-vf','crop=1:1:400:600,format=rgb24','-f','rawvideo','pipe:1'])
        assert max(abs(a-b) for a,b in zip(pixel,color))<20
    card=tmp_path/f'{case_index}-card.pdf';task_card(store,p['id'],clean(p['heritage_station']),card)
    assert len(PdfReader(str(card)).pages)==1


def test_optional_narration_checks_each_chapter_duration_before_replacing_video(tmp_path):
    from types import SimpleNamespace
    from scenarios.heritage_study.media import add_voiceover
    from scenarios.ink_drama.domain import UserError
    target=tmp_path/'old.mp4';target.write_bytes(b'old')
    def speak(text,voice,path):path.write_bytes(b'audio')
    facade=SimpleNamespace(providers=SimpleNamespace(speak=speak,duration=lambda path:13),call=lambda user,kind,pid,fn:fn())
    with pytest.raises(UserError,match='超过12秒'):
        add_voiceover(facade,{'id':'project'},{'intro':'过长','location':'定位','task':'任务'},target,{})
    assert target.read_bytes()==b'old'


def test_optional_narration_keeps_three_texts_and_pads_to_30_seconds(tmp_path):
    from types import SimpleNamespace
    from scenarios.heritage_study.media import add_voiceover
    from scenarios.ink_drama.providers import Providers,checked_ffmpeg
    provider=Providers();calls=[]
    target=tmp_path/'original.mp4'
    checked_ffmpeg(['-f','lavfi','-i','color=c=white:s=180x320:r=30:d=30',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(target)])
    def speak(text,voice,path):
        calls.append(text)
        checked_ffmpeg(['-f','lavfi','-i','sine=frequency=440:duration=1',str(path)])
    provider.speak=speak
    facade=SimpleNamespace(providers=provider,call=lambda user,kind,pid,fn:fn())
    add_voiceover(facade,{'id':'qa'},{'intro':'故事台词','location':'实拍定位台词','task':'寻找任务台词'},target,{})
    assert calls==['故事台词','实拍定位台词','寻找任务台词']
    assert abs(provider.duration(target)-30)<.1 and provider.has_audio(target)
