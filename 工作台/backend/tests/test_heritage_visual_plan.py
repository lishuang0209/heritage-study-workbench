import json

from scenarios.heritage_study.storyboard import history_board,narration_nodes
from scenarios.heritage_study.templates import CASES,script_from_station
from scenarios.heritage_study.visual_plan import visual_briefs
from scenarios.ink_drama.domain import framing_constraint
from test_heritage_history import settings
from test_ink_demo import api,setup


def narration():
    return script_from_station(CASES[0]['station'],dict(intro=45,location=10,task=5))['intro']


def test_visual_briefs_distinguish_repair_protection_and_observation_and_filter_refs():
    briefs=visual_briefs(narration_nodes(narration(),30),settings())
    assert [brief['role'] for brief in briefs]==['establish','origin','structure','repair','protection','observation']
    assert briefs[3]['camera'].startswith('特写') and briefs[3]['prop_ids']==['bracket']
    assert briefs[4]['camera'].startswith('全景') and briefs[4]['prop_ids']==[]
    assert briefs[5]['camera'].startswith('中景') and '定位' in briefs[5]['subject']
    assert all((a['subject'],a['camera'])!=(b['subject'],b['camera']) for a,b in zip(briefs,briefs[1:]))


def test_repeated_topic_alternates_composition_instead_of_repeating_second_variant():
    briefs=visual_briefs(['清代修缮。']*4,settings())
    assert all(a['camera']!=b['camera'] for a,b in zip(briefs,briefs[1:]))
    briefs=visual_briefs(['列入文物保护单位。']*4,settings())
    assert all(a['camera']!=b['camera'] for a,b in zip(briefs,briefs[1:]))


def test_history_design_sees_neighbors_and_corrects_repeated_model_closeups_without_extra_calls():
    prompts=[]
    def query(prompt):
        prompts.append(prompt)
        return json.dumps(dict(content='层叠斗拱的局部特写，木纹细节清楚',scene_id='temple',camera='中景偏全景',motion='缓缓推近斗拱',prop_ids=['undefined']))
    result=history_board(narration(),query,settings(),30)
    assert len(prompts)==len(result['shots'])==6
    assert '已完成的前镜' in prompts[4] and '全片画面分工' in prompts[4]
    assert 'repair' in prompts[4] and 'protection' in prompts[4]
    fourth,fifth,sixth=result['shots'][3:6]
    assert fourth['camera'].startswith('特写') and fifth['camera'].startswith('全景')
    assert fifth['prop_ids']==[] and '完整屋顶' in fifth['content']
    assert '缓缓推近斗拱' not in fifth['motion']
    assert sixth['content']!=fourth['content'] and sixth['camera'].startswith('中景')
    assert ''.join(line['text'] for shot in result['shots'] for line in shot['dialogues'])==narration()
    assert sum(shot['duration'] for shot in result['shots'])==30


def test_unmanned_wide_framing_has_architecture_rules_without_body_cropping():
    wide=framing_constraint(dict(character_ids=[],camera='全景，正面平视'))
    assert '屋顶、殿身和基座' in wide and '腰部' not in wide and '胸部' not in wide
    detail=framing_constraint(dict(character_ids=[],camera='特写，侧向仰视'))
    assert '连接边界' in detail and '完整建筑' not in detail
    actor=framing_constraint(dict(character_ids=['c1'],camera='中景'))
    assert '腰部以上' in actor


def test_wide_generated_shot_uses_scene_reference_and_no_component_image(setup):
    store,_=setup
    p=store.create('alice','保护全景','测试')
    data=settings();data['scenes'][0]['image']='scene.png';data['props'][0]['image']='bracket.png'
    p['creative_settings']=data
    refs=api.creative_refs(p,dict(character_ids=[],scene_id='temple',prop_ids=[],camera='全景',content='完整大殿'))
    assert [ref.rsplit('/',1)[-1] for ref in refs]==['scene.png']
