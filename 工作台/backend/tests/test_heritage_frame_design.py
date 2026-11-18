import copy
import json
from pathlib import Path

import pytest
from PIL import Image,ImageDraw

from scenarios.heritage_study.frame_design import local_window
from scenarios.heritage_study.material_views import material_reference
from scenarios.ink_drama.domain import frame_prompt
from test_heritage_material_views import configured,color_counts
from test_ink_demo import api,setup


def single_scene(setup,monkeypatch):
    store,client,p=configured(setup,monkeypatch)
    image=Image.new('RGB',(1000,600),'#f1ead9');draw=ImageDraw.Draw(image)
    draw.rectangle((80,70,920,560),fill='#a89778',outline='black',width=4)
    draw.rectangle((80,70,920,120),fill='#b52020',outline='black',width=3)
    draw.rectangle((445,235,555,305),fill='#208520',outline='black',width=3)
    draw.rectangle((80,530,920,560),fill='#2045b5',outline='black',width=3)
    image.save(store.asset(p['id'],'single.png'))
    item=p['creative_settings']['scenes'][0]
    item.update(image='single.png',desc='依据研学资料呈现大殿的完整外观、建筑体量与整体布局。')
    p['setting_generation_records']['single.png']=dict(style='工笔淡彩',heritage_reference=dict(layout='panoramic-single-view'))
    store.save(p)
    return store,client,p


def test_local_and_wide_shots_of_the_same_scene_receive_different_visual_ranges(setup,monkeypatch):
    store,_,p=single_scene(setup,monkeypatch);item=p['creative_settings']['scenes'][0]
    original=store.asset(p['id'],'single.png').read_bytes();before=copy.deepcopy(p)
    close=p['shots'][0]
    wide={**close,'camera':'全景固定镜头','content':'完整的大殿外观，屋顶和台基入画'}
    local=Path(material_reference(p,close,item,store))
    full=Path(material_reference(p,wide,item,store))
    assert local.name.startswith('frame-focus-') and full.name=='single.png'
    red,green,blue=color_counts(local)
    assert green>1000 and red==blue==0  # Plaque area, not the whole roof/base.
    red,_,blue=color_counts(full);assert red>1000 and blue>1000
    record=json.loads(local.with_suffix('.json').read_text())
    assert record['method']=='composition-window-not-object-recognition'
    assert record['composition']['scale']=='中近景' and record['composition']['region']=='upper-middle'
    assert store.asset(p['id'],'single.png').read_bytes()==original and p==before


@pytest.mark.parametrize('camera,content,region',[
    ('近景','柱脚与台基的一角','lower'),('特写','屋脊顶部的一处轮廓','upper'),
    ('中近景','额位位于檐下，不展示台基和底部','upper-middle'),
    ('中景','柱列与檐下木构形成纵向关系','middle')])
def test_composition_cues_choose_a_broad_window_and_negative_clauses_do_not_move_it(camera,content,region):
    assert local_window(dict(camera=camera,content=content,character_ids=[]))['region']==region


def test_wide_and_actor_shots_do_not_get_a_local_architecture_crop():
    assert local_window(dict(camera='全景',content='檐下额位可见',character_ids=[])) is None
    assert local_window(dict(camera='近景',content='老师在檐下',character_ids=['c1'])) is None


def test_unmanned_prompt_prioritizes_shot_without_complete_asset_layout_or_actor_rules(setup,monkeypatch):
    _,_,p=single_scene(setup,monkeypatch);s=p['shots'][0]
    prompt=frame_prompt(p,s)
    assert s['content'] in prompt and '本镜是局部取景' in prompt
    assert '建筑顶部、完整立面和台基在画外' in prompt
    assert '完整外观、建筑体量与整体布局' not in prompt
    assert not any(word in prompt for word in ('发际线','发髻数量','递接或转身','人物位置按剧情阶段','已确认场景：'))
    assert prompt.count('本镜唯一画面任务')==1 and len(prompt)<1800
    p['creative_settings']['scenes'][0]['desc']='三间开敞木构，门窗为深褐色'
    assert '三间开敞木构，门窗为深褐色' in frame_prompt(p,s)
    wide={**s,'camera':'全景','content':'大殿完整外观'}
    assert '屋顶、殿身和基座' in frame_prompt(p,wide)


@pytest.mark.parametrize('candidate',[False,True])
def test_actual_api_uses_local_reference_for_close_shot_and_preserves_original_until_adoption(setup,monkeypatch,candidate):
    store,client,p=single_scene(setup,monkeypatch);base=f'/api/ink/projects/{p["id"]}'
    before=store.asset(p['id'],'original-frame.png').read_bytes()
    def image(prompt,refs,folder,pid,ratio='9:16'):
        assert len(refs)==1 and Path(refs[0]).name.startswith('frame-focus-')
        red,green,blue=color_counts(refs[0]);assert green>1000 and red==blue==0
        assert '完整外观、建筑体量与整体布局' not in prompt
        assert '本镜是局部取景' in prompt and '额位' in prompt
        result=folder/'result.png';Image.new('RGB',(1280,720),'white').save(result);return result
    monkeypatch.setattr(api.providers,'image',image)
    if candidate:
        fields={key:p['shots'][0].get(key) for key in api.ShotInput.model_fields}
        response=client.post(base+'/shots/s1/preview',json=dict(mode='redesign',instruction='',shot=fields))
    else:response=client.post(base+'/actions/image?sid=s1')
    assert response.status_code==200,response.text
    result=client.get(base).json()
    assert result['jobs'][0]['state']=='completed',result['jobs'][0]
    if candidate:assert result['shots'][0]['image']=='original-frame.png' and result['shots'][0]['image_proposal']
    assert store.asset(p['id'],'original-frame.png').read_bytes()==before
