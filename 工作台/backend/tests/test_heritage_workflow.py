import copy
import json

from test_ink_demo import api, setup
from heritage_planner_fixtures import planner_reply
from test_heritage_study import prepared, picture
from scenarios.heritage_study.workflow import planning_settings


def split_fresh(setup, monkeypatch):
    from models.llm_client import LLM
    store, client = setup
    p = prepared(setup)
    base = f'/api/ink/projects/{p["id"]}'
    assert client.post(base+'/confirm-story').status_code == 200
    class Immediate:
        def submit(self, fn, *args):
            fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(LLM, 'query', lambda self,prompt,**kwargs: planner_reply(prompt))
    response = client.post(base+'/actions/split')
    assert response.status_code == 200, response.text
    result = client.get(base).json()
    assert result['jobs'][0]['state'] == 'completed', result['jobs'][0]
    return result, base


def test_storyboard_can_be_generated_edited_and_confirmed_before_visual_settings(setup, monkeypatch):
    store, client = setup
    p, base = split_fresh(setup, monkeypatch)
    assert not p.get('creative_settings')
    assert p['creative_draft']['characters'] == []
    assert p['creative_draft']['props'][0]['name'] == '斗拱'
    assert p['heritage_setting_references']
    assert ''.join(d['text'] for s in p['shots'] for d in s['dialogues']) == p['script']
    shot = p['shots'][0]
    fields = {key: shot[key] for key in api.ShotInput.model_fields}
    fields['content'] += '，保留周边空间'
    response = client.patch(base+'/shots/'+shot['id'], json=fields)
    assert response.status_code == 200, response.text
    # Both manual insertion and saved-shot edits accept provisional references.
    response = client.post(base+'/shots', json={**fields, 'dialogues':[]})
    assert response.status_code == 200, response.text
    response = client.post(base+'/confirm-storyboard')
    assert response.status_code == 200, response.text
    p = response.json()
    assert p['storyboard_confirmed'] and not p.get('creative_settings')
    shot_ids = [s['id'] for s in p['shots']]
    data = copy.deepcopy(p['creative_draft'])
    response = client.put(base+'/creative-settings', json=data)
    assert response.status_code == 200, response.text
    p = response.json()
    assert p['storyboard_confirmed'] and p['creative_draft'] is None
    assert [s['id'] for s in p['shots']] == shot_ids
    assert p['creative_settings']['characters'] == []
    assert not p['baseline']['characters']


def test_reference_style_edits_preserve_storyboard_approval_and_original_assets(setup, monkeypatch):
    store, client = setup
    p, base = split_fresh(setup, monkeypatch)
    p = client.post(base+'/confirm-storyboard').json()
    p = client.put(base+'/creative-settings', json=p['creative_draft']).json()
    saved = store.load(p['id'])
    s = saved['shots'][0]
    s.update(image='old.jpg', image_versions=['old.jpg'], clip='old.mp4', rendered='old.mp4')
    store.asset(p['id'], 'old.jpg').write_bytes(picture())
    store.asset(p['id'], 'old.mp4').write_bytes(b'original clip')
    store.save(saved)
    data = copy.deepcopy(p['creative_settings']); data['style'] = '水墨风格 · 泼墨写意'
    response = client.put(base+'/creative-settings', json=data)
    assert response.status_code == 200, response.text
    p = response.json()
    assert p['storyboard_confirmed']
    assert p['shots'][0]['image_stale'] and p['shots'][0]['clip_stale']
    assert store.asset(p['id'], 'old.mp4').read_bytes() == b'original clip'
    # Material review cannot silently break shot references or erase used actors.
    data['scenes'] = [{**data['scenes'][0], 'id':'unrelated'}]
    before = store.load(p['id'])
    response = client.put(base+'/creative-settings', json=data)
    assert response.status_code == 422
    assert store.load(p['id']) == before


def test_stale_historical_narration_cannot_be_confirmed_as_current_board(setup, monkeypatch):
    store, client = setup
    p, base = split_fresh(setup, monkeypatch)
    p = store.load(p['id']); p['heritage_story_stale'] = True; store.save(p)
    response = client.post(base+'/confirm-storyboard')
    assert response.status_code == 422 and '重新生成分镜' in response.json()['detail']


def test_provisional_manifest_keeps_existing_cast_and_never_mutates_old_materials():
    p = dict(characters=[dict(id='c1',name='讲解老师',desc='灰衣')], heritage_station=dict(building='测试古建',component='斗拱'))
    before = copy.deepcopy(p)
    data = planning_settings(p)
    assert data['characters'][0]['id'] == 'c1'
    data['scenes'][0]['desc'] = 'changed'
    assert p == before


def test_manual_legacy_shot_gets_scene_binding_at_storyboard_confirmation(setup):
    store, client = setup
    p = prepared(setup); base = f'/api/ink/projects/{p["id"]}'
    fields = dict(duration=5,content='从殿内观察梁架',scene='大殿内部',camera='中景',motion='固定镜头',
                  character_ids=[],scene_id=None,prop_ids=[],dialogues=[])
    response = client.post(base+'/shots',json=fields)
    assert response.status_code == 200, response.text
    response = client.post(base+'/confirm-storyboard')
    assert response.status_code == 200, response.text
    p = response.json(); s = p['shots'][0]
    assert s['scene_id']
    assert any(item['id']==s['scene_id'] and item['name']=='大殿内部' for item in p['creative_draft']['scenes'])
    assert client.put(base+'/creative-settings',json=p['creative_draft']).json()['storyboard_confirmed']
