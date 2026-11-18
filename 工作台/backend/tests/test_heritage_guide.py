import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from heritage_planner_fixtures import planner_reply
from scenarios.heritage_study.guide import set_enabled,DESCRIPTION
from scenarios.heritage_study.storyboard import history_board
from scenarios.heritage_study.workflow import planning_settings,planning_research
from scenarios.ink_drama.creative import validate_settings
from scenarios.ink_drama.domain import UserError,frame_prompt
from scenarios.ink_drama.providers import Providers
from test_heritage_visit_route import WORDS,MATERIAL,SETTINGS
from test_ink_demo import api,setup


def routed_project(setup,monkeypatch):
    store,client=setup
    p=store.create('alice','保国寺',''+WORDS)
    p.update(history_board(WORDS,planner_reply,SETTINGS,30,research=dict(material=MATERIAL)))
    p.update(project_type='heritage',creative_settings=validate_settings(SETTINGS),story_confirmed=True,storyboard_confirmed=True,
             heritage_station=dict(building='保国寺大殿',checked_description=MATERIAL),heritage_timing=dict(intro=30,location=11,task=7))
    Image.new('RGB',(1280,720),'white').save(store.asset(p['id'],'old.png'))
    store.asset(p['id'],'old.mp4').write_bytes(b'original movie')
    p['shots'][0].update(image='old.png',image_versions=['old.png'],clip='old.mp4',rendered='old.mp4')
    store.save(p)
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    return store,client,p,f'/api/ink/projects/{p["id"]}'


def enabled_project(setup,monkeypatch,adopt=False):
    store,client,p,base=routed_project(setup,monkeypatch)
    response=client.put(base+'/heritage/guide',json=dict(enabled=True,version=0))
    assert response.status_code==200,response.text
    if adopt:
        response=client.post(base+'/storyboard-draft/adopt')
        assert response.status_code==200,response.text
    return store,client,response.json(),base


def test_enabling_guide_prepares_reviewable_draft_without_touching_script_or_old_media(setup,monkeypatch):
    store,client,p,base=routed_project(setup,monkeypatch);before=copy.deepcopy(p);usage=store.usage('alice')
    result=client.put(base+'/heritage/guide',json=dict(enabled=True,version=0))
    assert result.status_code==200,result.text
    saved=store.load(p['id']);draft=saved['storyboard_draft'];cid=saved['heritage_guide']['character_id']
    assert saved['shots']==before['shots'] and saved['script']==before['script']
    assert saved['characters']==[] and saved['creative_settings']==before['creative_settings']
    assert [s['character_ids'] for s in draft['shots']]==[[cid],[cid],[cid],[],[],[]]
    assert all('小木匠阿木' in s['content'] for s in draft['shots'][:3])
    assert all('小木匠阿木' not in s['content'] for s in draft['shots'][3:])
    assert all(d['character_id']=='narrator' for s in draft['shots'] for d in s['dialogues'])
    assert ''.join(d['text'] for s in draft['shots'] for d in s['dialogues'])==WORDS
    assert sum(s['duration'] for s in draft['shots'])==30
    assert store.asset(p['id'],'old.mp4').read_bytes()==b'original movie'
    assert all(not s.get('image') and not s.get('clip') for s in draft['shots'])
    assert store.usage('alice')==usage


def test_guide_draft_can_be_adopted_then_requires_a_reference_before_material_confirmation(setup,monkeypatch):
    store,client,p,base=enabled_project(setup,monkeypatch,True)
    cid=p['heritage_guide']['character_id']
    assert p['characters'][0]['id']==p['creative_settings']['characters'][0]['id']==cid
    assert p['storyboard_history'][-1]['shots'][0]['image']=='old.png'
    assert p['creative_draft']['characters'][0]['id']==cid
    response=client.post(base+'/confirm-storyboard');assert response.status_code==200,response.text
    p=response.json()
    response=client.put(base+'/creative-settings',json=p['creative_draft'])
    assert response.status_code==422 and '角色参考图' in response.json()['detail']
    data=copy.deepcopy(p['creative_draft']);data['characters'][0]['image']='guide.png'
    Image.new('RGB',(1280,720),'white').save(store.asset(p['id'],'guide.png'))
    response=client.put(base+'/creative-settings',json=data)
    assert response.status_code==200,response.text
    assert response.json()['storyboard_confirmed'] and response.json()['creative_draft'] is None


def test_switching_guide_off_restores_architectural_draft_without_deleting_old_work(setup,monkeypatch):
    store,client,p,base=enabled_project(setup,monkeypatch)
    before=store.load(p['id'])
    response=client.put(base+'/heritage/guide',json=dict(enabled=False,version=1))
    assert response.status_code==200,response.text
    saved=store.load(p['id']);draft=saved['storyboard_draft']
    assert not draft['characters'] and all(not s['character_ids'] for s in draft['shots'])
    assert [s['content'] for s in draft['shots']]==[s['content'] for s in before['shots']]
    assert [s['motion'] for s in draft['shots']]==[s['motion'] for s in before['shots']]
    assert saved['shots']==before['shots'] and saved['storyboard_draft_history']


def test_guide_choice_is_versioned_and_idempotent(setup,monkeypatch):
    store,client,p,base=enabled_project(setup,monkeypatch)
    before=store.load(p['id'])
    assert client.put(base+'/heritage/guide',json=dict(enabled=False,version=0)).status_code==409
    assert client.put(base+'/heritage/guide',json=dict(enabled=True,version=1)).status_code==200
    assert store.load(p['id'])==before


def test_guide_keeps_existing_cast_ids_and_refuses_to_replace_a_full_cast():
    p=dict(characters=[dict(id='c1',name='原角色',desc='保留')],heritage_station=dict(building='大殿'))
    assert set_enabled(p,True)
    assert p['heritage_guide']['character_id']=='c2'
    assert [c['id'] for c in planning_settings(p)['characters']]==['c1','c2']
    full=dict(characters=[dict(id=f'c{i}',name=f'角色{i}',desc='保留') for i in (1,2)],heritage_station=dict(building='大殿'))
    before=copy.deepcopy(full)
    with pytest.raises(UserError,match='两位角色'):set_enabled(full,True)
    assert full==before


def test_enabled_guide_keeps_ai_on_the_two_call_research_route(monkeypatch):
    from models.llm_client import LLM
    p=dict(project_type='heritage',characters=[],script=WORDS,heritage_station=dict(building='大殿',checked_description=MATERIAL))
    set_enabled(p,True);settings=planning_settings(p);prompts=[]
    def query(self,prompt,**kwargs):prompts.append(prompt);return planner_reply(prompt)
    monkeypatch.setattr(LLM,'query',query)
    result=Providers().split(WORDS,settings=settings,planning=dict(kind='heritage-history',narration=WORDS,duration_seconds=30,research=planning_research(p)))
    assert len(prompts)==2
    assert [s['character_ids'] for s in result['shots']]==[['c1'],['c1'],['c1'],[],[],[]]
    assert [s['study_visit']['stage'] for s in result['shots']]==['overview','approach','entrance','interior','structure','detail']
    assert '不是历史事实来源' in prompts[1]
    assert '小木匠阿木' not in json.dumps(result['storyboard_analysis'],ensure_ascii=False)
    assert result['creative_draft']['characters'][0]['desc']==DESCRIPTION


@pytest.mark.parametrize('bad',['missing_action','detail_person'])
def test_invalid_guide_actions_do_not_trigger_more_model_calls(bad):
    p=dict(characters=[],heritage_station=dict(building='大殿',checked_description=MATERIAL));set_enabled(p,True);prompts=[]
    def query(prompt):
        prompts.append(prompt);data=json.loads(planner_reply(prompt))
        if prompt.startswith('阶段2：'):
            if bad=='missing_action':data['shots'][0]['guide_action']=''
            else:data['shots'][-1]['guide_action']='走到构件前'
        return json.dumps(data,ensure_ascii=False)
    with pytest.raises(UserError,match='原分镜已保留'):
        history_board(WORDS,query,planning_settings(p),30,research=planning_research(p))
    assert len(prompts)==2


@pytest.mark.parametrize('candidate',[False,True])
def test_visible_guide_requires_reference_before_any_image_call(setup,monkeypatch,candidate):
    store,client,p,base=enabled_project(setup,monkeypatch,True);s=p['shots'][0]
    monkeypatch.setattr(api.providers,'image',lambda *args,**kwargs:pytest.fail('must not generate before reference'))
    before=store.usage('alice')
    if candidate:
        s['image']='old.png';raw=store.load(p['id']);raw['shots'][0]['image']='old.png';store.save(raw)
        response=client.post(base+f'/shots/{s["id"]}/preview',json=dict(mode='redesign',instruction='',shot={key:s.get(key) for key in api.ShotInput.model_fields}))
    else:response=client.post(base+f'/actions/image?sid={s["id"]}')
    assert response.status_code==200,response.text
    result=client.get(base).json();assert result['jobs'][0]['state']=='failed'
    assert '小向导参考图' in result['jobs'][0]['error'] and store.usage('alice')==before


def test_confirmed_guide_reference_is_used_and_closeups_stay_empty(setup,monkeypatch):
    store,client,p,base=enabled_project(setup,monkeypatch,True)
    raw=store.load(p['id']);actor=raw['creative_settings']['characters'][0];actor['image']='guide.png'
    Image.new('RGB',(1280,720),'white').save(store.asset(p['id'],'guide.png'));store.save(raw)
    s=raw['shots'][0]
    def image(prompt,refs,folder,pid,**kwargs):
        assert [Path(ref).name for ref in refs]==['guide.png']
        assert '小木匠阿木' in prompt and '人物数量严格为一' in prompt and '人物数量为零' not in prompt
        assert '发髻' in prompt and '现存研学资料' in prompt
        target=folder/'generated.png';Image.new('RGB',(1280,720),'white').save(target);return target
    monkeypatch.setattr(api.providers,'image',image)
    response=client.post(base+f'/actions/image?sid={s["id"]}');assert response.status_code==200
    assert client.get(base).json()['jobs'][0]['state']=='completed'
    detail=frame_prompt(raw,raw['shots'][-1])
    assert '人物数量为零' in detail and '本镜唯一出镜人物' not in detail


def test_guide_three_view_generation_has_no_unrelated_adult_identity_reference(setup,monkeypatch):
    store,client,p,base=enabled_project(setup,monkeypatch,True)
    def image(prompt,refs,folder,pid,**kwargs):
        assert refs==[] and '教学虚构小向导' in prompt and '约十二岁' in prompt
        assert '角色三视图' in prompt and '正面' in prompt and '严格背面' in prompt
        target=folder/'guide-sheet.png';Image.new('RGB',(1280,720),'white').save(target);return target
    monkeypatch.setattr(api.providers,'image',image)
    response=client.post(base+'/generate-setting-image',json=dict(settings=p['creative_draft'],group='characters',asset_id='c1',view='sheet'))
    assert response.status_code==200,response.text
    result=client.get(base).json();assert result['jobs'][0]['state']=='completed',result['jobs'][0]
    assert result['creative_draft']['characters'][0]['image']
    assert store.asset(p['id'],'old.mp4').read_bytes()==b'original movie'


def test_guide_shots_can_be_deleted_and_restored_before_reference_generation(setup,monkeypatch):
    _,client,p,base=enabled_project(setup,monkeypatch,True);s=p['shots'][0]
    response=client.request('DELETE',base+f'/shots/{s["id"]}',json={'revision':s['revision']})
    assert response.status_code==200,response.text
    deletion=response.json()['deleted_shots'][0]
    response=client.post(base+f'/deleted-shots/{deletion["id"]}/restore')
    assert response.status_code==200,response.text
    restored=next(shot for shot in response.json()['shots'] if shot['id']==s['id'])
    assert restored['character_ids']==s['character_ids'] and restored['content']==s['content']
