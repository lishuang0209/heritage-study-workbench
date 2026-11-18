import copy
import json

import pytest
from PIL import Image

from test_ink_demo import setup, api, project
from test_heritage_study import prepared, create, clean
from scenarios.heritage_study.timing import observation_slots
from scenarios.heritage_study.templates import script_from_station


def change_timing(client, p, timing, version=0):
    r=client.put(f"/api/ink/projects/{p['id']}/heritage/timing",json={'version':version,'timing':timing})
    assert r.status_code==200,r.text
    return r.json()


def test_legacy_default_and_identical_timing_do_not_mutate_project(setup):
    store,client=setup;p=create(client);before=copy.deepcopy(store.load(p['id']))
    assert p['heritage_timing']=={'intro':12,'location':11,'task':7}
    q=change_timing(client,p,p['heritage_timing'])
    assert q['heritage_timing_version']==0 and store.load(p['id'])==before
    assert 'heritage_timing' not in before


def test_timing_persists_without_reconfirming_photos_or_removing_script_and_media(setup):
    store,client=setup;p=prepared(setup);old=copy.deepcopy(p)
    raw=store.load(p['id']);raw.update(final='old.mp4',task_card='old.pdf');store.save(raw)
    timing={'intro':20,'location':15,'task':10};q=change_timing(client,p,timing)
    assert q['heritage_ready'] and q['heritage_version']==p['heritage_version']
    assert q['heritage_timing_version']==1 and q['heritage_timing']==timing
    assert all(q['heritage_script'][key]==old['heritage_script'][key] for key in ('intro','location','task','version'))
    assert q['heritage_script']['confirmed_version'] is None
    assert q['final']=='old.mp4' and q['task_card']=='old.pdf' and q['final_stale'] and q['task_card_stale']
    base=f"/api/ink/projects/{p['id']}"
    assert client.post(base+'/heritage/confirm-script',json={'version':q['heritage_script']['version'],'teacher_verified':True}).status_code==409
    assert client.post(base+'/heritage/export',json={'version':q['heritage_version'],'timing_version':1}).status_code==422
    r=client.post(base+'/heritage/confirm-script',json={'version':q['heritage_script']['version'],'teacher_verified':True,'timing_version':1})
    assert r.status_code==200,r.text
    assert client.post(base+'/heritage/export',json={'version':q['heritage_version']}).status_code==409
    assert client.get(base).json()['heritage_timing']==timing and q['heritage_station']==old['heritage_station']


@pytest.mark.parametrize('timing',[
    {'intro':0,'location':11,'task':7},{'intro':12.5,'location':11,'task':7},
    {'intro':True,'location':11,'task':7},{'intro':181,'location':11,'task':7},
    {'intro':180,'location':180,'task':7},{'intro':'20','location':11,'task':7},
])
def test_invalid_timing_does_not_change_saved_content(setup,timing):
    store,client=setup;p=prepared(setup);before=store.load(p['id'])
    assert client.put(f"/api/ink/projects/{p['id']}/heritage/timing",json={'version':0,'timing':timing}).status_code==422
    assert store.load(p['id'])==before


def test_timing_version_and_readonly_guards(setup):
    _,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}/heritage/timing"
    timing={'intro':20,'location':15,'task':10};change_timing(client,p,timing)
    assert client.put(base,json={'version':0,'timing':timing}).status_code==409
    client.post('/api/ink/login',json={'token':'bob-test'})
    assert client.put(base,json={'version':1,'timing':timing}).status_code==403


def test_template_uses_more_supplied_history_when_intro_has_more_time():
    from scenarios.heritage_study.domain import empty_station
    station=empty_station();station.update(building='学堂',component='柱础',checked_description='历史背景：这里曾是学堂。后来曾经改为公共阅览场所。',instruction='看柱脚。',question='是什么形状？')
    short=script_from_station(station,{'intro':6,'location':11,'task':7})
    longer=script_from_station(station,{'intro':25,'location':15,'task':10})
    assert '公共阅览' not in short['intro'] and '公共阅览' in longer['intro']
    assert '1013' not in longer['intro']


def test_ai_prompt_uses_custom_timing_and_stale_results_do_not_overwrite(setup,monkeypatch):
    from models.llm_client import LLM
    store,client=setup;p=prepared(setup);p=change_timing(client,p,{'intro':20,'location':15,'task':10})
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    base=f"/api/ink/projects/{p['id']}"
    def query(self,prompt,**kwargs):
        assert '45秒短片' in prompt and '历史引入20秒' in prompt and '实物观察15秒' in prompt and '现场任务10秒' in prompt
        return json.dumps({'intro':'这里的大殿重建于北宋。','location':'观察照片标注。','task':'指出同一组斗拱。'},ensure_ascii=False)
    monkeypatch.setattr(LLM,'query',query)
    q=client.post(base+'/heritage/script-ai').json();assert q['heritage_script']['timing_version']==1
    saved=copy.deepcopy(q['heritage_script'])
    def stale(self,prompt,**kwargs):
        current=store.load(p['id']);current['heritage_timing_version']+=1;store.save(current)
        return json.dumps({'intro':'过时内容','location':'过时内容','task':'过时内容'},ensure_ascii=False)
    monkeypatch.setattr(LLM,'query',stale)
    q=client.post(base+'/heritage/script-ai').json()
    assert q['jobs'][0]['state']=='failed' and q['heritage_script']==saved


def test_custom_intro_budget_allows_longer_existing_story_import(setup):
    store,client=setup;source=project(store);shot=source['shots'][0]
    shot.update(duration=16,image='frame.jpg',clip='clip.mp4',rendered='clip.mp4',image_stale=False,clip_stale=False,rendered_stale=False)
    store.asset(source['id'],'frame.jpg').write_bytes(b'frame');store.asset(source['id'],'clip.mp4').write_bytes(b'video');store.save(source)
    p=prepared(setup);base=f"/api/ink/projects/{p['id']}/heritage/reuse-story"
    assert client.post(base,json={'source_project':source['id'],'shot_ids':[shot['id']]}).status_code==422
    change_timing(client,p,{'intro':20,'location':15,'task':10})
    assert client.post(base,json={'source_project':source['id'],'shot_ids':[shot['id']]}).status_code==200


def test_real_custom_movie_uses_requested_45_seconds_and_chapter_boundaries(setup,tmp_path):
    import subprocess
    from types import SimpleNamespace
    from scenarios.heritage_study.media import export_video
    from scenarios.ink_drama.providers import Providers,checked_ffmpeg,ffmpeg_executable
    store,client=setup;p=prepared(setup,detail=True);p=change_timing(client,p,{'intro':20,'location':15,'task':10})
    for slot,color in (('panorama','green'),('detail','blue')):
        Image.new('RGB',(900,1200),color).save(store.asset(p['id'],p['heritage_station'][slot]['image']))
    source=store.asset(p['id'],'long-story.mp4')
    checked_ffmpeg(['-f','lavfi','-i','color=c=red:s=180x320:r=24:d=16','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','16','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)])
    p['shots']=[{'id':'story','rendered':source.name,'image_stale':False,'clip_stale':False,'rendered_stale':False}]
    target=tmp_path/'custom.mp4';facade=SimpleNamespace(store=store,providers=Providers())
    chapters=export_video(facade,p,clean(p['heritage_station']),p['heritage_script'],tmp_path,target)
    assert [(c['kind'],c['duration']) for c in chapters]==[('story',20),('panorama',9),('detail',6),('task',10)]
    assert abs(Providers().duration(target)-45)<.1
    from test_heritage_widescreen import media_size
    assert media_size(target)==(1280,720) and Providers().has_audio(target)
    for second,color in ((19.5,(255,0,0)),(20.5,(0,128,0)),(29.5,(0,0,255)),(35.5,(0,0,255))):
        pixel=subprocess.check_output([ffmpeg_executable(),'-v','error','-ss',str(second),'-i',str(target),'-frames:v','1','-vf','crop=1:1:520:300,format=rgb24','-f','rawvideo','pipe:1'])
        assert max(abs(a-b) for a,b in zip(pixel,color))<20


def test_custom_narration_accepts_longer_intro_and_keeps_requested_total(tmp_path):
    from types import SimpleNamespace
    from scenarios.heritage_study.media import add_voiceover
    from scenarios.ink_drama.providers import Providers,checked_ffmpeg
    provider=Providers();target=tmp_path/'original.mp4';calls=[]
    checked_ffmpeg(['-f','lavfi','-i','color=c=white:s=180x320:r=30:d=23','-c:v','libx264','-pix_fmt','yuv420p',str(target)])
    def speak(text,voice,path,**kwargs):
        calls.append(text);seconds=13 if text=='长历史' else 1
        checked_ffmpeg(['-f','lavfi','-i',f'sine=frequency=440:duration={seconds}',str(path)])
    provider.speak=speak;facade=SimpleNamespace(providers=provider,call=lambda user,kind,pid,fn:fn())
    add_voiceover(facade,{'id':'qa','heritage_timing':{'intro':15,'location':5,'task':3}},{'intro':'长历史','location':'观察','task':'任务'},target,{})
    assert calls==['长历史','观察','任务'] and abs(provider.duration(target)-23)<.1 and provider.has_audio(target)


def test_observation_split_keeps_total_for_one_and_two_photos():
    assert observation_slots(11,True)==[('panorama',6),('detail',5)]
    assert observation_slots(15,True)==[('panorama',9),('detail',6)]
    assert observation_slots(20,False)==[('panorama',20)]
    for seconds in range(3,181):
        slots=observation_slots(seconds,True)
        assert sum(d for _,d in slots)==seconds and all(d>0 for _,d in slots)


def test_export_does_not_publish_a_result_after_timing_changes_mid_job(setup,monkeypatch):
    from scenarios.heritage_study import api as study_api
    store,client=setup;p=prepared(setup);p=change_timing(client,p,{'intro':20,'location':15,'task':10})
    base=f"/api/ink/projects/{p['id']}"
    client.post(base+'/heritage/confirm-script',json={'version':p['heritage_script']['version'],'teacher_verified':True,'timing_version':1})
    original=store.load(p['id']);original['final']='old.mp4';store.asset(p['id'],'old.mp4').write_bytes(b'old');store.save(original)
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    def exporting(api,p,station,script,folder,target):
        target.write_bytes(b'new')
        current=store.load(p['id']);current['heritage_timing']={'intro':30,'location':20,'task':10};current['heritage_timing_version']+=1;store.save(current)
        return [{'kind':'story','duration':20,'video':'new.mp4'}]
    monkeypatch.setattr(study_api,'export_video',exporting)
    q=client.post(base+'/heritage/export',json={'kind':'video','version':p['heritage_version'],'timing_version':1}).json()
    assert q['jobs'][0]['state']=='failed' and q['final']=='old.mp4'
    assert store.asset(p['id'],'old.mp4').read_bytes()==b'old'
