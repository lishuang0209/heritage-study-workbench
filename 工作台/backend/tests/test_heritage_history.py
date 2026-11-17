import copy
import json

import pytest

from scenarios.heritage_study.storyboard import history_board, narration_nodes, allocate_seconds
from scenarios.heritage_study.templates import CASES, research_material, script_from_station
from scenarios.ink_drama.domain import UserError
from scenarios.ink_drama.providers import Providers
from test_ink_demo import api, setup
from test_heritage_study import prepared


def settings():
    return dict(characters=[],scenes=[dict(id='temple',name='保国寺大殿',desc='现状可见木构')],props=[dict(id='bracket',name='斗拱',desc='木构件')],style='工笔淡彩')


def test_full_case_material_expands_with_time_instead_of_fixed_two_sentences():
    station=CASES[0]['station']
    short=script_from_station(station,dict(intro=12,location=11,task=5))
    detailed=script_from_station(station,dict(intro=60,location=11,task=5))
    assert detailed['intro']!=short['intro'] and len(detailed['intro'])>140
    assert all(word in detailed['intro'] for word in ('1013','灵山寺','营造技术','清代','1961','斗拱'))
    assert not any(word in detailed['intro'] for word in ('http','资料来源','现场核对'))
    assert len(detailed['intro'])<=240


def test_history_sections_accept_multiple_paragraphs_and_keep_sources_and_observations_out():
    material='历史背景：\n这里始建于宋代。\n建筑价值：保存传统木构。\n修缮沿革：清代曾经修缮。\n观察重点：沿柱子向上看。\n资料来源：博物馆\nhttps://example.invalid\n待老师核对：不要念这句'
    history,observation=research_material(material)
    assert history==['这里始建于宋代','保存传统木构','清代曾经修缮']
    assert observation==['沿柱子向上看']


@pytest.mark.parametrize('seconds',[3,12,45,60,180])
def test_narration_is_not_lost_and_durations_match_custom_budget(seconds):
    text=script_from_station(CASES[0]['station'],dict(intro=60,location=11,task=5))['intro']
    nodes=narration_nodes(text,seconds);durations=allocate_seconds(nodes,seconds)
    assert ''.join(nodes)==text
    assert sum(durations)==seconds and all(2<=duration<=15 for duration in durations)
    assert len(nodes)<=30


@pytest.mark.parametrize('seconds',[30,45])
def test_narration_only_history_ignores_hallucinated_character_ids_and_keeps_exact_words(seconds):
    text=script_from_station(CASES[0]['station'],dict(intro=45,location=11,task=5))['intro']
    prompts=[]
    def query(prompt):
        prompts.append(prompt)
        return json.dumps(dict(content='仅展示大殿梁架',scene_id='temple',camera='仰拍特写',motion='固定机位',prop_ids=['bracket'],
                               characters=[dict(id='c1',name='讲解员')],character_ids=['c1','undefined'],dialogues=[dict(character_id='c1',text='模型改写的错误旁白')]))
    result=history_board(text,query,settings(),seconds)
    assert len(result['shots'])>=4 and len(prompts)==len(result['shots'])
    assert result['characters']==[] and all(shot['character_ids']==[] for shot in result['shots'])
    assert ''.join(line['text'] for shot in result['shots'] for line in shot['dialogues'])==text
    assert all(line['character_id']=='narrator' for shot in result['shots'] for line in shot['dialogues'])
    assert sum(shot['duration'] for shot in result['shots'])==seconds


def test_provider_routes_authoritative_empty_cast_history_without_generic_story_planning(monkeypatch):
    from models.llm_client import LLM
    monkeypatch.setattr(LLM,'query',lambda self,*args,**kwargs:json.dumps(dict(content='建筑全景',scene_id='temple',camera='全景',motion='固定镜头',prop_ids=[])))
    result=Providers().split('保国寺大殿建于北宋。',settings=settings(),planning=dict(kind='heritage-history',duration_seconds=12,narration='保国寺大殿建于北宋。'))
    assert result['storyboard_engine']=='heritage-history-facts-v2'
    assert sum(s['duration'] for s in result['shots'])==12


def test_history_script_update_retains_old_assets_and_prevents_adopting_obsolete_draft(setup):
    store,client=setup;p=prepared(setup);base=f'/api/ink/projects/{p["id"]}'
    old=p['heritage_script']['intro'];raw=store.load(p['id'])
    raw['shots']=[dict(id='old',content='旧画面',rendered='kept.mp4')]
    raw['storyboard_draft']=dict(heritage_story_source=old,characters=[],shots=[])
    store.asset(p['id'],'kept.mp4').write_bytes(b'keep old video')
    store.save(raw)
    script={key:p['heritage_script'][key] for key in ('intro','location','task','version','station_version','timing_version')}
    script['intro']='保国寺大殿重建于1013年。它还保留了木构营造的线索。'
    response=client.put(base+'/heritage/script',json=script)
    assert response.status_code==200,response.text
    assert response.json()['heritage_story_stale']
    assert store.asset(p['id'],'kept.mp4').read_bytes()==b'keep old video'
    assert client.post(base+'/storyboard-draft/adopt').status_code==409
    from scenarios.heritage_study.media import export_video
    with pytest.raises(UserError,match='旧镜头已保留'):
        export_video(api,store.load(p['id']),{}, {},store.folder(p['id']),store.folder(p['id'])/'out.mp4')


@pytest.mark.parametrize('seconds',[30,45])
def test_api_split_keeps_old_shots_until_new_history_draft_is_adopted(setup,monkeypatch,seconds):
    from models.llm_client import LLM
    from scenarios.ink_drama.domain import board
    store,client=setup;p=prepared(setup)
    text=script_from_station(CASES[0]['station'],dict(intro=45,location=11,task=5))['intro']
    old=board(json.dumps(dict(characters=[],shots=[dict(duration=5,content='旧画面',scene='保国寺大殿',camera='全景',motion='固定镜头',character_ids=[],dialogues=[])])))['shots']
    p=store.load(p['id']);p.update(creative_settings=settings(),characters=[],shots=old,script=text,story_confirmed=True,
                                heritage_story_stale=True,heritage_timing=dict(intro=seconds,location=11,task=5))
    store.save(p)
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(LLM,'query',lambda self,*args,**kwargs:json.dumps(dict(content='建筑梁架',scene_id='temple',camera='全景',motion='固定镜头',prop_ids=[],character_ids=['undefined'])))
    base=f'/api/ink/projects/{p["id"]}'
    response=client.post(base+'/actions/split')
    assert response.status_code==200,response.text
    current=client.get(base).json()
    assert current['jobs'][0]['state']=='completed',current['jobs'][0]
    assert current['shots'][0]['content']=='旧画面'
    assert current['heritage_story_stale']
    draft=current['storyboard_draft']
    assert draft['heritage_story_source']==text and len(draft['shots'])>=4
    assert sum(shot['duration'] for shot in draft['shots'])==seconds
    assert all(not shot['character_ids'] for shot in draft['shots'])
    response=client.post(base+'/storyboard-draft/adopt')
    assert response.status_code==200,response.text
    assert not response.json()['heritage_story_stale']
    assert response.json()['storyboard_history'][-1]['shots'][0]['content']=='旧画面'
