"""Exercise source grounding and whole-film planning without paid requests."""
import copy
import json

import pytest

from heritage_planner_fixtures import planner_reply
from scenarios.heritage_study.research_plan import analyze_research
from scenarios.heritage_study.storyboard import history_board
from scenarios.ink_drama.domain import UserError
from test_ink_demo import api, setup
from test_heritage_study import clean, picture
from test_heritage_workflow import split_fresh


WORDS = '保国寺大殿保存了木构。斗拱由层叠构件相接。柱子承接上方梁架。今天观察大殿。再看斗拱。最后沿柱子寻找。'
RESEARCH = dict(material='保国寺大殿保存木构，斗拱与梁架连接，柱子支承上部。', instruction='沿柱子向上找斗拱。')
SETTINGS = dict(characters=[], scenes=[dict(id='hall', name='大殿', desc='木构')],
                props=[dict(id='bracket', name='斗拱', desc='木构件')], style='工笔淡彩')


def generate(change=None):
    calls=[]
    def query(prompt):
        calls.append(prompt)
        data=json.loads(planner_reply(prompt))
        if change: change(prompt,data)
        return json.dumps(data,ensure_ascii=False)
    return history_board(WORDS,query,SETTINGS,30,research=RESEARCH),calls


def test_all_phases_see_saved_research_and_each_shot_has_original_evidence():
    result,calls=generate()
    assert len(calls)==2
    assert all(RESEARCH['material'] in prompt for prompt in calls)
    assert ''.join(d['text'] for shot in result['shots'] for d in shot['dialogues'])==WORDS
    assert len({shot['content'] for shot in result['shots']})==len(result['shots'])
    assert len({s['focus_element'] for s in result['storyboard_visual_plan']})>=3
    for shot in result['shots']:
        assert shot['study_topic'] and shot['research_evidence']
        for fact in shot['research_evidence']:
            source=dict(material=RESEARCH['material'],narration=WORDS,instruction=RESEARCH['instruction'])[fact['source']]
            assert fact['quote'] in source


@pytest.mark.parametrize('invalid',['quote','duplicate'])
def test_invented_analysis_stops_before_planning_or_refinement(invalid):
    calls=[]
    def query(prompt):
        calls.append(prompt)
        result=json.loads(planner_reply(prompt))
        if invalid=='quote': result['facts'][0]['quote']='未提供的地宫存在彩绘龙纹'
        else: result['facts'][1]['id']=result['facts'][0]['id']
        return json.dumps(result,ensure_ascii=False)
    with pytest.raises(UserError,match='原分镜已保留'):
        history_board(WORDS,query,SETTINGS,30,research=RESEARCH)
    assert len(calls)==1


def test_one_unverifiable_label_does_not_discard_valid_research_or_add_model_calls():
    def change(prompt,data):
        if prompt.startswith('阶段1：'):
            data['facts'][0]['elements'].append('未提供的彩绘龙纹')
    result,calls=generate(change)
    assert len(calls)==2
    assert all('彩绘龙纹' not in str(fact['elements']) for fact in result['storyboard_analysis']['facts'])
    assert len({item['focus_element'] for item in result['storyboard_visual_plan']})>=3


def test_all_unverifiable_labels_stop_with_a_model_extraction_error():
    calls=[]
    def query(prompt):
        calls.append(prompt)
        data=json.loads(planner_reply(prompt))
        for fact in data['facts']: fact['elements']=['未提供的彩绘龙纹']
        return json.dumps(data,ensure_ascii=False)
    with pytest.raises(UserError,match='模型未能提取.*尚未进入画面规划'):
        history_board(WORDS,query,SETTINGS,30,research=RESEARCH)
    assert len(calls)==1


def test_single_character_structural_names_can_complete_the_entire_pipeline():
    material='斗承接拱，梁连着柱。'
    def query(prompt):
        if prompt.startswith('阶段1：'):
            return json.dumps(dict(facts=[dict(id=f'f{i+1}',source='material',quote=material,elements=[term])
                                         for i,term in enumerate(('斗','拱','梁','柱'))]),ensure_ascii=False)
        return planner_reply(prompt)
    result=history_board('先看斗。再看拱。再看梁。最后找柱。',query,SETTINGS,12,research=dict(material=material))
    assert {item['focus_element'] for item in result['storyboard_visual_plan']}=={'斗','拱','梁','柱'}
    assert sum(shot['duration'] for shot in result['shots'])==12


def test_presentation_suffixes_are_removed_only_when_the_remaining_name_is_literal():
    material='斗拱和藻井保存完好。'
    response=dict(facts=[dict(id='f1',source='material',quote=material,
                             elements=['“斗拱结构”','藻井的细节','斗拱','彩绘龙纹特写'])])
    result=analyze_research('观察斗拱。',dict(material=material),lambda _:json.dumps(response,ensure_ascii=False))
    assert result['facts'][0]['elements']==['斗拱','藻井']
    assert result['facts'][0]['quote']==material


def test_a_real_name_outside_its_quote_gets_its_own_verbatim_source_evidence():
    material='大殿重建于1013年。前槽安置三个镂空藻井。'
    response=dict(facts=[dict(id='f1',source='material',quote='大殿重建于1013年。',elements=['镂空藻井'])])
    result=analyze_research('看大殿。',dict(material=material),lambda _:json.dumps(response,ensure_ascii=False))
    assert result['facts'][0]['quote']=='大殿重建于1013年。' and result['facts'][0]['elements']==[]
    visual=next(fact for fact in result['facts'] if fact['elements'])
    assert visual['elements']==['镂空藻井']
    assert visual['quote'] in material and '镂空藻井' in visual['quote']
    assert visual['id']!='f1'


def test_event_only_facts_and_fullwidth_names_are_accepted_without_guessing_synonyms():
    material='1013年重建。殿内有斗拱与木架。'
    response=dict(facts=[dict(id='f1',source='material',quote='1013年重建。',elements=[]),
                         dict(id='f2',source='material',quote='殿内有斗拱与木架。',elements=[' 斗 拱 ','梁架'])])
    result=analyze_research('观察木架。',dict(material=material),lambda _:json.dumps(response,ensure_ascii=False))
    assert result['facts'][0]['elements']==[]
    assert result['facts'][1]['elements']==['斗拱']


def test_a_name_found_only_in_a_source_url_is_not_accepted_as_a_visual_element():
    material='大殿重建于1013年。\n资料来源：https://example.invalid/DragonHall'
    response=dict(facts=[dict(id='f1',source='material',quote='大殿重建于1013年。',elements=['DragonHall'])])
    with pytest.raises(UserError,match='模型未能提取'):
        analyze_research('观察大殿。',dict(material=material),lambda _:json.dumps(response,ensure_ascii=False))


def test_rebinding_evidence_preserves_bounded_unique_fact_ids_at_full_capacity():
    material='1013年重建。殿内有藻井与拼合柱。'
    response=dict(facts=[dict(id=f'f{i+1}',source='material',quote='1013年重建。',elements=['藻井','拼合柱'])
                         for i in range(30)])
    result=analyze_research('观察构件。',dict(material=material),lambda _:json.dumps(response,ensure_ascii=False))
    assert len(result['facts'])<=30
    assert len({fact['id'] for fact in result['facts']})==len(result['facts'])
    assert {element for fact in result['facts'] for element in fact['elements']}=={'藻井','拼合柱'}
    assert all(fact['quote'] in material for fact in result['facts'])


@pytest.mark.parametrize('invalid',['fact','scene','props','indices','repeated','single_focus','all_wide'])
def test_invalid_or_repetitive_global_plan_does_not_proceed_to_shot_calls(invalid):
    calls=[]
    def query(prompt):
        calls.append(prompt)
        result=json.loads(planner_reply(prompt))
        if prompt.startswith('阶段2：'):
            shots=result['shots']
            if invalid=='fact': shots[0]['fact_ids']=['f99']
            elif invalid=='scene': shots[0]['scene_id']='invented'
            elif invalid=='props': shots[0]['prop_ids']=['invented']
            elif invalid=='indices': shots[1]['index']=0
            elif invalid=='repeated': shots[1].update(copy.deepcopy(shots[0]),index=1)
            elif invalid=='single_focus':
                for shot in shots:
                    shot['visual']=shot['visual'].replace(shot['focus_element'],'大殿')
                    shot.update(focus_element='大殿',fact_ids=['f1'])
            elif invalid=='all_wide':
                for shot in shots: shot['camera']='固定机位，全景，平视'
        return json.dumps(result,ensure_ascii=False)
    with pytest.raises(UserError,match='原分镜已保留'):
        history_board(WORDS,query,SETTINGS,30,research=RESEARCH)
    assert len(calls)==2


@pytest.mark.parametrize('seconds',[18,30,60])
def test_whole_film_visuals_and_motion_need_only_two_calls_with_any_duration(seconds):
    calls=[];progress=[]
    def query(prompt):
        calls.append(prompt)
        data=json.loads(planner_reply(prompt))
        if prompt.startswith('阶段2：'):
            for shot in data['shots']: shot['motion']='固定机位，保持本镜可见连接关系。'
        return json.dumps(data,ensure_ascii=False)
    result=history_board(WORDS,query,SETTINGS,seconds,research=RESEARCH,
                         progress=lambda message,done,total:progress.append((message,done,total)))
    assert len(calls)==2
    assert [shot['content'] for shot in result['shots']]==[shot['visual'] for shot in result['storyboard_visual_plan']]
    assert all(shot['motion']==brief['motion'] for shot,brief in zip(result['shots'],result['storyboard_visual_plan']))
    assert any('推近' in shot['motion'] for shot in result['shots'])
    assert sum(shot['duration'] for shot in result['shots'])==seconds
    assert [done for _,done,_ in progress]==[0,1,2]
    assert '解析研学资料' in progress[0][0] and '画面与运镜' in progress[1][0] and '核对' in progress[2][0]


def test_new_material_changes_visual_elements_without_temple_keyword_template():
    material='石狮立在台基边，柱础与地面相接。观察石狮，再看柱础。'
    settings=copy.deepcopy(SETTINGS)
    settings['scenes'][0].update(name='文庙',desc='石构')
    settings['props']=[dict(id='stone',name='石狮',desc='石构件')]
    result=history_board('观察石狮。再看柱础。回到石狮。',planner_reply,settings,30,research=dict(material=material))
    assert {item['focus_element'] for item in result['storyboard_visual_plan']}=={'石狮','柱础'}
    assert not any('斗拱' in shot['content'] or '大殿' in shot['content'] for shot in result['shots'])


def test_existing_media_survives_reconstruction_and_stale_research_cannot_be_adopted(setup,monkeypatch):
    store,client=setup
    p,base=split_fresh(setup,monkeypatch)
    saved=store.load(p['id'])
    saved['shots'][0].update(image='kept.jpg',image_versions=['kept.jpg'],clip='kept.mp4',rendered='kept.mp4')
    store.asset(p['id'],'kept.jpg').write_bytes(picture())
    store.asset(p['id'],'kept.mp4').write_bytes(b'original video')
    store.save(saved)
    before=copy.deepcopy(saved['shots'])
    assert client.post(base+'/actions/split').status_code==200
    p=client.get(base).json()
    assert p['jobs'][0]['state']=='completed',p['jobs'][0]
    saved=store.load(p['id'])
    assert saved['shots']==before
    assert saved['storyboard_draft']['storyboard_analysis']['facts']
    assert saved['storyboard_draft']['heritage_story_research_stamp']
    station=clean(p['heritage_station'])
    station['checked_description']+='\n补充资料：柱子与梁架的连接可观察。'
    response=client.put(base+'/heritage/station',json=dict(version=p['heritage_version'],station=station))
    assert response.status_code==200,response.text
    # Narration is unchanged, but the source material has changed.
    assert store.load(p['id'])['script']==saved['script']
    response=client.post(base+'/storyboard-draft/adopt')
    assert response.status_code==409 and '研学资料' in response.json()['detail']
    assert store.load(p['id'])['shots']==before
    assert store.asset(p['id'],'kept.mp4').read_bytes()==b'original video'


def test_failed_reconstruction_retains_existing_shots_and_reports_specific_reason(setup,monkeypatch):
    from models.llm_client import LLM
    store,client=setup
    p,base=split_fresh(setup,monkeypatch)
    before=copy.deepcopy(store.load(p['id'])['shots'])
    def invented(self,prompt,**kwargs):
        data=json.loads(planner_reply(prompt))
        data['facts'][0]['quote']='未提供的佛像复原资料'
        return json.dumps(data,ensure_ascii=False)
    monkeypatch.setattr(LLM,'query',invented)
    assert client.post(base+'/actions/split').status_code==200
    p=client.get(base).json()
    assert p['jobs'][0]['state']=='failed'
    assert '原文没有的依据' in p['jobs'][0]['error']
    assert store.load(p['id'])['shots']==before
    assert not p.get('storyboard_draft')


def test_api_reconstruction_finishes_when_a_model_fact_contains_an_extra_unmatched_name(setup,monkeypatch):
    from models.llm_client import LLM
    store,client=setup
    p,base=split_fresh(setup,monkeypatch)
    before=copy.deepcopy(store.load(p['id'])['shots'])
    def mixed(self,prompt,**kwargs):
        data=json.loads(planner_reply(prompt))
        if prompt.startswith('阶段1：'):
            data['facts'][0]['elements'].append('未提供的彩绘龙纹')
        return json.dumps(data,ensure_ascii=False)
    monkeypatch.setattr(LLM,'query',mixed)
    assert client.post(base+'/actions/split').status_code==200
    p=client.get(base).json()
    assert p['jobs'][0]['state']=='completed',p['jobs'][0]
    assert p['storyboard_draft']['storyboard_engine']=='heritage-visit-route-v4'
    assert store.load(p['id'])['shots']==before
