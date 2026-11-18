import copy
import json
from pathlib import Path

import pytest
from PIL import Image,ImageDraw

from scenarios.heritage_study.material_views import material_reference,sheet_boxes,shot_view,frame_style_references
from scenarios.ink_drama.domain import UserError
from test_ink_demo import api,setup


def sheet(path,count=3):
    image=Image.new('RGB',(1000,500),'#f1ead9')
    draw=ImageDraw.Draw(image)
    # Unequal panels deliberately cross the equal-third crop at x=333.
    objects=[(15,120,385,380,'#b52020'),(415,150,610,370,'#208520'),(650,105,980,395,'#2045b5')]
    if count==4:objects=[(20+i*250,120,210+i*250,380,color) for i,color in enumerate(('red','green','blue','black'))]
    if count==1:objects=[(100,100,900,400,'#b52020')]
    for left,top,right,bottom,color in objects:
        draw.polygon([(left,top+60),((left+right)//2,top),(right,top+60)],fill=color,outline='black',width=3)
        draw.rectangle((left+15,top+60,right-15,bottom-15),fill=color,outline='black',width=3)
        draw.rectangle((left,bottom-15,right,bottom),fill=color,outline='black',width=3)
    image.save(path)
    return objects


def configured(setup,monkeypatch):
    store,client=setup
    p=store.create('alice','研学视角','大殿历史旁白')
    sheet(store.folder(p['id'])/'sheet.png')
    Image.new('RGB',(1280,720),'white').save(store.folder(p['id'])/'original-frame.png')
    data=dict(characters=[],scenes=[dict(id='hall',name='大殿',desc='完整木构建筑',image='sheet.png')],props=[],style='工笔淡彩')
    p.update(project_type='heritage',characters=[],creative_settings=data,shots=[dict(id='s1',duration=5,
        content='正面檐下额位居中，周围带出相邻木构',scene='大殿',scene_id='hall',camera='中近景，正面平视',motion='固定机位',
        character_ids=[],prop_ids=[],dialogues=[],image='original-frame.png',image_stale=False,image_versions=['original-frame.png'],
        revision=1,clip=None,rendered=None,clip_stale=False,rendered_stale=False)],
        setting_generation_records={'sheet.png':dict(style='工笔淡彩',heritage_reference=dict(layout='panoramic-three-view'))})
    store.save(p)
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    return store,client,p


@pytest.mark.parametrize('camera,content,view',[
    ('全景，正面平视','侧面带出柱列','front'),('全景，严格90度侧面','正面大殿','side'),
    ('全景，45度斜侧','建筑外观','oblique'),('中近景','正面额位','front'),('全景','','front')])
def test_camera_angle_selects_one_view_before_content(camera,content,view):
    assert shot_view(dict(camera=camera,content=content))==view


def test_unequal_three_view_sheet_is_split_without_cutting_or_combining_subjects(tmp_path):
    path=tmp_path/'sheet.png';objects=sheet(path)
    with Image.open(path) as image:boxes=sheet_boxes(image)
    for view,obj in zip(('front','side','oblique'),objects):
        left,top,right,bottom=boxes[view]
        assert left<=obj[0]+2 and top<=obj[1]+2 and right>=obj[2]-2 and bottom>=obj[3]-2
    assert boxes['front'][2]>385 and boxes['front'][2]<415
    assert boxes['side'][0]>385 and boxes['side'][2]<650


@pytest.mark.parametrize('count',[1,4])
def test_ambiguous_or_extra_views_are_rejected_instead_of_sent_whole(tmp_path,count):
    path=tmp_path/'sheet.png';sheet(path,count=count)
    with Image.open(path) as image:
        with pytest.raises(UserError,match='视角|分隔'):sheet_boxes(image)


def color_counts(path):
    with Image.open(path) as image:
        data=image.convert('RGB').tobytes()
        channels=(data[::3],data[1::3],data[2::3])
        # Ignore near-black resampling fringes; test actual coloured subjects.
        return (sum(r>80 and r>g*1.4 and r>b*1.4 for r,g,b in zip(*channels)),
                sum(g>80 and g>r*1.4 and g>b*1.4 for r,g,b in zip(*channels)),
                sum(b>80 and b>r*1.4 and b>g*1.4 for r,g,b in zip(*channels)))


def test_selected_view_is_full_framed_and_cache_provenance_tracks_source_bytes(setup,monkeypatch):
    store,_,p=configured(setup,monkeypatch)
    item=p['creative_settings']['scenes'][0];original=store.asset(p['id'],'sheet.png').read_bytes()
    before=copy.deepcopy(p)
    wide={**p['shots'][0],'camera':'全景，正面平视'}
    front=Path(material_reference(p,wide,item,store))
    counts=color_counts(front)
    assert counts[0]>1000 and counts[1]==counts[2]==0
    with Image.open(front) as image:assert image.size==(1280,720)
    record=json.loads(front.with_suffix('.json').read_text())
    assert record['view']=='front' and record['source_image']=='sheet.png'
    assert material_reference(p,wide,item,store)==str(front)
    side=material_reference(p,dict(camera='侧面'),item,store)
    counts=color_counts(side);assert counts[1]>1000 and counts[0]==counts[2]==0
    assert store.asset(p['id'],'sheet.png').read_bytes()==original and p==before
    # Same filename with different bytes must never reuse a previous derived view.
    with Image.open(store.asset(p['id'],'sheet.png')) as image:
        changed=image.copy();changed.putpixel((0,0),(240,230,220));changed.save(store.asset(p['id'],'sheet.png'))
    assert material_reference(p,wide,item,store)!=str(front)


def test_unknown_single_view_uploads_and_ordinary_ink_keep_original_references(setup,monkeypatch):
    store,_,p=configured(setup,monkeypatch);item=p['creative_settings']['scenes'][0]
    ordinary={**p,'project_type':'ink'}
    assert material_reference(ordinary,p['shots'][0],item,store)==str(store.asset(p['id'],'sheet.png'))
    uploaded={**item,'image':'single-upload.png'}
    assert material_reference(p,p['shots'][0],uploaded,store)==str(store.asset(p['id'],'single-upload.png'))


@pytest.mark.parametrize('layout',['panoramic-single-view','component-single-view'])
def test_new_single_materials_are_used_whole_without_sheet_splitting_or_extra_style_subjects(setup,monkeypatch,layout):
    store,_,p=configured(setup,monkeypatch)
    p['setting_generation_records']['original-frame.png']=dict(style='工笔淡彩',heritage_reference=dict(layout=layout))
    item={**p['creative_settings']['scenes'][0],'image':'original-frame.png'}
    def unexpected(*args,**kwargs):pytest.fail('Single-view materials need neither sheet splitting nor an extra subject-bearing sample')
    monkeypatch.setattr('scenarios.heritage_study.material_views.sheet_boxes',unexpected)
    reference=material_reference(p,{**p['shots'][0],'camera':'全景'},item,store)
    assert reference==str(store.asset(p['id'],'original-frame.png'))
    prompt,refs=frame_style_references(p,'单张画面',[reference],unexpected)
    assert refs==[reference] and '本镜主体参考' in prompt


@pytest.mark.parametrize('candidate',[False,True])
def test_direct_and_candidate_generation_send_a_single_view_not_the_full_sheet(setup,monkeypatch,candidate):
    store,client,p=configured(setup,monkeypatch);base=f'/api/ink/projects/{p["id"]}'
    original=store.asset(p['id'],'original-frame.png').read_bytes()
    seen=[]
    def image(prompt,refs,folder,pid,ratio='9:16'):
        seen.extend(refs)
        assert len(refs)==1
        assert Path(refs[0]).name.startswith('frame-focus-')
        assert 'sheet.png' not in [Path(path).name for path in refs]
        assert color_counts(refs[0])[1:]==(0,0)
        assert '本镜是局部取景' in prompt and '不补回整栋建筑' in prompt
        assert '中近景' in prompt and '额位' in prompt
        result=folder/'simulated.png';Image.new('RGB',(1280,720),'white').save(result);return result
    monkeypatch.setattr(api.providers,'image',image)
    if candidate:
        fields={key:p['shots'][0].get(key) for key in api.ShotInput.model_fields}
        response=client.post(base+'/shots/s1/preview',json=dict(mode='redesign',instruction='',shot=fields))
    else:response=client.post(base+'/actions/image?sid=s1')
    assert response.status_code==200,response.text
    result=client.get(base).json()
    assert result['jobs'][0]['state']=='completed',result['jobs'][0]
    assert seen
    if candidate:
        assert result['shots'][0]['image']=='original-frame.png'
        assert result['shots'][0]['image_proposal']['reference_images'][0]==Path(seen[0]).name
    else:assert result['shots'][0]['image_reference_images'][0]==Path(seen[0]).name
    assert store.asset(p['id'],'original-frame.png').read_bytes()==original


def test_unseparable_sheet_stops_before_paid_generation_and_keeps_current_frame(setup,monkeypatch):
    store,client,p=configured(setup,monkeypatch);sheet(store.asset(p['id'],'sheet.png'),count=1)
    def unexpected(*args,**kwargs):pytest.fail('Ambiguous sheet must not reach an image provider')
    monkeypatch.setattr(api.providers,'image',unexpected)
    base=f'/api/ink/projects/{p["id"]}'
    assert client.post(base+'/actions/image?sid=s1').status_code==200
    result=client.get(base).json()
    assert result['jobs'][0]['state']=='failed' and '视角' in result['jobs'][0]['error']
    assert result['shots'][0]['image']=='original-frame.png'
    assert store.usage('alice').get('image',0)==0


def test_video_reference_mode_also_receives_only_the_selected_material_view(setup,monkeypatch):
    store,_,p=configured(setup,monkeypatch)
    monkeypatch.setattr(api,'check_frame_style',lambda *args:None)
    monkeypatch.setattr(api,'video_modes',lambda:[dict(id='reference',supported=True)])
    _,refs=api.video_inputs(p,p['shots'][0],'reference')
    assert len(refs)==1 and Path(refs[0]).name.startswith('frame-focus-')
    assert color_counts(refs[0])[1:]==(0,0)
