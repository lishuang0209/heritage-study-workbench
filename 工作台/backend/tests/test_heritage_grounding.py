import copy
import json

from scenarios.heritage_study.storyboard import history_board, narration_nodes
from scenarios.heritage_study.visual_plan import visual_briefs, differentiated_content
from scenarios.heritage_study.workflow import planning_research
from scenarios.ink_drama.providers import Providers
from test_heritage_history import settings
from test_heritage_workflow import split_fresh
from test_ink_demo import api, setup
from heritage_planner_fixtures import planner_reply


NARRATION = ('宁波保国寺的前身是灵山寺。唐武宗会昌灭佛时,灵山寺被废;唐广明年间重建寺院,唐僖宗赐“保国”额。'
             '北宋大中祥符六年,即1013年,重建的大殿是全寺精粹。'
             '它全部结构用斗拱衔接,靠榫卯不用一钉;相关做法成为《营造法式》的实物例证,有的已是孤例,也是江南罕见的宋代木结构实物。'
             '今天我们先看斗拱。')


def test_imported_ascii_punctuation_does_not_turn_word_tails_into_history_shots():
    nodes = narration_nodes(NARRATION, 30)
    assert ''.join(nodes) == NARRATION
    assert '结构实物。' not in nodes
    assert any('木结构实物' in node for node in nodes)
    briefs = visual_briefs(nodes, settings())
    assert briefs[2]['role'] == 'construction'
    assert briefs[3]['role'] == 'joinery'
    assert briefs[-1]['role'] == 'observation'
    assert len(set(brief['camera'] for brief in briefs)) >= 5
    assert briefs[-1]['prop_ids'] == ['bracket']


def test_provider_passes_material_and_photo_limits_to_every_history_query_without_changing_narration(monkeypatch):
    from models.llm_client import LLM
    research = dict(material='资料测试：前槽天花有三个镂空藻井，拼合柱采用多片木料组合。',
                    instruction='沿照片框选的柱子向上观察。',
                    photos=[dict(slot='panorama',uploaded=True,note='未识别照片内容')])
    prompts = []
    def query(self, prompt, **kwargs):
        prompts.append(prompt)
        return planner_reply(prompt)
    monkeypatch.setattr(LLM, 'query', query)
    result = Providers().split(NARRATION,settings=settings(),planning=dict(
        kind='heritage-history',duration_seconds=45,narration=NARRATION,research=research))
    assert all('三个镂空藻井' in prompt and '拼合柱' in prompt and '未识别照片内容' in prompt for prompt in prompts)
    assert prompts[0].startswith('阶段1：') and prompts[1].startswith('阶段2：')
    assert ''.join(d['text'] for s in result['shots'] for d in s['dialogues']) == NARRATION
    assert not any('藻井' in d['text'] for s in result['shots'] for d in s['dialogues'])
    assert len(prompts) == 2  # Analysis + whole-film plan, with no hidden retries.
    assert len(set(s['content'] for s in result['shots'])) == len(result['shots'])
    assert sum(s['duration'] for s in result['shots']) == 45


def test_nonadjacent_repeated_visual_content_is_not_reused():
    briefs=visual_briefs(narration_nodes(NARRATION,30),settings())
    previous=[dict(content='A建筑全景'),dict(content='完全不同的木构连接局部')]
    result=differentiated_content(dict(content='A建筑全景'),briefs[2],previous)
    assert result == briefs[2]['content']


def test_research_context_uses_original_material_and_does_not_guess_photo_contents():
    p=dict(heritage_station=dict(building='测试建筑',component='斗拱',checked_description='完整导入资料\n资料来源：https://example.invalid',
                                instruction='沿柱向上看',question='哪层伸得远？',panorama=dict(image='photo.jpg',mark=dict(kind='rectangle',x=.1,y=.2,x2=.4,y2=.6))))
    before=copy.deepcopy(p)
    research=planning_research(p)
    assert research['material']==p['heritage_station']['checked_description']
    assert research['photos'][0]['mark']==p['heritage_station']['panorama']['mark']
    assert '未识别' in research['photos'][0]['note']
    research['photos'][0]['mark']['x']=.9
    assert p==before


def test_api_split_uses_saved_material_without_creating_settings_first(setup,monkeypatch):
    # Exercise the actual route -> provider -> prompt boundary using simulated AI.
    p,base=split_fresh(setup,monkeypatch)
    store,client=setup
    captured=[]
    original=api.providers.split
    def split(script,**kwargs):
        captured.append(copy.deepcopy(kwargs.get('planning')))
        return original(script,**kwargs)
    monkeypatch.setattr(api.providers,'split',split)
    response=client.post(base+'/actions/split')
    assert response.status_code==200,response.text
    current=client.get(base).json()
    assert current['jobs'][0]['state']=='completed',current['jobs'][0]
    research=captured[0]['research']
    assert research['material']==p['heritage_station']['checked_description']
    assert research['component']=='斗拱' and research['photos'][0]['uploaded']
    assert not current.get('creative_settings')
    assert current['storyboard_draft']['storyboard_engine']=='heritage-visit-route-v4'
