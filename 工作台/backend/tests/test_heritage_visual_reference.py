import copy
import hashlib

import pytest
from PIL import Image

from test_ink_demo import api, project, setup
from scenarios.heritage_study.domain import empty_station
from scenarios.heritage_study.visual_reference import reference_plan


MATERIAL='保国寺大殿重建于1013年。木构以斗拱衔接，前槽设有三个镂空藻井，并使用拼合柱。'


def fixture(setup, monkeypatch, *, style='工笔淡彩'):
    store, client = setup
    p = project(store)
    station = empty_station()
    station.update(building='宁波保国寺大殿',component='斗拱',checked_description=MATERIAL,panorama={
        'image':'real-photo.jpg','mode':'contain','focus_x':.5,'focus_y':.5,
        'source':'测试实拍','author':'测试作者','license':'测试授权',
        'mark':{'kind':'rectangle','x':.3,'y':.3,'x2':.7,'y2':.6}})
    p.update(project_type='heritage',heritage_station=station,heritage_version=7)
    Image.new('RGB',(1000,1200),'blue').save(store.folder(p['id'])/'real-photo.jpg')
    Image.new('RGB',(160,90),'white').save(store.folder(p['id'])/'old-umbrella.png')
    data=dict(characters=[],scenes=[dict(id='scene1',name='保国寺大殿',
              desc='依据已上传实拍中的可见建筑与空间关系，不补造不可见结构。',image=None)],
              props=[dict(id='prop1',name='斗拱',desc='层叠交错的木构件',image='old-umbrella.png')],style=style)
    p['creative_draft']=copy.deepcopy(data);store.save(p)
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    return store,client,p,data


def generate(client,p,data,group='props',**fields):
    response=client.post(f'/api/ink/projects/{p["id"]}/generate-setting-image',json={
        'settings':data,'group':group,'asset_id':'prop1' if group=='props' else 'scene1',**fields})
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.parametrize('style',['工笔淡彩','兼工带写','泼墨写意'])
def test_research_based_single_component_has_no_photo_old_image_or_subject_bearing_style_sample(setup,monkeypatch,style):
    store,client,p,data=fixture(setup,monkeypatch,style=style)
    original=store.asset(p['id'],'real-photo.jpg').read_bytes();before=copy.deepcopy(p['shots'])
    def image(prompt,refs,folder,pid,ratio='9:16'):
        assert ratio=='16:9' and '横屏16:9' in prompt
        assert refs==[] and MATERIAL in prompt and style in prompt
        assert '单张完整构件' in prompt and '外轮廓' in prompt and '只展示一个目标构件组的一个视角' in prompt
        assert '禁止三视图、多视角并列' in prompt
        assert '单个道具设定图' not in prompt and '第1张是本讲解站上传的真实照片' not in prompt
        assert 'soft-props.png' not in prompt and 'old-umbrella.png' not in prompt
        return folder/'old-umbrella.png'
    monkeypatch.setattr(api.providers,'image',image)
    result=generate(client,p,data)
    assert result['jobs'][0]['state']=='completed',result['jobs'][0]
    saved=store.load(p['id']);generated=saved['creative_draft']['props'][0]['image']
    record=saved['setting_generation_records'][generated]
    assert record['reference_mode']=='heritage-research' and record['references']==[]
    source=record['heritage_reference']
    assert source['station_version']==7 and source['layout']=='component-single-view'
    assert source['material_digest']==hashlib.sha256(MATERIAL.encode()).hexdigest()
    assert not {'source_image','mark','crop'} & source.keys()
    assert store.asset(p['id'],'real-photo.jpg').read_bytes()==original
    assert store.asset(p['id'],'old-umbrella.png').is_file()
    assert any(v['image']=='old-umbrella.png' for v in saved['setting_image_history']['props:prop1'])
    assert saved['shots']==before
    assert result['heritage_setting_references'][-1]['mode']=='research'


@pytest.mark.parametrize('photo_state',['absent','unmarked','missing_file','corrupt_file','arrow'])
def test_material_generation_does_not_require_a_field_photo_or_annotation(setup,monkeypatch,photo_state):
    store,client,p,data=fixture(setup,monkeypatch)
    if photo_state=='absent':p['heritage_station']['panorama']=None
    elif photo_state=='unmarked':p['heritage_station']['panorama']['mark']=None
    elif photo_state=='missing_file':store.asset(p['id'],'real-photo.jpg').unlink()
    elif photo_state=='corrupt_file':store.asset(p['id'],'real-photo.jpg').write_bytes(b'not an image')
    else:p['heritage_station']['panorama']['mark']=dict(kind='arrow',x=.4,y=.5,x2=.4,y2=.3)
    store.save(p)
    def image(prompt,refs,folder,pid,ratio='9:16'):
        assert refs==[] and MATERIAL in prompt
        return folder/'old-umbrella.png'
    monkeypatch.setattr(api.providers,'image',image)
    result=generate(client,p,data,'scenes')
    assert result['jobs'][0]['state']=='completed',result['jobs'][0]


@pytest.mark.parametrize('view',['front','sheet'])
def test_building_is_a_single_panorama_even_if_a_legacy_client_requests_sheet(setup,monkeypatch,view):
    store,client,p,data=fixture(setup,monkeypatch)
    def image(prompt,refs,folder,pid,ratio='9:16'):
        assert ratio=='16:9' and refs==[]
        assert MATERIAL in prompt and '单张建筑全景' in prompt
        assert '只绘制一栋主体建筑的一个视角' in prompt
        assert '禁止三视图、多视角并列' in prompt
        assert '从左到右展示' not in prompt and '三个视角' not in prompt
        assert all(term in prompt for term in ('屋顶、殿身、台基','四周留边'))
        assert '不以檐下、梁架、斗拱特写代替全景' in prompt
        assert '依据已上传实拍中的可见建筑与空间关系，不补造不可见结构。' not in prompt
        assert '不凭局部照片补造完整外观' not in prompt
        return folder/'old-umbrella.png'
    monkeypatch.setattr(api.providers,'image',image)
    result=generate(client,p,data,'scenes',view=view)
    assert result['jobs'][0]['state']=='completed',result['jobs'][0]
    assert result['heritage_setting_references'][0]['layout']=='panoramic-single-view'


def test_missing_research_stops_before_paid_call_and_retains_the_original_asset(setup,monkeypatch):
    store,client,p,data=fixture(setup,monkeypatch)
    p['heritage_station']['checked_description']='';store.save(p)
    def unexpected(*args,**kwargs):pytest.fail('Missing research must not reach a paid provider')
    monkeypatch.setattr(api.providers,'image',unexpected)
    result=generate(client,p,data)
    assert result['jobs'][0]['state']=='failed' and '研学资料' in result['jobs'][0]['error']
    assert result['creative_draft']['props'][0]['image']=='old-umbrella.png'
    assert store.usage('alice').get('image',0)==0


def test_other_story_props_use_their_own_description_not_the_station_target_or_style_sample(setup,monkeypatch):
    store,client,p,data=fixture(setup,monkeypatch)
    assert reference_plan(p,'characters',dict(id='c1',name='讲解员')) is None
    assert reference_plan({**p,'project_type':'ink'},'props',data['props'][0]) is None
    data['props'][0].update(name='木凳',desc='四脚方形木凳，腿间有横撑')
    def image(prompt,refs,folder,pid,ratio='9:16'):
        assert refs==[] and '木凳：四脚方形木凳' in prompt
        assert '当前素材名称决定主体' in prompt
        return folder/'old-umbrella.png'
    monkeypatch.setattr(api.providers,'image',image)
    result=generate(client,p,data)
    assert result['jobs'][0]['state']=='completed'


def test_storyboard_frame_uses_material_sheet_as_shape_reference_without_repeating_its_panels():
    from scenarios.ink_drama.domain import frame_prompt
    p=dict(project_type='heritage',characters=[],creative_settings=dict(characters=[],scenes=[],props=[],style='工笔淡彩'))
    prompt=frame_prompt(p,dict(content='大殿正面全景',scene='大殿',camera='全景，正面平视',character_ids=[],prop_ids=[]))
    assert '只输出一个视角的一幅静态画面，建筑视角不能叠加' in prompt
    assert '屋顶、殿身和基座' in prompt
