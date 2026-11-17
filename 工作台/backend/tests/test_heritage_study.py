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


def test_unified_guidance_confirmation_no_longer_requires_a_separate_position(setup):
    _,client=setup;p=prepared(setup);station=p['heritage_station']
    assert station['standing_position']=='' and p['heritage_ready']
    base=f"/api/ink/projects/{p['id']}"
    station['instruction']='对照照片标注，找到同一组斗拱。';p=save(client,p,station)
    assert client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True}).status_code==200
    station['instruction']='';p=save(client,p,station)
    r=client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True})
    assert r.status_code==422 and '观察指引' in r.json()['detail'] and '站位' not in r.json()['detail']


def test_legacy_position_is_kept_in_script_preview_and_card_without_read_time_writes(setup,tmp_path,monkeypatch):
    from scenarios.heritage_study import media
    store,client=setup;p=prepared(setup);station=p['heritage_station']
    station.update(standing_position='大殿东侧围栏外',instruction='沿第二根柱子向上找斗拱。')
    p=save(client,p,station);base=f"/api/ink/projects/{p['id']}";saved=store.load(p['id'])
    q=client.get(base).json();assert q['heritage_station']['standing_position']==station['standing_position']
    assert snapshot(store.load(p['id']))==snapshot(saved)
    guidance='大殿东侧围栏外。沿第二根柱子向上找斗拱。'
    q=client.post(base+'/heritage/script-template').json()
    assert q['heritage_script']['location'].endswith(guidance)
    assert station['question'] in q['heritage_script']['task']
    preview=[]
    def frame(store,pid,station,slot,text):
        preview.append(text);return Image.new('RGB',(720,1280),'white')
    monkeypatch.setattr(study_api,'photo_frame',frame)
    assert client.get(p['heritage_station']['panorama']['preview_url']).status_code==200
    assert preview==[guidance+'\n'+station['question']]
    text=[];original=media.block
    def block(draw,value,*args,**kwargs):
        text.append(value);return original(draw,value,*args,**kwargs)
    monkeypatch.setattr(media,'block',block)
    media.task_card(store,p['id'],clean(station),tmp_path/'legacy-card.pdf')
    assert '观察指引\n'+guidance in text
    assert not any(value.startswith('观察站位：') for value in text)


def test_long_legacy_guidance_can_be_merged_saved_and_script_remains_editable(setup):
    _,client=setup;p=prepared(setup);station=p['heritage_station']
    from scenarios.heritage_study.domain import observation_guidance
    station.update(standing_position='位置说明'*50,instruction='观察指令'*50)
    guidance=observation_guidance(station)
    station.update(instruction=guidance,standing_position='');p=save(client,p,station)
    base=f"/api/ink/projects/{p['id']}"
    q=client.post(base+'/heritage/script-template').json();script=q['heritage_script']
    assert script['location'].endswith(guidance)
    r=client.put(base+'/heritage/script',json={key:script[key] for key in ('intro','location','task','version','station_version')})
    assert r.status_code==200,r.text
    assert r.json()['heritage_script']['location'].endswith(guidance)


@pytest.mark.parametrize('slot,color,source',[('panorama','white','10-34-40'),('detail','blue','10-34-26')])
def test_known_photo_credits_use_content_even_when_renamed(setup,monkeypatch,slot,color,source):
    import hashlib
    from scenarios.heritage_study import photo_credits
    _,client=setup;p=create(client);data=picture(color)
    credit={'source':'https://commons.wikimedia.org/wiki/File:Ningbo_Baoguo_Si_2013.07.27_'+source+'.jpg','author':'Zhangzhugang','license':'CC BY-SA 3.0','credit_kind':'catalog'}
    monkeypatch.setattr(photo_credits,'catalog',lambda:{hashlib.sha256(data).hexdigest():credit})
    q=client.post(f"/api/ink/projects/{p['id']}/heritage/photos/{slot}",params={'version':0},files={'file':('renamed.jpg',data,'image/jpeg')}).json()
    assert all(q['heritage_station'][slot][key]==value for key,value in credit.items())
    assert q['heritage_station'][slot]['mark'] is None
    assert client.get('/api/ink/projects/'+p['id']).json()['heritage_station'][slot]['author']=='Zhangzhugang'


def test_unknown_photo_does_not_inherit_a_license_from_its_filename(setup):
    _,client=setup;p=create(client)
    q=client.post(f"/api/ink/projects/{p['id']}/heritage/photos/panorama",params={'version':0},files={'file':('01-现场定位图.jpg',picture('yellow'),'image/jpeg')}).json()
    photo=q['heritage_station']['panorama']
    assert photo['credit_kind']=='unresolved'
    assert not any(photo[key] for key in ('source','author','license'))


def test_existing_photo_credits_are_recovered_once_and_marks_are_preserved(setup,monkeypatch):
    import hashlib
    from scenarios.heritage_study import photo_credits
    store,client=setup;p=prepared(setup);station=p['heritage_station'];photo=station['panorama']
    photo.update(source='',author='',license='');p=save(client,p,station)
    stored=store.load(p['id']);stored.update(final='old.mp4',task_card='old.pdf');store.save(stored)
    image=store.asset(p['id'],photo['image']).read_bytes()
    credit=dict(source='https://commons.wikimedia.org/verified-photo',author='Verified photographer',license='CC BY-SA 3.0',credit_kind='catalog')
    monkeypatch.setattr(photo_credits,'catalog',lambda:{hashlib.sha256(image).hexdigest():credit})
    base=f"/api/ink/projects/{p['id']}/heritage/photo-credits"
    r=client.post(base,json={'version':p['heritage_version']});assert r.status_code==200
    q=r.json();assert q['heritage_station']['panorama']['mark']==photo['mark']
    assert q['heritage_station']['panorama']['image']==photo['image']
    assert q['heritage_station']['panorama']['author']=='Verified photographer'
    assert q['heritage_version']==p['heritage_version']+1 and not q['heritage_ready']
    assert q['final_stale'] and q['task_card_stale']
    assert client.post(base,json={'version':p['heritage_version']}).status_code==409
    repeated=client.post(base,json={'version':q['heritage_version']}).json()
    assert repeated['heritage_version']==q['heritage_version']


def test_existing_manual_credits_and_readonly_projects_are_not_overwritten(setup):
    _,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}/heritage/photo-credits"
    q=client.post(base,json={'version':p['heritage_version']}).json()
    assert q['heritage_station']==p['heritage_station'] and q['heritage_version']==p['heritage_version']
    client.post('/api/ink/login',json={'token':'bob-test'})
    assert client.post(base,json={'version':p['heritage_version']}).status_code==403


@pytest.mark.parametrize('kind',['self','authorized'])
def test_source_selection_fills_credits_without_manual_text(setup,kind):
    _,client=setup;p=prepared(setup);station=p['heritage_station']
    station['panorama'].update(credit_kind=kind,source='',author='',license='')
    p=save(client,p,station);photo=p['heritage_station']['panorama']
    assert all(photo[key] for key in ('source','author','license'))
    assert photo['credit_kind']==kind
    assert photo['mark']==station['panorama']['mark']
    assert 'Zhangzhugang' not in photo['author'] and 'CC BY' not in photo['license']
    assert client.post(f"/api/ink/projects/{p['id']}/heritage/confirm",json={'version':p['heritage_version'],'teacher_verified':True}).status_code==200


@pytest.mark.parametrize('mark',[
    {'kind':'rectangle','x':.6,'y':.5,'x2':.2,'y2':.2},
    {'kind':'arrow','x':.2,'y':.4,'x2':.6,'y2':.4},
])
def test_detail_is_a_true_crop_with_transformed_annotation_and_inherited_credits(setup,mark):
    store,client=setup;p=prepared(setup,detail=True);base=f"/api/ink/projects/{p['id']}"
    old_detail=p['heritage_station']['detail']['image'];source=p['heritage_station']['panorama']['image']
    vertical=Image.linear_gradient('L').resize((900,1200))
    horizontal=Image.linear_gradient('L').rotate(90).resize((900,1200))
    Image.merge('RGB',(vertical,horizontal,Image.new('L',(900,1200),120))).save(store.asset(p['id'],source),quality=94)
    source_bytes=store.asset(p['id'],source).read_bytes()
    station=p['heritage_station'];station['panorama']['mark']=mark;p=save(client,p,station)
    r=client.post(base+'/heritage/detail-from-mark',json={'version':p['heritage_version']});assert r.status_code==200,r.text
    q=r.json();detail=q['heritage_station']['detail'];panorama=q['heritage_station']['panorama']
    record=store.load(p['id'])['heritage_uploads'][detail['image']];left,top,right,bottom=record['crop']
    assert detail['derived_from']==source and detail['derived_mark']==mark
    assert all(detail[key]==panorama[key] for key in ('source','author','license','credit_kind'))
    assert q['heritage_version']==p['heritage_version']+1 and not q['heritage_ready']
    for coordinate,dimension,offset,extent in [('x',900,left,right-left),('x2',900,left,right-left),('y',1200,top,bottom-top),('y2',1200,top,bottom-top)]:
        assert detail['mark'][coordinate]==pytest.approx((mark[coordinate]*dimension-offset)/extent)
    with Image.open(store.asset(p['id'],source)) as original, Image.open(store.asset(p['id'],detail['image'])) as crop:
        assert crop.size==(right-left,bottom-top)
        for x,y in [(crop.width//3,crop.height//3),(crop.width//2,crop.height//2)]:
            assert max(abs(a-b) for a,b in zip(crop.getpixel((x,y)),original.getpixel((left+x,top+y))))<10
    assert store.asset(p['id'],source).read_bytes()==source_bytes
    assert store.asset(p['id'],old_detail).is_file()
    assert client.post(base+'/heritage/confirm',json={'version':q['heritage_version'],'teacher_verified':True}).status_code==200


@pytest.mark.parametrize('change',['mark','image'])
def test_source_changes_block_confirmation_preview_and_export_until_detail_is_updated(setup,change):
    store,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    p=client.post(base+'/heritage/detail-from-mark',json={'version':p['heritage_version']}).json()
    previous=p['heritage_station']['detail']['image']
    if change=='image':
        p=client.post(base+'/heritage/photos/panorama',params={'version':p['heritage_version']},files={'file':('new.jpg',picture('blue'),'image/jpeg')}).json()
    station=p['heritage_station'];station['panorama']['mark']={'kind':'rectangle','x':.25,'y':.25,'x2':.65,'y2':.55}
    station['panorama'].update(source='新照片',author='老师',license='已授权');p=save(client,p,station)
    response=client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True,'same_target_verified':True})
    assert response.status_code==422 and '更新特写' in response.json()['detail']
    assert client.get(p['heritage_station']['detail']['preview_url']).status_code==422
    assert client.post(base+'/heritage/export',json={'kind':'both','version':p['heritage_version']}).status_code==422
    p=client.post(base+'/heritage/detail-from-mark',json={'version':p['heritage_version']}).json()
    assert p['heritage_station']['detail']['image']!=previous and store.asset(p['id'],previous).is_file()
    assert client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True}).status_code==200


def test_derived_mark_is_locked_and_uploads_cannot_forge_an_automatic_link(setup):
    store,client=setup;p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    p=client.post(base+'/heritage/detail-from-mark',json={'version':p['heritage_version']}).json()
    station=p['heritage_station'];station['detail']['mark']['x']+=.03
    response=client.put(base+'/heritage/station',json={'version':p['heritage_version'],'station':clean(station)})
    assert response.status_code==422 and '随定位图' in response.json()['detail']
    # A separately uploaded photo remains a manual match, even if client metadata claims a link.
    p=prepared(setup,detail=True);base=f"/api/ink/projects/{p['id']}";station=p['heritage_station']
    station['detail'].update(derived_from=station['panorama']['image'],derived_mark=station['panorama']['mark']);p=save(client,p,station)
    assert p['heritage_station']['detail']['derived_from'] is None
    assert client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True}).status_code==422


def test_detail_generation_guards_missing_marks_versions_readonly_and_credits_follow_source(setup):
    _,client=setup;p=create(client);base=f"/api/ink/projects/{p['id']}"
    assert client.post(base+'/heritage/detail-from-mark',json={'version':0}).status_code==422
    p=prepared(setup);base=f"/api/ink/projects/{p['id']}"
    assert client.post(base+'/heritage/detail-from-mark',json={'version':0}).status_code==409
    p=client.post(base+'/heritage/detail-from-mark',json={'version':p['heritage_version']}).json()
    station=p['heritage_station'];station['panorama'].update(credit_kind='self');p=save(client,p,station)
    assert p['heritage_station']['detail']['source']==p['heritage_station']['panorama']['source']
    assert p['heritage_station']['detail']['mark'] is not None
    client.post('/api/ink/login',json={'token':'bob-test'})
    assert client.post(base+'/heritage/detail-from-mark',json={'version':p['heritage_version']}).status_code==403


@pytest.mark.parametrize('index',[0,1,2])
def test_history_templates_introduce_place_before_observation_without_source_notes(setup,index):
    _,client=setup;p=prepared(setup,case_index=index);script=p['heritage_script'];case=CASES[index]
    assert script['intro']==case['intro'] and len(script['intro'])<70
    assert any(term in script['intro'] for term in ('北宋','宋代','明清'))
    assert case['station']['question'] in script['task']
    assert 'http' not in ''.join(script[key] for key in ('intro','location','task'))
    assert '现场核对' not in script['intro'] and '待老师核对' not in script['intro']
    assert case['sources'][0]['url'] in case['station']['checked_description']


def test_custom_research_uses_only_provided_history_and_keeps_observation_separate(setup):
    _,client=setup;p=prepared(setup);station=p['heritage_station']
    station.update(building='自选古建',checked_description='历史背景：这处建筑曾是当地的公共学堂。\n观察重点：柱脚有石雕。\n现场核对：历史年代待核实。\n资料来源：https://example.invalid/history')
    p=save(client,p,station);q=client.post(f"/api/ink/projects/{p['id']}/heritage/script-template").json()['heritage_script']
    assert '曾是当地的公共学堂' in q['intro'] and '柱脚有石雕' not in q['intro']
    assert q['location'].startswith('柱脚有石雕。')
    assert not any(term in q['intro'] for term in ('北宋','1013','康熙','example.invalid','待核实'))
    from scenarios.heritage_study.templates import research_excerpt
    assert research_excerpt('这里重建于1900年。现为学堂。')[0]=='这里重建于1900年'
    assert research_excerpt('历史背景：这里曾是学堂；观察重点：柱脚石雕；资料来源：https://example.invalid')==('这里曾是学堂','柱脚石雕')


def test_missing_history_remains_an_explicit_draft_and_never_calls_ai(setup,monkeypatch):
    from models.llm_client import LLM
    _,client=setup;p=prepared(setup);station=p['heritage_station']
    station['checked_description']='观察重点：沿柱子上方观察木构件。';p=save(client,p,station);base=f"/api/ink/projects/{p['id']}"
    q=client.post(base+'/heritage/script-template').json();assert '【待补充历史背景】' in q['heritage_script']['intro']
    r=client.post(base+'/heritage/confirm-script',json={'version':q['heritage_script']['version'],'teacher_verified':True})
    assert r.status_code==422 and '历史' in r.json()['detail']
    calls=[];monkeypatch.setattr(LLM,'query',lambda *args,**kwargs:calls.append('called'))
    r=client.post(base+'/heritage/script-ai');assert r.status_code==422 and '未调用模型' in r.json()['detail']
    assert calls==[]


def test_overlong_history_template_does_not_replace_existing_script(setup):
    _,client=setup;p=prepared(setup);old=copy.deepcopy(p['heritage_script']);station=p['heritage_station']
    station['checked_description']='历史背景：'+('长资料'*150)+'。';p=save(client,p,station)
    r=client.post(f"/api/ink/projects/{p['id']}/heritage/script-template")
    assert r.status_code==422 and '原脚本已保留' in r.json()['detail']
    assert client.get('/api/ink/projects/'+p['id']).json()['heritage_script']==old
