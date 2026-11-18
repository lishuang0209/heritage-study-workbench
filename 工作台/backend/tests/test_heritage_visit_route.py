import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from heritage_planner_fixtures import planner_reply
from scenarios.heritage_study.research_plan import analyze_research
from scenarios.heritage_study.storyboard import history_board
from scenarios.heritage_study.visit_route import route_for,interior_view
from scenarios.ink_drama.domain import UserError,frame_prompt
from test_heritage_frame_design import single_scene
from test_ink_demo import api,setup

MATERIAL='大殿保存了斗拱、柱子和木构。殿内前槽天花有三个镂空藻井。拼合柱与上部木构相接。'
WORDS='先介绍大殿历史。再讲寺院沿革。然后说重建年代。讲述木构价值。再看柱子。最后找斗拱。'
SETTINGS=dict(characters=[],scenes=[dict(id='hall',name='大殿',desc='完整外观')],props=[],style='工笔淡彩')


def analysis(material=MATERIAL):
    return analyze_research(WORDS,dict(material=material),planner_reply)


@pytest.mark.parametrize('count',[1,2,3,4,5,6,12,30])
def test_route_adapts_to_shot_count_and_never_returns_outside(count):
    route=route_for(count,analysis())
    assert len(route)==count and route[0]['stage']=='overview'
    assert route[-1]['stage']==('overview' if count==1 else 'detail')
    if count>=4:assert 'interior' in [stop['stage'] for stop in route]
    if count==6:assert [stop['stage'] for stop in route]==['overview','approach','entrance','interior','structure','detail']


def test_missing_internal_material_keeps_the_visit_at_entrance_and_visible_parts():
    external=analysis('大殿外观可见木构、柱子和斗拱。')
    assert 'interior' not in [stop['stage'] for stop in route_for(6,external)]


def test_route_and_source_evidence_survive_pipeline_without_rewriting_narration():
    prompts=[]
    def query(prompt):prompts.append(prompt);return planner_reply(prompt)
    result=history_board(WORDS,query,SETTINGS,30,research=dict(material=MATERIAL))
    visits=[s['study_visit'] for s in result['shots']]
    assert [v['stage'] for v in visits]==['overview','approach','entrance','interior','structure','detail']
    assert [v['space'] for v in visits]==['exterior','exterior','entrance','interior','interior','interior']
    assert ''.join(d['text'] for s in result['shots'] for d in s['dialogues'])==WORDS
    assert sum(s['duration'] for s in result['shots'])==30 and len(prompts)==2
    assert '而非按每句历史的关键词' in prompts[1] and 'interior_fact_ids' in prompts[1]
    assert all(s['character_ids']==[] for s in result['shots'])


@pytest.mark.parametrize('bad',['order','evidence','outside_again','wide_detail'])
def test_noncontinuous_or_ungrounded_route_is_rejected_without_more_model_calls(bad):
    calls=[]
    def query(prompt):
        calls.append(prompt);data=json.loads(planner_reply(prompt))
        if prompt.startswith('阶段2：'):
            if bad=='order':data['shots'][1]['visit_stage']='detail'
            if bad=='evidence':data['shots'][3]['fact_ids']=['f99']
            if bad=='outside_again':data['shots'][-1]['view_space']='exterior'
            if bad=='wide_detail':data['shots'][-1]['camera']='全景，平视'
        return json.dumps(data,ensure_ascii=False)
    with pytest.raises(UserError,match='原分镜已保留'):
        history_board(WORDS,query,SETTINGS,30,research=dict(material=MATERIAL))
    assert len(calls)==2


@pytest.mark.parametrize('candidate',[False,True])
def test_interior_generation_uses_research_instead_of_exterior_image_or_style_sample(setup,monkeypatch,candidate):
    store,client,p=single_scene(setup,monkeypatch);s=p['shots'][0]
    p['heritage_station']={'checked_description':MATERIAL}
    s.update(content='在殿内仰看前槽天花与三个镂空藻井',camera='中景，仰视内部顶部')
    store.save(p);original=s['image']
    def image(prompt,refs,folder,pid,**kwargs):
        assert refs==[]
        assert '内部空间原文依据' in prompt and '三个镂空藻井' in prompt
        assert '外立面全景放大充当室内' in prompt and '屋顶、殿身和基座' not in prompt
        target=folder/'result.png';Image.new('RGB',(1280,720),'white').save(target);return target
    monkeypatch.setattr(api.providers,'image',image)
    base=f'/api/ink/projects/{p["id"]}'
    if candidate:
        fields={key:s.get(key) for key in api.ShotInput.model_fields}
        response=client.post(base+'/shots/s1/preview',json=dict(mode='redesign',instruction='',shot=fields))
    else:response=client.post(base+'/actions/image?sid=s1')
    assert response.status_code==200,response.text
    saved=client.get(base).json()
    assert saved['jobs'][0]['state']=='completed',saved['jobs'][0]
    if candidate:assert saved['shots'][0]['image']==original
    assert store.asset(p['id'],original).is_file()


def test_missing_internal_research_stops_before_charging_and_keeps_original(setup,monkeypatch):
    store,client,p=single_scene(setup,monkeypatch)
    s=p['shots'][0];s.update(content='站在殿内看天花',camera='中景')
    store.save(p)
    monkeypatch.setattr(api.providers,'image',lambda *a,**k:pytest.fail('must not generate without internal evidence'))
    response=client.post(f'/api/ink/projects/{p["id"]}/actions/image?sid=s1')
    saved=client.get(f'/api/ink/projects/{p["id"]}').json()
    assert response.status_code==200 and saved['jobs'][0]['state']=='failed'
    assert '补充殿内资料' in saved['jobs'][0]['error']
    assert saved['shots'][0]['image']=='original-frame.png'


def test_inside_reference_video_uses_confirmed_inside_frame(setup,monkeypatch):
    store,_,p=single_scene(setup,monkeypatch);s=p['shots'][0]
    s.update(content='在殿内观察天花板',camera='中景')
    monkeypatch.setattr(api,'video_modes',lambda:[dict(id='reference',supported=True)])
    end,refs=api.video_inputs(p,s,'reference')
    assert end is None and refs==[str(store.asset(p['id'],s['image']))]
    assert 'single.png' not in [Path(ref).name for ref in refs]


def test_negated_internal_words_do_not_reframe_an_exterior_view():
    assert not interior_view(dict(content='大殿外观，不展示殿内天花',camera='全景'))
