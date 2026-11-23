import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scenarios.ink_drama.domain import Store, UserError, board, caption, frame_prompt
# Importing the API must never recover jobs in the developer's live data directory.
import os
import tempfile
from unittest.mock import patch
_import_data = tempfile.TemporaryDirectory(prefix='ink-test-import-')
with patch.dict(os.environ, {'SFA_INK_DATA_DIR': _import_data.name}):
    from scenarios.ink_drama import api


def example_board():
    return board(json.dumps({'characters': [{'id': 'c1', 'name': '书生', 'desc': '灰衣木簪'}],
       'shots': [dict(content=f'画面{i}', scene='山寺', camera='中景', motion='雨丝飘落', character_ids=['c1'], dialogues=[]) for i in range(4)]}))


def example_caption():
    return {'characters': [{'character_id': 'c1', 'desc': '灰衣木簪', 'visibility': 'clear', 'match_status': 'consistent'}],
      'scene': {'description': '山寺', 'light_direction': 'uncertain'},
      'camera': {'shot_size': '中景', 'angle': '平视', 'composition': '人物居中'},
      'ink_style': {'techniques': ['飞白', '没有宣纸纹理'], 'whitespace': '中', 'bleed_strength': '弱', 'paper_texture': '未见', 'palette': ['青灰冷调']},
      'uncertainties': []}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from config import Config
    # Generation is mocked in these tests; make preflight credentials deterministic.
    for name in ('ARK_API_KEY', 'DASHSCOPE_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.setattr(Config, name, 'test-image-key')
    store = Store(tmp_path)
    monkeypatch.setenv('SFA_INK_TRIAL_MODE', '1')
    monkeypatch.delenv('SFA_INK_SHARED_PROJECT_IDS', raising=False)
    monkeypatch.setattr(api, 'store', store)
    monkeypatch.setenv('SFA_INK_INVITES', json.dumps([
        {'token': 'alice-test', 'user': 'alice', 'limits': dict(text=2, vl=2, image=2, video=2, speech=2)},
        {'token': 'bob-test', 'user': 'bob', 'limits': dict(text=2, vl=2, image=2, video=2, speech=2)}]))
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    assert client.post('/api/ink/login', json={'token': 'alice-test'}).status_code == 200
    return store, client


def project(store, owner='alice'):
    p = store.create(owner, '山寺', '书生借伞')
    p.update(example_board())
    store.save(p)
    return p


def test_normalize_exact_tags_not_negation():
    data = caption(example_caption(), ['c1'])
    assert data['ink_style']['techniques'] == ['枯笔飞白']
    assert data['ink_style']['paper_texture'] == '未见'
    assert data['uncertainties']


def test_invalid_id_and_unclear_identity_not_inherited():
    data = example_caption()
    data['characters'][0]['visibility'] = 'unclear'
    assert caption(data, ['c1'])['characters'][0]['character_id'] is None


def test_empty_scene_does_not_add_snapshot_character():
    p = {'characters': [], 'baseline': {'characters': [{'character_id': 'c1', 'desc': '灰衣'}], 'ink_style': {}}}
    prompt = frame_prompt(p, dict(content='山寺', scene='山寺', camera='远景', character_ids=[]))
    assert '无人景物' in prompt
    assert '灰衣' not in prompt


def test_board_rejects_extra_character():
    data = example_board()
    # Board parsing only accepts provider fields, not persisted state.
    raw = {'characters': [{'id': 'c1', 'name': 'A', 'desc': 'A'}], 'shots': []}
    for shot in data['shots']:
        raw['shots'].append({k: shot[k] for k in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')})
    raw['shots'][0]['character_ids'] = ['c2']
    with pytest.raises(UserError):
        board(json.dumps(raw))


def test_auth_required_and_bad_origin(setup):
    _, client = setup
    assert client.post('/api/ink/projects', json={'title': 'x', 'script': 'x'}, headers={'origin': 'https://attacker.invalid'}).status_code == 403
    client.cookies.clear()
    assert client.get('/api/ink/projects').status_code == 401


def test_private_trial_project_is_hidden_from_other_invitees(setup):
    store, client = setup
    own = project(store)
    store.asset(own['id'], 'image.png').write_bytes(b'own fixture')
    other = project(store, 'bob')
    store.asset(other['id'], 'image.png').write_bytes(b'other fixture')
    own_url = f'/api/ink/projects/{own["id"]}'
    other_url = f'/api/ink/projects/{other["id"]}'

    assert [item['id'] for item in client.get('/api/ink/projects').json()['projects']] == [own['id']]
    assert client.get(own_url).status_code == 200
    assert client.get(own_url + '/assets/image.png').content == b'own fixture'
    assert client.get(other_url).status_code == 404
    assert client.get(other_url + '/assets/image.png').status_code == 404
    assert client.delete(other_url).status_code == 404
    assert client.post(other_url + '/clone').status_code == 404

    assert client.post('/api/ink/login', json={'token': 'bob-test'}).status_code == 200
    assert [item['id'] for item in client.get('/api/ink/projects').json()['projects']] == [other['id']]
    assert client.get(other_url + '/assets/image.png').content == b'other fixture'
    assert client.get(own_url + '/assets/image.png').status_code == 404


def test_source_readonly_clone_separate_files(setup, monkeypatch):
    store, client = setup
    source = project(store, 'bob')
    private = project(store, 'bob')
    monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', source['id'])
    (store.folder(source['id']) / 'image.png').write_bytes(b'fixture')
    assert [item['id'] for item in client.get('/api/ink/projects').json()['projects']] == [source['id']]
    assert client.get(f'/api/ink/projects/{source["id"]}').status_code == 200
    assert client.get(f'/api/ink/projects/{source["id"]}/assets/image.png').content == b'fixture'
    assert client.get(f'/api/ink/projects/{private["id"]}').status_code == 404
    body = {k: source['shots'][0][k] for k in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')}
    assert client.patch(f'/api/ink/projects/{source["id"]}/shots/s1', json=body).status_code == 403
    response = client.post(f'/api/ink/projects/{source["id"]}/clone')
    assert response.status_code == 200
    clone = response.json()
    assert clone['owner'] == 'alice'
    assert store.asset(clone['id'], 'image.png').read_bytes() == b'fixture'
    store.asset(clone['id'], 'image.png').write_bytes(b'changed')
    assert store.asset(source['id'], 'image.png').read_bytes() == b'fixture'


def test_single_edit_invalidates_only_dependent_outputs(setup):
    store, client = setup
    p = project(store)
    for s in p['shots']:
        s.update(image=s['id'] + '.png', clip=s['id'] + '.mp4', rendered=s['id'] + '-sound.mp4')
    p['final'] = 'final.mp4'
    p['baseline'] = {'version': 1, 'characters': [], 'ink_style': {}, 'reference_images': []}
    store.save(p)
    before = copy.deepcopy(p['shots'][1])
    body = {k: p['shots'][0][k] for k in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')}
    body['content'] = '只改第一个镜头'
    response = client.patch(f'/api/ink/projects/{p["id"]}/shots/s1', json=body)
    assert response.status_code == 200
    after = store.load(p['id'])
    assert after['shots'][0]['clip_stale'] and after['final_stale']
    assert after['shots'][1] == before
    assert after['baseline'] == p['baseline']
    assert after['shots'][0]['clip'] == 's1.mp4'


def test_caption_analysis_does_not_change_locked_baseline(setup, monkeypatch):
    store, _ = setup
    p = project(store)
    p['shots'][0]['image'] = 'x.png'
    p['baseline'] = {'version': 3, 'characters': [], 'ink_style': {}, 'reference_images': []}
    store.save(p)
    observed = caption(example_caption(), ['c1'])
    monkeypatch.setattr(api.providers, 'analyze', lambda *_: observed)
    user = {'id': 'alice', 'limits': {'vl': 1}}
    jid = store.enqueue(p['id'], 'alice', 'caption')
    api.run_job(jid, p['id'], user, 'caption', 's1')
    assert store.jobs(p['id'])[0]['state'] == 'completed'
    assert store.load(p['id'])['baseline'] == p['baseline']


def test_quota_zero_denies_and_failed_calls_remain_counted(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(UserError):
        store.reserve('alice', 'image', 'p', {'image': 0})
    cid = store.reserve('alice', 'image', 'p', {'image': 1})
    store.settle(cid, 'failed_or_unknown')
    with pytest.raises(UserError):
        store.reserve('alice', 'image', 'p', {'image': 1})


def test_recover_does_not_restart_calls(tmp_path):
    store = Store(tmp_path)
    p = project(store)
    jid = store.enqueue(p['id'], 'alice', 'video')
    store.recover()
    assert store.jobs(p['id'])[0]['state'] == 'interrupted'
    assert store.usage('alice') == {}


def test_path_escape_rejected(tmp_path):
    store = Store(tmp_path)
    p = project(store)
    with pytest.raises(UserError):
        store.asset(p['id'], '../ink.sqlite3')


def test_ended_trial_readonly_and_retention_preserves_copy(setup):
    store, client = setup
    p = project(store)
    cloned = store.clone(p['id'], 'bob')
    response = client.post('/api/ink/end-trial')
    assert response.status_code == 200
    ended = response.json()['ended']
    assert client.post('/api/ink/projects', json={'title': 'x', 'script': 'x'}).status_code == 403
    assert store.purge(now=ended + 7 * 86400 - 1) == []
    assert store.purge(now=ended + 7 * 86400 + 1) == [p['id']]
    assert store.load(cloned['id'])['owner'] == 'bob'


def test_audio_total_over_five_does_not_render(setup, monkeypatch):
    store, _ = setup
    p = project(store)
    p['shots'][0].update(clip='old.mp4', dialogues=[{'character_id': 'c1', 'text': '一句'}, {'character_id': 'c1', 'text': '二句'}])
    store.save(p)
    monkeypatch.setattr(api.providers, 'has_audio', lambda _: False)
    monkeypatch.setattr(api.providers, 'speak', lambda *_: None)
    monkeypatch.setattr(api.providers, 'duration', lambda _: 3.0)
    monkeypatch.setattr(api.providers, 'render', lambda *_: pytest.fail('overlong audio must not render'))
    jid = store.enqueue(p['id'], 'alice', 'sound')
    api.run_job(jid, p['id'], {'id': 'alice', 'limits': {'speech': 2}}, 'sound', 's1')
    assert '累计6秒' in store.jobs(p['id'])[0]['error']
    assert store.load(p['id'])['shots'][0]['clip'] == 'old.mp4'


def test_busy_project_rejects_edits(setup):
    store, client = setup
    p = project(store)
    store.enqueue(p['id'], 'alice', 'video')
    body = {k: p['shots'][0][k] for k in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')}
    assert client.patch(f'/api/ink/projects/{p["id"]}/shots/s1', json=body).status_code == 409


def test_complete_api_pipeline_with_explicit_fake_providers(setup, monkeypatch):
    """Fixture responses test wiring only; they are never exposed as real generations."""
    store, client = setup
    from PIL import Image
    class Immediate:
        def submit(self, fn, *args):
            fn(*args)
    class Fake:
        def split(self, script):
            return example_board()
        def image(self, prompt, refs, folder, pid):
            image = folder / 'fixture.png'
            Image.new('RGB', (90, 160), 'white').save(image)
            return image
        def analyze(self, image, p):
            return caption(example_caption(), ['c1'])
        def video(self, image, motion, target, project=None, duration_seconds=5):
            assert project is not None
            target.write_bytes(b'FAKE VIDEO - TEST ONLY')
        def duration(self, target):
            return 5.0
        def render(self, video, lines, folder, target, duration_seconds=5):
            target.write_bytes(b'FAKE RENDER - TEST ONLY')
        def assemble(self, clips, music, folder, target):
            assert len(clips) == 4
            target.write_bytes(b'FAKE FINAL - TEST ONLY')
    monkeypatch.setattr(api, 'providers', Fake())
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setenv('SFA_INK_INVITES', json.dumps([{'token': 'alice-test', 'user': 'alice', 'limits': dict(text=1, vl=1, image=4, video=4, speech=0)}]))
    created = client.post('/api/ink/projects', json={'title': '接口测试', 'script': '测试剧本'}).json()
    pid = created['id']
    base = f'/api/ink/projects/{pid}'
    assert client.post(base + '/actions/split').status_code == 200
    for sid in ['s1', 's2', 's3', 's4']:
        assert client.post(base + f'/actions/image?sid={sid}').status_code == 200
        if sid == 's1':
            assert client.post(base + '/actions/caption?sid=s1').status_code == 200
            p = client.get(base).json()
            assert client.post(base + '/baseline/s1', json=p['shots'][0]['candidate']).status_code == 200
        assert client.post(base + f'/actions/video?sid={sid}').status_code == 200
        completed = client.get(base).json()
        assert next(s for s in completed['shots'] if s['id'] == sid)['rendered_url']
    p = store.load(pid)
    track = store.folder(pid) / 'fixture-music.mp3'
    track.write_bytes(b'FAKE MUSIC - TEST ONLY')
    p.update(music=track.name, music_credit={'title': 'fixture', 'license': 'TEST ONLY'})
    store.save(p)
    assert client.post(base + '/actions/assemble').status_code == 200
    p = client.get(base).json()
    assert all(j['state'] == 'completed' for j in p['jobs'])
    assert p['final_url']
    assert client.get(p['final_url']).content == b'FAKE FINAL - TEST ONLY'
    assert store.usage('alice') == dict(text=1, vl=1, image=4, video=4)


def test_real_media_processing_without_provider_calls(tmp_path):
    """Generate local test signals, verify real FFmpeg mux/subtitles/music durations."""
    from scenarios.ink_drama.providers import Providers, checked_ffmpeg
    provider = Providers()
    video = tmp_path / 'fixture.mp4'
    audio = tmp_path / 'fixture.m4a'
    music = tmp_path / 'music.m4a'
    checked_ffmpeg(['-f', 'lavfi', '-i', 'color=c=white:s=180x320:r=24', '-t', '5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)])
    checked_ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '0.7', str(audio)])
    checked_ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000', '-t', '1', str(music)])
    assert 0.6 <= provider.duration(audio) <= 0.8
    rendered = tmp_path / 'rendered.mp4'
    provider.render(video, [('本地媒体测试', provider.duration(audio), audio)], tmp_path, rendered)
    assert abs(provider.duration(rendered) - 5) < 0.15
    assert provider.has_audio(rendered)
    final = tmp_path / 'final.mp4'
    provider.assemble([rendered] * 4, music, tmp_path, final)
    assert abs(provider.duration(final) - 20) < 0.2


def test_public_mode_blocks_original_api_and_local_login(setup, monkeypatch):
    _, client = setup
    from api.app import app
    monkeypatch.setenv('SFA_INK_PUBLIC', '1')
    public_client = TestClient(app)
    assert public_client.get('/api/config').status_code == 403
    assert public_client.get('/api/project/example/status').status_code == 403
    assert public_client.get('/code/private.png').status_code == 403
    assert public_client.get('/openapi.json').status_code == 403
    assert public_client.get('/api/ink/projects').status_code == 401
    assert public_client.post('/api/ink/login', json={'token': 'alice-test'}).status_code == 200
    assert public_client.get('/api/ink/projects').status_code == 200
    monkeypatch.setenv('SFA_INK_INVITES', '[]')
    assert public_client.post('/api/ink/login', json={'token': ''}).status_code == 401


def test_quota_reservation_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = Store(tmp_path)
    def reserve(_):
        try:
            store.reserve('alice', 'image', 'p', {'image': 1})
            return True
        except UserError:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(reserve, range(8))) == 1


def test_voice_change_invalidates_audio_only(setup):
    store, client = setup
    p = project(store)
    p['shots'][0].update(image='image.png', clip='clip.mp4', rendered='rendered.mp4',
                        dialogues=[{'character_id': 'c1', 'text': '一句'}])
    p['final'] = 'final.mp4'
    store.save(p)
    response = client.post(f'/api/ink/projects/{p["id"]}/voices', json={'voices': {'c1': 'zh-CN-XiaoxiaoNeural'}})
    assert response.status_code == 200
    after = store.load(p['id'])
    assert not after['shots'][0]['image_stale']
    assert not after['shots'][0]['clip_stale']
    assert after['shots'][0]['rendered_stale'] and after['final_stale']


def test_local_workspace_needs_no_login_and_ignores_trial_limits(setup, monkeypatch):
    store, client = setup
    monkeypatch.delenv('SFA_INK_TRIAL_MODE', raising=False)
    client.cookies.clear()
    assert client.get('/api/ink/mode').json() == {'trial_mode': False}
    me = client.get('/api/ink/me')
    assert me.status_code == 200 and me.json()['trial_mode'] is False
    store.end_trial('local')
    assert client.get('/api/ink/me').json()['ended'] is None
    created = client.post('/api/ink/projects', json={'title': '本地创作', 'script': '一场短戏'})
    assert created.status_code == 200
    user = api.identity(type('LocalRequest', (), {'headers': {}, 'cookies': {}, 'client': type('Peer', (), {'host': '127.0.0.1'})()})())
    assert api.call(user, 'image', created.json()['id'], lambda: 'fixture only') == 'fixture only'
    assert store.usage('local')['image'] == 1
    assert client.post('/api/ink/login', json={'token': ''}).status_code == 404
    assert client.post('/api/ink/end-trial').status_code == 404


def test_local_mode_does_not_hide_or_lock_expired_trial_projects(setup, monkeypatch):
    store, client = setup
    monkeypatch.setenv('SFA_INK_TRIAL_MODE', '0')
    client.cookies.clear()
    p = project(store, 'alice')
    with store.db() as db:
        db.execute('INSERT INTO trials VALUES(?,?)', ('alice', 1))
    assert client.get('/api/ink/projects').json()['projects'][0]['id'] == p['id']
    assert client.get(f'/api/ink/projects/{p["id"]}').status_code == 200
    body = {k: p['shots'][0][k] for k in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')}
    assert client.patch(f'/api/ink/projects/{p["id"]}/shots/s1', json=body).status_code == 200


def test_disabled_trial_cleanup_does_not_open_store(monkeypatch, capsys):
    from scenarios.ink_drama import cleanup
    monkeypatch.setenv('SFA_INK_TRIAL_MODE', '0')
    monkeypatch.setattr('sys.argv', ['cleanup', '--apply'])
    monkeypatch.setattr(cleanup, 'Store', lambda *_: pytest.fail('disabled cleanup must not open or purge data'))
    cleanup.main()
    assert '不执行到期清理' in capsys.readouterr().out


def test_ink_settings_local_only_redacted_and_hot_save(setup, monkeypatch):
    from config import Config, DEFAULT_CONFIG
    store, client = setup
    monkeypatch.setenv('SFA_INK_TRIAL_MODE', '0')
    values = copy.deepcopy(DEFAULT_CONFIG)
    values['api_providers']['deepseek']['api_key'] = 'test-old-secret'
    monkeypatch.setattr(Config, 'as_dict', classmethod(lambda cls: copy.deepcopy(values)))
    monkeypatch.setattr(Config, 'ENV_OVERRIDDEN_PATHS', [])
    saved = []
    def update(cls, patch):
        saved.append(copy.deepcopy(patch))
        for group in ('models', 'api_providers'):
            for key, value in patch[group].items():
                if isinstance(value, dict):
                    values[group][key].update(value)
                else:
                    values[group][key] = value
    monkeypatch.setattr(Config, 'update_config', classmethod(update))
    response = client.get('/api/ink/settings')
    assert response.status_code == 200
    assert 'test-old-secret' not in response.text
    assert response.json()['providers']['deepseek']['secrets']['api_key'] is True
    result = client.put('/api/ink/settings', json={'models': {'llm': 'deepseek-chat'}, 'providers': {'deepseek': {'api_key': 'test-new-secret'}}})
    assert result.status_code == 200
    assert result.json()['models']['llm'] == 'deepseek-chat'
    assert 'test-new-secret' not in result.text
    assert saved[-1]['api_providers']['deepseek']['api_key'] == 'test-new-secret'
    assert client.put('/api/ink/settings', json={'models': {'vlm': 'deepseek-chat'}}).status_code == 422
    assert client.put('/api/ink/settings', json={'providers': {'deepseek': {'base_url': 'https://user:secret@example.com/v1'}}}).status_code == 422
    assert client.put('/api/ink/settings', json={'server': {'host': '0.0.0.0'}}).status_code == 422
    assert client.get('/api/ink/settings', headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.put('/api/ink/settings', json={}, headers={'x-forwarded-for': '192.0.2.1'}).status_code == 403
    monkeypatch.setattr(Config, 'ENV_OVERRIDDEN_PATHS', ['models.llm'])
    assert client.put('/api/ink/settings', json={'models': {'llm': 'deepseek-chat'}}).status_code == 409
    p = store.create('local', '测试', '剧本')
    store.enqueue(p['id'], 'local', 'split')
    assert client.put('/api/ink/settings', json={}).status_code == 409
    monkeypatch.setenv('SFA_INK_TRIAL_MODE', '1')
    assert client.get('/api/ink/settings').status_code == 403


def test_reference_prepares_image_and_caption_and_supports_new_character(setup, monkeypatch):
    store, client = setup
    from PIL import Image
    p = project(store)
    p['characters'].append({'id': 'c2', 'name': '少女', 'desc': '青衣少女'})
    p['shots'][1]['character_ids'] = ['c2']
    store.save(p)
    prompts = []
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid):
        prompts.append(prompt)
        path = folder / 'test-reference.png'
        Image.new('RGB', (9, 16), 'white').save(path)
        return path
    def analyze(path, current):
        data = example_caption()
        if current['shots'][1].get('image') == path.name:
            data['characters'][0].update(character_id='c2', desc='青衣少女')
        return caption(data, ['c1', 'c2'])
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'image', image)
    monkeypatch.setattr(api.providers, 'analyze', analyze)
    base = f"/api/ink/projects/{p['id']}"
    assert client.post(base + '/actions/reference?sid=s1&preset=simple').status_code == 200
    result = client.get(base).json()
    assert result['jobs'][0]['state'] == 'completed'
    assert result['shots'][0]['image_url'] and result['shots'][0]['candidate']
    assert '简笔写意' in prompts[0]
    approved = result['shots'][0]['candidate']
    approved['characters'][0]['desc'] = '用户修正的外貌'
    result = client.post(base + '/baseline/s1', json=approved).json()
    assert result['shots'][0]['candidate']['characters'][0]['desc'] == '用户修正的外貌'
    assert client.post(base + '/actions/reference?sid=s2').status_code == 200
    result = client.get(base).json()
    assert result['jobs'][0]['state'] == 'completed'
    assert '青衣少女' in prompts[1]
    assert {c['character_id'] for c in result['baseline']['characters']} == {'c1'}
    result = client.post(base + '/baseline/s2', json=result['shots'][1]['candidate']).json()
    assert {c['character_id'] for c in result['baseline']['characters']} == {'c1', 'c2'}


def test_reference_keeps_paid_image_when_vision_fails(setup, monkeypatch):
    store, client = setup
    from PIL import Image
    p = project(store)
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid):
        path = folder / 'test-retained-image.png'
        Image.new('RGB', (9, 16), 'white').save(path)
        return path
    def fail(*_): raise UserError('读图服务暂不可用')
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'image', image)
    monkeypatch.setattr(api.providers, 'analyze', fail)
    base = f"/api/ink/projects/{p['id']}"
    assert client.post(base + '/actions/reference?sid=s1').status_code == 200
    result = client.get(base).json()
    assert result['jobs'][0]['state'] == 'failed'
    assert result['shots'][0]['image_url'] and not result['shots'][0]['candidate']
    assert client.get(result['shots'][0]['image_url']).status_code == 200
    assert len(result['shots'][0]['image_versions']) == 1


def test_final_can_be_assembled_without_background_music(setup, monkeypatch):
    store, client = setup
    p = project(store)
    for shot in p['shots']:
        shot['rendered'] = shot['id'] + '.mp4'
        (store.folder(p['id']) / shot['rendered']).write_bytes(b'test')
    p.update(music='old.mp3', music_credit={'title': 'old', 'license': 'test'})
    store.save(p)
    base = f"/api/ink/projects/{p['id']}"
    assert client.post(base + '/music', json={'id': ''}).json()['music_credit'] is None
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def assemble(clips, music, folder, target):
        assert music is None
        target.write_bytes(b'test final')
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'assemble', assemble)
    assert client.post(base + '/actions/assemble').status_code == 200
    result = client.get(base).json()
    assert result['jobs'][0]['state'] == 'completed'
    assert result['final_url']


def test_motion_edit_updates_image_prompt_and_invalidates_dependent_outputs(setup):
    store, client = setup
    p = project(store)
    s = p['shots'][0]
    s.update(image='old.png', clip='old.mp4', rendered='old-sound.mp4')
    p['final'] = 'final.mp4'
    store.save(p)
    other = copy.deepcopy(p['shots'][1])
    body = {k: s[k] for k in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')}
    body['motion'] = '少女双手握伞，面对书生'
    result = client.patch(f'/api/ink/projects/{p["id"]}/shots/s1', json=body)
    assert result.status_code == 200
    updated = store.load(p['id'])
    shot = updated['shots'][0]
    assert shot['image_stale'] and shot['clip_stale'] and shot['rendered_stale']
    assert updated['final_stale']
    assert shot['image'] == 'old.png'
    assert updated['shots'][1] == other
    assert body['motion'] not in frame_prompt(updated, shot)


def test_regenerate_uses_reference_and_complete_current_constraints(setup, monkeypatch):
    from PIL import Image
    store, client = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(image='current.png', content='旧画面单手持伞')
    p['baseline'] = {'version': 1, 'characters': [{'character_id': 'c1', 'desc': '旧姿势面朝右'}], 'reference_images': ['baseline.png'], 'ink_style': {}}
    for name in ('current.png', 'baseline.png'):
        Image.new('RGB', (9,16), 'white').save(store.folder(p['id']) / name)
    store.save(p)
    body = {k: shot[k] for k in ('content','scene','camera','motion','character_ids','dialogues')}
    body['motion'] = '双手持伞面向书生'
    base = f"/api/ink/projects/{p['id']}"
    assert client.patch(base+'/shots/s1', json=body).status_code == 200
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid):
        assert refs == [str(store.asset(pid, 'baseline.png'))]
        assert body['motion'] not in prompt
        assert '旧画面单手持伞' in prompt
        assert '场景：' + body['scene'] in prompt
        assert '镜头构图：' + body['camera'] in prompt
        assert '静态首帧（最高优先级）' in prompt
        path = folder / 'edited.png'
        Image.new('RGB', (9,16), 'blue').save(path)
        return path
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'image', image)
    assert client.post(base+'/actions/image?sid=s1').status_code == 200
    result = client.get(base).json()
    assert result['jobs'][0]['state'] == 'completed'
    assert result['shots'][0]['image'] != 'current.png'
    assert result['shots'][0]['pending_image_edits'] == []
    assert store.asset(p['id'], 'current.png').is_file()


def test_failed_edit_retains_current_image_and_pending_changes(setup, monkeypatch):
    store, client = setup
    p = project(store)
    p['shots'][0].update(image='current.png', pending_image_edits=['motion'])
    store.save(p)
    def fail(*args): raise UserError('test generation failure')
    monkeypatch.setattr(api.providers, 'image', fail)
    jid = store.enqueue(p['id'], 'alice', 'image')
    api.run_job(jid, p['id'], {'id':'alice', 'limits':{'image':2}}, 'image', 's1')
    result = store.load(p['id'])['shots'][0]
    assert result['image'] == 'current.png'
    assert result['pending_image_edits'] == ['motion']


@pytest.mark.parametrize('mode', ['detail', 'redesign', 'style'])
def test_preview_adoption_undo_and_discard(setup, monkeypatch, mode):
    from PIL import Image
    store, client = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(image='original.png', clip='old.mp4', rendered='sound.mp4')
    if mode == 'style':
        p['creative_settings'] = {'style': '泼墨写意', 'characters': p['characters'], 'scenes': [{'id': shot.get('scene_id')}], 'props': []}
    p['final'] = 'final.mp4'
    Image.new('RGB',(9,16),'white').save(store.folder(p['id'])/'original.png')
    store.save(p)
    before = copy.deepcopy(shot)
    draft = {k: copy.deepcopy(shot[k]) for k in api.ShotInput.model_fields}
    draft['motion'] = '转身递伞'
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid):
        if mode == 'style':
            assert refs[1] == str(store.asset(pid, 'original.png'))
            assert refs[0].endswith('/bold.png')
            assert len(refs) == 2
            assert '整幅换画法重绘' in prompt
        else:
            assert refs == ([str(store.asset(pid,'original.png'))] if mode == 'detail' else [])
        if mode != 'style':
            assert ('衣服浅青色' if mode == 'detail' else draft['content']) in prompt
        assert draft['motion'] not in prompt
        target = folder/'preview.png'
        Image.new('RGB',(9,16),'blue').save(target)
        return target
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'image',image)
    base = f"/api/ink/projects/{p['id']}/shots/s1"
    body = {'mode':mode,'shot':draft,'instruction':'衣服浅青色'}
    response = client.post(base+'/preview',json=body)
    assert response.status_code == 200
    data = response.json()
    assert data['jobs'][0]['state'] == 'completed'
    for k,v in before.items(): assert data['shots'][0][k] == v
    assert not data.get('final_stale')
    cid = data['shots'][0]['image_proposal']['id']
    assert data['shots'][0]['image_proposal']['image_url']
    assert client.post(base+'/adopt',json={'candidate_id':'wrong'}).status_code == 409
    adopted = client.post(base+'/adopt',json={'candidate_id':cid}).json()
    current = adopted['shots'][0]
    assert current['image'] != before['image']
    assert current['clip_stale'] and current['rendered_stale'] and adopted['final_stale']
    assert not current['image_proposal']
    if mode == 'detail': assert '衣服浅青色' in current['content']
    elif mode == 'style':
        assert current['motion'] == before['motion']
        assert current['content'] == before['content']
    else: assert current['motion'] == draft['motion']
    undone = client.post(base+'/undo-image',json={}).json()['shots'][0]
    for k in ('image','content','motion'): assert undone[k] == before[k]
    assert store.asset(p['id'],'original.png').is_file()
    second = client.post(base+'/preview',json=body).json()['shots'][0]['image_proposal']
    assert client.post(base+'/discard',json={'candidate_id':second['id']}).status_code == 200
    assert store.load(p['id'])['shots'][0]['image'] == before['image']


def test_preview_failure_keeps_draft_and_original(setup, monkeypatch):
    store, client = setup
    p = project(store)
    before = copy.deepcopy(p['shots'][0])
    draft = {k: before[k] for k in api.ShotInput.model_fields}
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def fail(*args): raise UserError('模拟失败')
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'image',fail)
    base = f"/api/ink/projects/{p['id']}/shots/s1"
    data = client.post(base+'/preview',json={'mode':'redesign','shot':draft}).json()
    assert data['jobs'][0]['state'] == 'failed'
    for k,v in before.items(): assert data['shots'][0][k] == v
    assert data['shots'][0]['image_draft']['shot'] == draft


def test_stale_preview_cannot_be_adopted(setup):
    store, client = setup
    p = project(store)
    p['shots'][0]['image_proposal'] = {'id':'test','image':'preview.png','stamp':[999,None,None]}
    store.save(p)
    base = f"/api/ink/projects/{p['id']}/shots/s1"
    assert client.post(base+'/adopt',json={'candidate_id':'test'}).status_code == 409
    assert client.post(base+'/discard',json={'candidate_id':'test'}).status_code == 200


def test_history_keeps_discarded_candidate_and_restores_snapshot(setup):
    from PIL import Image
    store, client = setup
    p = project(store)
    s = p['shots'][0]
    s.update(image='original.png', clip='old.mp4')
    original_content = s['content']
    snapshot = {k: copy.deepcopy(s[k]) for k in api.ShotInput.model_fields}
    snapshot['content'] = '候选画面描述'
    s['image_proposal'] = dict(id='proposal',image='candidate.png',shot=snapshot,prompt='test',mode='redesign',stamp=api.proposal_stamp(p,s))
    for name in ('original.png','candidate.png'):
        Image.new('RGB',(9,16),'white').save(store.folder(p['id'])/name)
    store.save(p)
    base=f"/api/ink/projects/{p['id']}/shots/s1"
    assert client.post(base+'/discard',json={'candidate_id':'proposal'}).status_code == 200
    entries=client.get(base+'/history').json()['images']
    candidate=next(e for e in entries if e['image']=='candidate.png')
    assert candidate['status']=='discarded' and candidate['has_snapshot']
    body={'image':'candidate.png','revision':s['revision'],'current_image':'original.png'}
    restored=client.post(base+'/restore-image',json=body)
    assert restored.status_code==200
    current=restored.json()['shots'][0]
    assert current['image']=='candidate.png' and current['content']=='候选画面描述'
    assert current['clip_stale']
    assert client.post(base+'/restore-image',json=body).status_code==409
    undone=client.post(base+'/undo-image',json={}).json()['shots'][0]
    assert undone['image']=='original.png' and undone['content']==original_content


def test_legacy_history_is_scoped_and_keeps_current_text(setup):
    from PIL import Image
    store, client = setup
    p=project(store)
    s=p['shots'][0]
    s['image_versions']=['legacy.png','legacy.png']
    p['shots'][1]['image_versions']=['other-shot.png']
    for name in ('legacy.png','other-shot.png'):
        Image.new('RGB',(9,16),'white').save(store.folder(p['id'])/name)
    store.save(p)
    base=f"/api/ink/projects/{p['id']}/shots/s1"
    entries=client.get(base+'/history').json()['images']
    assert len(entries)==1 and not entries[0]['has_snapshot']
    body={'revision':s['revision'],'current_image':None}
    assert client.post(base+'/restore-image',json={**body,'image':'other-shot.png'}).status_code==404
    assert client.post(base+'/restore-image',json={**body,'image':'../secret'}).status_code==404
    result=client.post(base+'/restore-image',json={**body,'image':'legacy.png'}).json()['shots'][0]
    assert result['content']==s['content'] and result['image']=='legacy.png'


def test_confirm_current_image_without_generation_preserves_downstream_staleness(setup, monkeypatch):
    from PIL import Image
    store, client=setup
    p=project(store)
    s=p['shots'][0]
    s.update(image='existing.png',image_stale=True,image_stale_reason='设定变化',clip='old.mp4',clip_stale=True,rendered_stale=True)
    p['final_stale']=True
    Image.new('RGB',(9,16),'white').save(store.folder(p['id'])/'existing.png')
    store.save(p)
    def no_call(*args): pytest.fail('confirmation must not generate')
    monkeypatch.setattr(api.providers,'image',no_call)
    base=f"/api/ink/projects/{p['id']}/shots/s1/confirm-image"
    assert client.post(base,json={'image':'other.png','revision':s['revision']}).status_code==409
    assert client.post(base,json={'image':'existing.png','revision':999}).status_code==409
    result=client.post(base,json={'image':'existing.png','revision':s['revision']})
    assert result.status_code==200
    current=result.json()['shots'][0]
    assert current['image']=='existing.png' and not current['image_stale']
    assert current['image_stale_reason'] is None
    assert current['clip_stale'] and current['rendered_stale'] and result.json()['final_stale']
    assert current['content']==s['content']


def creative_fixture():
    return {'characters':[{'id':'c1','name':'书生','desc':'灰衣木簪','image':None}],
            'scenes':[{'id':'scene1','name':'山寺','desc':'门洞左侧，石阶向下','image':None}],
            'props':[{'id':'prop1','name':'纸伞','desc':'竹骨黄纸伞','image':None}], 'style':'淡彩水墨'}


def test_confirm_settings_migrates_existing_images_and_invalidation_is_scoped(setup):
    store,client=setup
    p=project(store)
    for s in p['shots']: s.update(image=s['id']+'.png',clip='clip.mp4')
    store.save(p)
    base=f"/api/ink/projects/{p['id']}"
    data=creative_fixture()
    saved=client.put(base+'/creative-settings',json=data)
    assert saved.status_code==200
    p=store.load(p['id'])
    assert all(not s['image_stale'] for s in p['shots'])
    assert all(s['scene_id']=='scene1' for s in p['shots'])
    p['shots'][0]['prop_ids']=['prop1']
    p['storyboard_confirmed']=True
    store.save(p)
    data['props'][0]['desc']='竹骨白纸伞'
    changed=client.put(base+'/creative-settings',json=data).json()
    assert changed['shots'][0]['image_stale']
    assert not changed['shots'][1]['image_stale']
    assert changed['shots'][0]['image']=='s1.png'
    assert not changed['storyboard_confirmed']
    version=changed['baseline']['version']
    same=client.put(base+'/creative-settings',json=data).json()
    assert same['baseline']['version']==version
    assert '白纸伞' in frame_prompt(store.load(p['id']),store.load(p['id'])['shots'][0])


def test_storyboard_confirmation_requires_valid_asset_links(setup):
    store,client=setup
    p=project(store)
    base=f"/api/ink/projects/{p['id']}"
    assert client.post(base+'/confirm-storyboard').status_code==422
    assert client.put(base+'/creative-settings',json=creative_fixture()).status_code==200
    p=store.load(p['id']); p['shots'][0]['prop_ids']=['missing'];store.save(p)
    assert client.post(base+'/confirm-storyboard').status_code==422
    p['shots'][0]['prop_ids']=['prop1'];store.save(p)
    assert client.post(base+'/confirm-storyboard').json()['storyboard_confirmed']


def test_extract_settings_is_draft_only(setup,monkeypatch):
    store,client=setup
    p=project(store)
    before=copy.deepcopy(p['shots'])
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'extract_settings',lambda script:creative_fixture())
    base=f"/api/ink/projects/{p['id']}"
    assert client.post(base+'/actions/settings').status_code==200
    result=client.get(base).json()
    assert result['creative_draft']['props'][0]['name']=='纸伞'
    assert result['shots']==api.public(p)['shots']
    assert not result.get('creative_settings')


def test_setting_image_generation_does_not_change_shot_images(setup,monkeypatch):
    from PIL import Image
    store,client=setup
    p=project(store)
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    def image(prompt,refs,folder,pid):
        assert refs==[] and '道具设定图' in prompt and '竹骨黄纸伞' in prompt
        target=folder/'asset.png';Image.new('RGB',(9,16),'white').save(target);return target
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'image',image)
    result=client.post(f"/api/ink/projects/{p['id']}/generate-setting-image",json={'settings':creative_fixture(),'group':'props','asset_id':'prop1'})
    assert result.status_code==200
    data=result.json()
    assert data['jobs'][0]['state']=='completed'
    assert data['creative_draft']['props'][0]['image']
    assert data['shots'][0]['image'] is None


def test_split_uses_confirmed_settings_and_retains_reference_ids(setup,monkeypatch):
    store,client=setup
    p=store.create('alice','新剧','书生在山寺撑伞')
    base=f"/api/ink/projects/{p['id']}"
    assert client.put(base+'/creative-settings',json=creative_fixture()).status_code==200
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    def split(script, *, settings=None):
        assert 'prop1' in script and '竹骨黄纸伞' in script
        assert settings['props'][0]['id']=='prop1'
        data=example_board()
        for s in data['shots']:s.update(scene_id='scene1',prop_ids=['prop1'])
        return data
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'split',split)
    assert client.post(base+'/actions/split').status_code==200
    p=store.load(p['id'])
    assert p['shots'][0]['scene_id']=='scene1'
    assert p['shots'][0]['prop_ids']==['prop1']
    assert not p['storyboard_confirmed']
    assert client.post(base+'/confirm-storyboard').status_code==200


def test_asset_reference_selection_and_validation(setup):
    from PIL import Image
    store,client=setup
    p=project(store)
    data=creative_fixture()
    data['characters'][0]['image']='person.png'
    data['props'][0]['image']='umbrella.png'
    for name in ('person.png','umbrella.png'):
        Image.new('RGB',(9,16),'white').save(store.folder(p['id'])/name)
    base=f"/api/ink/projects/{p['id']}"
    assert client.put(base+'/creative-settings',json=data).status_code==200
    p=store.load(p['id']);shot=p['shots'][0]
    assert api.creative_refs(p,shot)==[str(store.asset(p['id'],'person.png'))]
    shot['prop_ids']=['prop1']
    assert api.creative_refs(p,shot)==[str(store.asset(p['id'],'person.png')),str(store.asset(p['id'],'umbrella.png'))]
    data['scenes'][0]['image']='missing.png'
    assert client.put(base+'/creative-settings',json=data).status_code==422


def test_background_is_explicit_and_does_not_rewrite_script(setup):
    store, client = setup
    p = project(store)
    base = '/api/ink/projects/' + p['id']
    original = p['script']
    result = client.put(base + '/background', json={'era': '宋代'})
    assert result.status_code == 200
    assert result.json()['background'] == {'era':'宋代','source':'user'}
    assert client.get(base).json()['script'] == original
    result = client.put(base + '/background', json={'era': ''})
    assert result.status_code == 200
    assert result.json()['background'] == {'era':'','source':'unspecified'}
    assert client.get(base).json()['script'] == original


def test_background_context_never_infers_from_generic_story():
    from scenarios.ink_drama.background import background_context
    assert '未补充时代背景' in background_context({'script':'书生在古寺借伞'})
    assert '用户指定时代背景：宋代' in background_context({'background':{'era':'宋代'}})


def test_setting_history_retains_versions_and_adopts_without_rewriting_text(setup, monkeypatch):
    from PIL import Image
    store, client = setup
    p = project(store)
    settings = creative_fixture()
    base = f"/api/ink/projects/{p['id']}"
    Image.new('RGB', (9,16), 'white').save(store.folder(p['id'])/'old.png')
    settings['characters'][0]['image'] = 'old.png'
    p['creative_draft'] = settings
    store.save(p)
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    def image(prompt, refs, folder, pid):
        path = folder/'generated.png'
        Image.new('RGB', (9,16), 'gray').save(path)
        return path
    monkeypatch.setattr(api.providers, 'image', image)
    payload = {'settings':settings, 'group':'characters', 'asset_id':'c1'}
    generated = client.post(base+'/generate-setting-image', json=payload)
    assert generated.status_code == 200
    draft = generated.json()['creative_draft']
    new_image = draft['characters'][0]['image']
    rows = client.get(base+'/setting-history/characters/c1').json()['items']
    assert {x['image'] for x in rows} == {'old.png', new_image}
    assert client.get(base+'/setting-history/props/prop1').json()['items'] == []
    draft['characters'][0]['desc'] = '保留当前修改的描述'
    result = client.post(base+'/select-setting-image', json={**payload, 'settings':draft, 'image':'old.png'})
    assert result.status_code == 200
    assert result.json()['creative_draft']['characters'][0]['image'] == 'old.png'
    assert result.json()['creative_draft']['characters'][0]['desc'] == '保留当前修改的描述'
    assert len(client.get(base+'/setting-history/characters/c1').json()['items']) == 2
    assert client.post(base+'/select-setting-image', json={**payload, 'group':'props', 'asset_id':'prop1','image':'old.png'}).status_code == 422


@pytest.mark.parametrize('group,asset_id,reference_suffix', [('scenes','scene1','-empty'),('props','prop1','-props')])
@pytest.mark.parametrize('style,key', [('工笔淡彩','soft'),('兼工带写','simple'),('泼墨写意','bold')])
def test_setting_generation_uses_asset_group_style_reference(setup, monkeypatch, group, asset_id, reference_suffix, style, key):
    from PIL import Image
    from pathlib import Path
    store, client = setup
    p = project(store)
    settings = creative_fixture()
    settings['style'] = style
    seen = []
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    def image(prompt, refs, folder, pid):
        seen.append(prompt)
        assert len(refs) == 1
        assert Path(refs[0]).name == key + reference_suffix + '.png'
        assert Path(refs[0]).is_file()
        assert '人物数量为零' in prompt
        assert '人物倒影' in prompt
        if group == 'props':
            assert '不画持物的手' in prompt
        target = folder/'empty-test.png'
        Image.new('RGB', (9,16), 'white').save(target)
        return target
    monkeypatch.setattr(api.providers, 'image', image)
    result = client.post(f"/api/ink/projects/{p['id']}/generate-setting-image", json={'settings':settings,'group':group,'asset_id':asset_id})
    assert result.status_code == 200
    assert seen
    assert result.json()['jobs'][0]['state'] == 'completed'


def test_delete_shot_archives_all_outputs_and_restore_preserves_them(setup):
    store, client = setup
    p = project(store)
    s = p['shots'][1]
    s.update(image='image.png', clip='clip.mp4', rendered='sound.mp4',
             image_versions=['older.png', 'image.png'],
             image_history={'older.png': {'image': 'older.png', 'prompt': '原提示词'}},
             image_proposal={'id': 'candidate', 'image': 'candidate.png', 'shot': {'content': '候选内容'},
                             'mode': 'redesign', 'prompt': '候选提示词', 'stamp': [1, 'image.png', 2]},
             candidate=example_caption(), candidate_image='image.png')
    p.update(storyboard_confirmed=True, final='final.mp4', final_stale=False,
             baseline={'version': 2, 'characters': [], 'ink_style': {}, 'reference_images': ['image.png']})
    names = ['image.png', 'clip.mp4', 'sound.mp4', 'older.png', 'candidate.png', 'final.mp4']
    for name in names:
        store.asset(p['id'], name).write_bytes(name.encode())
    store.save(p)
    original = copy.deepcopy(p)
    base = f'/api/ink/projects/{p["id"]}'
    response = client.request('DELETE', base + '/shots/s2', json={'revision': s['revision']})
    assert response.status_code == 200
    result = response.json()
    entry = result['deleted_shots'][0]
    assert set(entry) == {'id', 'shot_id', 'index', 'scene', 'content', 'deleted_at'}
    assert entry['shot_id'] == 's2' and entry['index'] == 1
    after = store.load(p['id'])
    assert after['shots'] == [original['shots'][i] for i in (0, 2, 3)]
    assert after['deleted_shots'][0]['shot'] == original['shots'][1]
    assert after['baseline'] == original['baseline']
    assert not after['storyboard_confirmed'] and after['final_stale']
    assert after['final'] == 'final.mp4'
    for name in names:
        assert store.asset(p['id'], name).read_bytes() == name.encode()
    # Reloaded public state retains undo without leaking the full archived payload.
    assert client.get(base).json()['deleted_shots'] == [entry]
    restored = client.post(base + f'/deleted-shots/{entry["id"]}/restore')
    assert restored.status_code == 200
    after = store.load(p['id'])
    expected = copy.deepcopy(original['shots'])
    expected[1]['revision'] += 1
    expected[1]['image_proposal']['stamp'][0] += 1
    assert after['shots'] == expected
    assert not after['deleted_shots'] and not after['storyboard_confirmed'] and after['final_stale']
    assert client.post(base + f'/deleted-shots/{entry["id"]}/restore').status_code == 404
    assert client.request('DELETE', base + '/shots/s2', json={'revision': s['revision']}).status_code == 409


def test_delete_shot_rejects_stale_missing_and_last_shot(setup):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    original = store.load(p['id'])
    assert client.request('DELETE', base + '/shots/s1', json={}).status_code == 422
    assert client.request('DELETE', base + '/shots/s1', json={'revision': 1.5}).status_code == 422
    assert client.request('DELETE', base + '/shots/s1', json={'revision': 99}).status_code == 409
    assert client.request('DELETE', base + '/shots/missing', json={'revision': 1}).status_code == 404
    assert store.load(p['id']) == original
    for sid in ('s1', 's2', 's3'):
        assert client.request('DELETE', base + '/shots/' + sid, json={'revision': 1}).status_code == 200
    assert client.request('DELETE', base + '/shots/s3', json={'revision': 1}).status_code == 404
    assert client.request('DELETE', base + '/shots/s4', json={'revision': 1}).status_code == 409
    assert [s['id'] for s in store.load(p['id'])['shots']] == ['s4']


def test_delete_and_restore_respect_busy_and_readonly_projects(setup, monkeypatch):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    deleted = client.request('DELETE', base + '/shots/s1', json={'revision': 1}).json()['deleted_shots'][0]
    original = store.load(p['id'])
    restore = base + f'/deleted-shots/{deleted["id"]}/restore'
    jid = store.enqueue(p['id'], 'alice', 'image')
    assert client.request('DELETE', base + '/shots/s2', json={'revision': 1}).status_code == 409
    assert client.post(restore).status_code == 409
    assert store.load(p['id']) == original
    store.finish(jid)
    monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
    assert client.post('/api/ink/login', json={'token': 'bob-test'}).status_code == 200
    assert client.request('DELETE', base + '/shots/s2', json={'revision': 1}).status_code == 403
    assert client.post(restore).status_code == 403
    assert store.load(p['id']) == original


@pytest.mark.parametrize('restore_order', [
    ('s1', 's2', 's3'), ('s1', 's3', 's2'), ('s2', 's1', 's3'),
    ('s2', 's3', 's1'), ('s3', 's1', 's2'), ('s3', 's2', 's1'),
])
def test_multiple_deleted_shots_restore_original_order(setup, restore_order):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    for sid in ('s2', 's3', 's1'):
        assert client.request('DELETE', base + '/shots/' + sid, json={'revision': 1}).status_code == 200
    entries = {d['shot_id']: d['id'] for d in client.get(base).json()['deleted_shots']}
    for sid in restore_order:
        assert client.post(base + f'/deleted-shots/{entries[sid]}/restore').status_code == 200
    assert [s['id'] for s in store.load(p['id'])['shots']] == ['s1', 's2', 's3', 's4']


def test_restored_shot_marks_images_for_review_if_background_changed(setup):
    store, client = setup
    p = project(store)
    p['shots'][1].update(image='image.png', clip='clip.mp4', rendered='sound.mp4')
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    deleted = client.request('DELETE', base + '/shots/s2', json={'revision': 1}).json()['deleted_shots'][0]
    assert client.put(base + '/background', json={'era': '宋代'}).status_code == 200
    result = client.post(base + f'/deleted-shots/{deleted["id"]}/restore')
    assert result.status_code == 200
    restored = result.json()['shots'][1]
    assert restored['image'] == 'image.png' and restored['clip'] == 'clip.mp4'
    assert restored['image_stale'] and restored['clip_stale'] and restored['rendered_stale']


def test_restored_shot_only_invalidates_audio_if_voice_changed(setup):
    store, client = setup
    p = project(store)
    p['shots'][1].update(image='image.png', clip='clip.mp4', rendered='sound.mp4',
                         dialogues=[{'character_id': 'c1', 'text': '借伞'}])
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    deleted = client.request('DELETE', base + '/shots/s2', json={'revision': 1}).json()['deleted_shots'][0]
    assert client.post(base + '/voices', json={'voices': {'c1': api.VOICES['c2']}}).status_code == 200
    result = client.post(base + f'/deleted-shots/{deleted["id"]}/restore').json()['shots'][1]
    assert not result['image_stale'] and not result['clip_stale'] and result['rendered_stale']


@pytest.mark.parametrize('remaining', [1, 2, 3])
def test_assemble_after_deletion_uses_only_remaining_shots(setup, monkeypatch, remaining):
    store, client = setup
    p = project(store)
    for shot in p['shots']:
        shot['rendered'] = shot['id'] + '.mp4'
        store.asset(p['id'], shot['rendered']).write_bytes(b'test')
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    assert client.put(base + '/creative-settings', json=creative_fixture()).status_code == 200
    for sid in ['s4', 's3', 's2'][:4 - remaining]:
        assert client.request('DELETE', base + '/shots/' + sid, json={'revision': 1}).status_code == 200
    assert client.post(base + '/confirm-storyboard').status_code == 200
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    observed = []
    def assemble(clips, music, folder, target):
        observed.extend(path.name for path in clips)
        target.write_bytes(b'test final')
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'assemble', assemble)
    assert client.post(base + '/actions/assemble').status_code == 200
    result = client.get(base).json()
    assert result['jobs'][0]['state'] == 'completed'
    assert observed == [f's{i + 1}.mp4' for i in range(remaining)]
    assert result['final_url'] and not result['final_stale']


def test_restored_candidate_and_adoption_undo_remain_usable(setup):
    store, client = setup
    p = project(store)
    s = p['shots'][1]
    s['image'] = 'original.png'
    draft = {key: copy.deepcopy(s[key]) for key in api.ShotInput.model_fields}
    draft['content'] = '新画面'
    s['image_proposal'] = {'id': 'candidate', 'image': 'candidate.png', 'shot': draft,
                            'mode': 'redesign', 'prompt': '新画面', 'stamp': api.proposal_stamp(p, s)}
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    deleted = client.request('DELETE', base + '/shots/s2', json={'revision': 1}).json()['deleted_shots'][0]
    assert client.post(base + f'/deleted-shots/{deleted["id"]}/restore').status_code == 200
    adopted = client.post(base + '/shots/s2/adopt', json={'candidate_id': 'candidate'})
    assert adopted.status_code == 200
    shot = adopted.json()['shots'][1]
    assert shot['image'] == 'candidate.png' and shot['content'] == '新画面'
    deleted = client.request('DELETE', base + '/shots/s2', json={'revision': shot['revision']}).json()['deleted_shots'][0]
    assert client.post(base + f'/deleted-shots/{deleted["id"]}/restore').status_code == 200
    undone = client.post(base + '/shots/s2/undo-image')
    assert undone.status_code == 200
    assert undone.json()['shots'][1]['image'] == 'original.png'


@pytest.mark.parametrize('was_stale', [False, True])
def test_restore_archives_invalid_candidate_instead_of_showing_unusable_adopt(setup, was_stale):
    store, client = setup
    p = project(store)
    s = p['shots'][1]
    s['image'] = 'original.png'
    stamp = api.proposal_stamp(p, s)
    s['image_proposal'] = {'id': 'candidate', 'image': 'candidate.png',
                            'shot': {key: copy.deepcopy(s[key]) for key in api.ShotInput.model_fields},
                            'mode': 'redesign', 'prompt': '新画面', 'stamp': [99, *stamp[1:]] if was_stale else stamp}
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    deleted = client.request('DELETE', base + '/shots/s2', json={'revision': 1}).json()['deleted_shots'][0]
    if not was_stale:
        assert client.put(base + '/background', json={'era': '宋代'}).status_code == 200
    restored = client.post(base + f'/deleted-shots/{deleted["id"]}/restore').json()['shots'][1]
    assert restored['image_proposal'] is None
    assert restored['image_history']['candidate.png']['image'] == 'candidate.png'


def test_cloned_project_can_restore_without_false_reference_path_change(setup):
    store, client = setup
    p = project(store)
    p['shots'][1]['image'] = 'shot.png'
    settings = creative_fixture()
    settings['characters'][0]['image'] = 'character.png'
    store.asset(p['id'], 'character.png').write_bytes(b'fixture')
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    assert client.put(base + '/creative-settings', json=settings).status_code == 200
    deleted = client.request('DELETE', base + '/shots/s2', json={'revision': 1}).json()['deleted_shots'][0]
    cloned = client.post(base + '/clone').json()
    clonebase = f'/api/ink/projects/{cloned["id"]}'
    restored = client.post(clonebase + f'/deleted-shots/{deleted["id"]}/restore')
    assert restored.status_code == 200
    assert not restored.json()['shots'][1]['image_stale']
    assert client.get(base).json()['deleted_shots'][0]['id'] == deleted['id']


@pytest.mark.parametrize('pending_kind', ['proposal', 'undo'])
def test_restore_keeps_baseline_guard_for_assets_only_used_by_candidate_or_undo(setup, pending_kind):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    settings = creative_fixture()
    settings['characters'].append({'id': 'c2', 'name': '少女', 'desc': '白衣长发', 'image': None})
    assert client.put(base + '/creative-settings', json=settings).status_code == 200
    p = store.load(p['id'])
    shot = p['shots'][1]
    shot['image'] = 'current.png'
    other_shot = {key: copy.deepcopy(shot[key]) for key in api.ShotInput.model_fields}
    other_shot.update(character_ids=['c2'], content='少女走出寺门')
    if pending_kind == 'proposal':
        shot['image_proposal'] = {'id': 'candidate', 'image': 'candidate.png', 'shot': other_shot,
                                  'mode': 'redesign', 'prompt': '少女走出寺门', 'stamp': api.proposal_stamp(p, shot)}
    else:
        shot['image_undo'] = {**other_shot, 'image': 'previous.png', 'image_stale': False,
                              'used_prompt': '少女走出寺门', 'image_baseline_version': p['baseline']['version']}
        shot['image_undo_stamp'] = api.proposal_stamp(p, shot)
    before_context = api.shot_restore_context(p, shot)
    store.save(p)
    deleted = client.request('DELETE', base + '/shots/s2', json={'revision': 1}).json()['deleted_shots'][0]
    settings['characters'][1]['desc'] = '红衣短发'
    assert client.put(base + '/creative-settings', json=settings).status_code == 200
    changed = store.load(p['id'])
    assert api.shot_restore_context(changed, shot) == before_context
    response = client.post(base + f'/deleted-shots/{deleted["id"]}/restore')
    assert response.status_code == 200
    restored = response.json()['shots'][1]
    assert not restored['image_stale']
    if pending_kind == 'proposal':
        assert restored['image_proposal'] is None
        assert 'candidate.png' in restored['image_history']
        assert client.post(base + '/shots/s2/adopt', json={'candidate_id': 'candidate'}).status_code == 409
    else:
        assert restored['image_undo'] is None and restored['image_undo_stamp'] is None
        assert 'previous.png' in restored['image_history']
        assert client.post(base + '/shots/s2/undo-image').status_code == 409


def manual_shot(**changes):
    return {'content': '雨停后，书生沿石阶离开山寺', 'scene': '山寺', 'scene_id': 'scene1',
            'camera': '远景，平视', 'motion': '书生缓缓下阶', 'character_ids': ['c1'],
            'prop_ids': ['prop1'], 'dialogues': [], **changes}


def test_add_shot_appends_without_changing_existing_assets_or_calling_models(setup, monkeypatch):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    assert client.put(base + '/creative-settings', json=creative_fixture()).status_code == 200
    p = store.load(p['id'])
    p['shots'][0].update(image='existing.png', clip='existing.mp4', rendered='sound.mp4')
    p.update(final='final.mp4', final_stale=False, storyboard_confirmed=True)
    for name in ('existing.png', 'existing.mp4', 'sound.mp4', 'final.mp4'):
        store.asset(p['id'], name).write_bytes(name.encode())
    store.save(p)
    original = copy.deepcopy(p)
    def unexpected_call(*args, **kwargs):
        pytest.fail('Adding a storyboard shot must not start model or background tasks')
    monkeypatch.setattr(api.pool, 'submit', unexpected_call)
    response = client.post(base + '/shots', json=manual_shot())
    assert response.status_code == 200
    after = store.load(p['id'])
    assert after['shots'][:-1] == original['shots']
    assert after['baseline'] == original['baseline']
    assert after['creative_settings'] == original['creative_settings']
    assert after['final'] == 'final.mp4' and after['final_stale'] and not after['storyboard_confirmed']
    added = response.json()['shots'][-1]
    assert all(added[key] == value for key, value in manual_shot().items())
    assert added['id'].startswith('s_') and added['revision'] == 1
    assert added['image_url'] is None and added['clip_url'] is None and added['rendered_url'] is None
    assert not added['image_stale'] and not added['clip_stale'] and not added['rendered_stale']
    assert added['image_versions'] == [] and added['clip_versions'] == []
    assert store.jobs(p['id']) == [] and store.usage('alice') == {}
    for name in ('existing.png', 'existing.mp4', 'sound.mp4', 'final.mp4'):
        assert store.asset(p['id'], name).read_bytes() == name.encode()


@pytest.mark.parametrize('changes', [
    {'content': '   '}, {'character_ids': ['missing']}, {'character_ids': ['c1', 'c1']},
    {'dialogues': [{'character_id': 'c2', 'text': '借伞'}]},
    {'scene_id': 'missing'}, {'scene_id': None}, {'prop_ids': ['missing']},
    {'prop_ids': ['prop1', 'prop1']}, {'duration': 1}, {'id': 's1'},
])
def test_add_shot_rejects_invalid_fields_and_references_without_side_effects(setup, changes):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    assert client.put(base + '/creative-settings', json=creative_fixture()).status_code == 200
    before = store.load(p['id'])
    assert client.post(base + '/shots', json=manual_shot(**changes)).status_code == 422
    assert store.load(p['id']) == before
    assert store.jobs(p['id']) == [] and store.usage('alice') == {}


def test_add_shot_allows_first_manual_shot_and_enforces_six_shot_limit(setup):
    store, client = setup
    p = store.create('alice', '手动分镜', '书生借伞')
    base = f'/api/ink/projects/{p["id"]}'
    assert client.put(base + '/creative-settings', json=creative_fixture()).status_code == 200
    ids = []
    for i in range(30):
        result = client.post(base + '/shots', json=manual_shot(content=f'画面{i + 1}'))
        assert result.status_code == 200
        assert len(result.json()['shots']) == i + 1
        ids.append(result.json()['shots'][-1]['id'])
    assert len(set(ids)) == 30
    before = store.load(p['id'])
    assert client.post(base + '/shots', json=manual_shot()).status_code == 409
    assert store.load(p['id']) == before
    assert client.post(base + '/confirm-storyboard').status_code == 200


def test_add_shot_respects_readonly_and_busy_guards(setup, monkeypatch):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    body = manual_shot(scene_id=None, prop_ids=[])
    before = store.load(p['id'])
    jid = store.enqueue(p['id'], 'alice', 'image')
    assert client.post(base + '/shots', json=body).status_code == 409
    assert store.load(p['id']) == before
    store.finish(jid)
    monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
    assert client.post('/api/ink/login', json={'token': 'bob-test'}).status_code == 200
    assert client.post(base + '/shots', json=body).status_code == 403
    assert store.load(p['id']) == before


def test_add_shot_legacy_project_rejects_unconfirmed_asset_ids(setup):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    before = store.load(p['id'])
    assert client.post(base + '/shots', json=manual_shot()).status_code == 422
    assert store.load(p['id']) == before
    assert client.post(base + '/shots', json=manual_shot(scene_id=None, prop_ids=[])).status_code == 200


@pytest.mark.parametrize('restore_order', [('s2', 's4'), ('s4', 's2')])
def test_added_shots_stay_after_restored_shots_and_ids_are_not_reused(setup, restore_order):
    store, client = setup
    p = project(store)
    base = f'/api/ink/projects/{p["id"]}'
    assert client.put(base + '/creative-settings', json=creative_fixture()).status_code == 200
    for sid in ('s2', 's4'):
        assert client.request('DELETE', base + '/shots/' + sid, json={'revision': 1}).status_code == 200
    archived = {item['shot_id']: item['id'] for item in client.get(base).json()['deleted_shots']}
    new_ids = []
    for _ in range(2):
        result = client.post(base + '/shots', json=manual_shot())
        assert result.status_code == 200
        new_ids.append(result.json()['shots'][-1]['id'])
    for sid in restore_order:
        assert client.post(base + f'/deleted-shots/{archived[sid]}/restore').status_code == 200
    assert [s['id'] for s in client.get(base).json()['shots']] == ['s1', 's2', 's3', 's4', *new_ids]
    # A newly added, later deleted shot also retains its place when another is appended.
    response = client.request('DELETE', base + '/shots/' + new_ids[0], json={'revision': 1})
    deleted_id = response.json()['deleted_shots'][0]['id']
    latest = client.post(base + '/shots', json=manual_shot()).json()['shots'][-1]['id']
    assert latest not in {'s1', 's2', 's3', 's4', *new_ids}
    assert client.request('DELETE', base + '/shots/' + latest, json={'revision': 1}).status_code == 200
    assert client.post(base + f'/deleted-shots/{deleted_id}/restore').status_code == 200
    assert [s['id'] for s in client.get(base).json()['shots']] == ['s1', 's2', 's3', 's4', *new_ids]


@pytest.mark.parametrize('change_kind', ['content', 'dialogues'])
@pytest.mark.parametrize('pending_kind', ['draft', 'proposal', 'undo'])
def test_edit_shot_retires_old_snapshots_and_preserves_image_history(setup, change_kind, pending_kind):
    store, client = setup
    p = project(store)
    s = p['shots'][0]
    s.update(image='current.png', clip='clip.mp4', rendered='sound.mp4')
    old_shot = {key: copy.deepcopy(s[key]) for key in api.ShotInput.model_fields}
    old_shot.update(content='旧草稿画面', dialogues=[{'character_id': 'c1', 'text': '旧台词'}])
    s['image_draft'] = {'mode': 'redesign', 'instruction': '', 'shot': old_shot}
    if pending_kind == 'proposal':
        s['image_proposal'] = {'id': 'candidate', 'image': 'candidate.png', 'shot': old_shot,
                               'mode': 'redesign', 'prompt': '旧提示词', 'stamp': api.proposal_stamp(p, s)}
    elif pending_kind == 'undo':
        s['image_undo'] = {**old_shot, 'image': 'previous.png', 'image_stale': False,
                           'used_prompt': '旧提示词', 'image_baseline_version': None}
        s['image_undo_stamp'] = api.proposal_stamp(p, s)
    p.update(storyboard_confirmed=True, final='final.mp4', final_stale=False)
    for name in ('current.png', 'candidate.png', 'previous.png'):
        store.asset(p['id'], name).write_bytes(name.encode())
    store.save(p)
    before = copy.deepcopy(p)
    data = {key: copy.deepcopy(s[key]) for key in api.ShotInput.model_fields}
    if change_kind == 'content':
        data['content'] = '用户刚保存的新画面'
    else:
        data['dialogues'] = [{'character_id': 'c1', 'text': '用户刚保存的新台词'}]
    base = f'/api/ink/projects/{p["id"]}/shots/s1'
    response = client.patch(base, json=data)
    assert response.status_code == 200
    edited = response.json()['shots'][0]
    assert all(edited[key] == value for key, value in data.items())
    assert edited['image_draft'] is None and edited['image_proposal'] is None
    assert edited['image_undo'] is None and edited['image_undo_stamp'] is None
    assert edited['image'] == 'current.png' and edited['revision'] == 2
    assert edited['image_stale'] == (change_kind == 'content')
    assert edited['clip_stale'] == (change_kind == 'content')
    assert edited['rendered_stale'] and response.json()['final_stale']
    assert not response.json()['storyboard_confirmed']
    assert store.load(p['id'])['shots'][1:] == before['shots'][1:]
    history = {item['image']: item for item in client.get(base + '/history').json()['images']}
    assert 'current.png' in history
    expected_old = {'proposal': 'candidate.png', 'undo': 'previous.png'}.get(pending_kind)
    if expected_old:
        assert history[expected_old]['status'] == 'history'
        assert history[expected_old]['shot'] == old_shot
        assert client.get(history[expected_old]['image_url']).content == expected_old.encode()
    assert client.post(base + '/adopt', json={'candidate_id': 'candidate'}).status_code == 409
    assert client.post(base + '/undo-image').status_code == 409
    reloaded = client.get(f'/api/ink/projects/{p["id"]}').json()['shots'][0]
    assert all(reloaded[key] == value for key, value in data.items())
    assert reloaded['image_draft'] is None


def test_unchanged_shot_save_keeps_draft_candidate_undo_and_revision(setup):
    store, client = setup
    p = project(store)
    s = p['shots'][0]
    s['image'] = 'current.png'
    data = {key: copy.deepcopy(s[key]) for key in api.ShotInput.model_fields}
    s['image_draft'] = {'mode': 'redesign', 'instruction': '', 'shot': data}
    s['image_proposal'] = {'id': 'candidate', 'image': 'candidate.png', 'shot': data,
                           'mode': 'redesign', 'prompt': '提示词', 'stamp': api.proposal_stamp(p, s)}
    s['image_undo'] = {**data, 'image': 'previous.png', 'image_stale': False,
                       'used_prompt': '旧提示词', 'image_baseline_version': None}
    s['image_undo_stamp'] = api.proposal_stamp(p, s)
    p['storyboard_confirmed'] = True
    store.save(p)
    before = copy.deepcopy(p)
    base = f'/api/ink/projects/{p["id"]}/shots/s1'
    assert client.patch(base, json=data).status_code == 200
    assert store.load(p['id']) == before
    assert client.post(base + '/adopt', json={'candidate_id': 'candidate'}).status_code == 200


def test_duration_edit_preserves_image(setup):
    store, client = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(image='frame.png', image_stale=False, clip='clip.mp4', clip_stale=False, rendered='sound.mp4', rendered_stale=False)
    store.save(p)
    body = {key: shot[key] for key in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')}
    body['duration'] = 10
    response = client.patch(f'/api/ink/projects/{p["id"]}/shots/{shot["id"]}', json=body)
    assert response.status_code == 200, response.text
    saved = store.load(p['id'])['shots'][0]
    assert saved['duration'] == 10
    assert saved['image'] == 'frame.png' and not saved['image_stale']
    assert saved['clip_stale'] and saved['rendered_stale']


def test_video_duration_options(monkeypatch):
    from scenarios.ink_drama.providers import Config, video_durations
    monkeypatch.setattr(Config, 'VIDEO_FIRST_FRAME_MODEL', 'wan2.7-i2v')
    assert video_durations() == list(range(2, 16))
    monkeypatch.setattr(Config, 'VIDEO_FIRST_FRAME_MODEL', 'unknown-model')
    assert video_durations() == [5]

@pytest.mark.parametrize('redesign', [False, True])
def test_character_generation_identity_reference(setup, monkeypatch, redesign):
    from PIL import Image
    store, client = setup
    p = project(store)
    data = creative_fixture()
    data['characters'][0]['image'] = 'identity.png'
    Image.new('RGB', (9,16), 'white').save(store.folder(p['id'])/'identity.png')
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid):
        assert (str(folder/'identity.png') in refs) is (not redesign)
        assert ('本次必须按目标画风从头重新绘制整个角色' in prompt) is (not redesign)
        target = folder/'generated.png'
        Image.new('RGB', (9,16), 'gray').save(target)
        return target
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'image', image)
    response = client.post(f'/api/ink/projects/{p["id"]}/generate-setting-image', json={
        'settings': data, 'group':'characters', 'asset_id':data['characters'][0]['id'], 'redesign':redesign})
    assert response.status_code == 200
    assert response.json()['jobs'][0]['state'] == 'completed'


def test_frame_prefers_confirmed_character_over_old_caption():
    p = {'creative_settings': creative_fixture(), 'baseline': {'characters': [{'character_id':'c1','desc':'过期人物描述'}], 'ink_style':{}}}
    shot = example_board()['shots'][0]
    shot['scene_id'] = 'scene1'
    prompt = frame_prompt(p, shot)
    assert '过期人物描述' not in prompt
    assert p['creative_settings']['characters'][0]['desc'] in prompt


def test_regenerate_passes_confirmed_assets_not_old_frame(setup, monkeypatch):
    from PIL import Image
    store, client = setup
    p = project(store)
    settings = creative_fixture()
    p['creative_settings'] = settings
    for group, name in [('characters','person.png'),('scenes','scene.png'),('props','prop.png')]:
        settings[group][0]['image'] = name
        Image.new('RGB',(9,16),'white').save(store.folder(p['id'])/name)
    s = p['shots'][0]
    s.update(image='old.png', pending_image_edits=['motion'], scene_id='scene1', prop_ids=['prop1'])
    store.save(p)
    class Immediate:
        def submit(self,fn,*args): fn(*args)
    def image(prompt,refs,folder,pid):
        assert [Path(x).name for x in refs] == ['person.png','scene.png','prop.png']
        target=folder/'result.png'; Image.new('RGB',(9,16),'gray').save(target); return target
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'image',image)
    response=client.post(f'/api/ink/projects/{p["id"]}/actions/image?sid=s1')
    assert response.status_code == 200
    assert client.get(f'/api/ink/projects/{p["id"]}').json()['jobs'][0]['state']=='completed'


def test_missing_character_mentions_block_generation(setup):
    store, client = setup
    p = project(store)
    p['characters'][0]['name'] = '年轻书生'
    p['shots'][0].update(character_ids=[], content='少女站在书生身旁')
    store.save(p)
    response = client.post(f'/api/ink/projects/{p["id"]}/actions/image?sid=s1')
    assert response.status_code == 422
    assert '年轻书生' in response.json()['detail']
    assert not store.jobs(p['id'])


def test_character_check_ignores_dialogue_and_accepts_selection():
    from scenarios.ink_drama.creative import check_visible_characters
    p = {'characters':[{'id':'c1','name':'年轻书生'}]}
    shot = dict(content='山寺',motion='雨落',character_ids=[],dialogues=[{'text':'书生在哪里'}])
    check_visible_characters(p,shot)
    shot.update(content='书生站在门前',character_ids=['c1'])
    check_visible_characters(p,shot)


@pytest.mark.parametrize('view', ['front', 'sheet'])
def test_style_change_uses_partial_identity_reference(setup, monkeypatch, view):
    from PIL import Image
    store, client = setup
    p = project(store)
    p['creative_settings'] = creative_fixture()
    p['creative_settings']['style'] = '泼墨写意'
    store.save(p)
    data = creative_fixture()
    data['style'] = '工笔淡彩'
    data['characters'][0]['image'] = 'old-ink.png'
    Image.new('RGB',(90,160),'white').save(store.folder(p['id'])/'old-ink.png')
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid, ratio='9:16'):
        assert len(refs) == 2 and Path(refs[-1]).name == 'soft.png'
        assert Path(refs[0]).name.endswith('-identity.png')
        with Image.open(refs[0]) as crop: assert crop.height < 160
        assert '跨画风重新绘制' in prompt
        assert ratio == ('16:9' if view == 'sheet' else '9:16')
        target = folder/'new.png'; Image.new('RGB',(9,16),'white').save(target); return target
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'image',image)
    result=client.post(f'/api/ink/projects/{p["id"]}/generate-setting-image',json={'settings':data,'group':'characters','asset_id':data['characters'][0]['id'],'view':view})
    assert result.status_code == 200
    assert result.json()['jobs'][0]['state'] == 'completed'

    saved = store.load(p['id'])
    name = saved['creative_draft']['characters'][0]['image']
    assert saved['setting_generation_records'][name]['reference_mode'] == 'portrait'
    assert not list(store.folder(p['id']).glob('*-identity.png'))


def test_identity_reference_tracks_original_and_rejects_multiview(tmp_path):
    from PIL import Image
    from scenarios.ink_drama.identity_reference import identity_source, portrait_reference
    p={'setting_generation_records':{'b':{'identity_source':'a'},'c':{'identity_source':'b'}}}
    assert identity_source(p,{'image':'c'}) == 'a'
    source=tmp_path/'sheet.png'
    Image.new('RGB',(160,90)).save(source)
    with pytest.raises(UserError,match='单人竖版'):
        portrait_reference(source,tmp_path/'crop.png')


def test_side_view_preserves_front_and_uses_it_as_reference(setup, monkeypatch):
    from PIL import Image
    store, client = setup
    p = project(store); data = creative_fixture()
    data['characters'][0]['image'] = 'front.png'
    Image.new('RGB',(9,16),'white').save(store.folder(p['id'])/'front.png')
    class Immediate:
        def submit(self,fn,*args): fn(*args)
    def image(prompt,refs,folder,pid):
        assert Path(refs[0]).name == 'front.png'
        assert '严格侧面全身' in prompt
        target=folder/'generated.png'; Image.new('RGB',(9,16),'gray').save(target); return target
    monkeypatch.setattr(api,'pool',Immediate()); monkeypatch.setattr(api.providers,'image',image)
    response=client.post(f'/api/ink/projects/{p["id"]}/generate-setting-image',json={'settings':data,'group':'characters','asset_id':data['characters'][0]['id'],'view':'side'})
    assert response.status_code==200
    result=response.json(); assert result['jobs'][0]['state']=='completed'
    character=result['creative_draft']['characters'][0]
    assert character['image']=='front.png'
    assert character['views']['side']['source']=='front.png'
    assert character['views']['side']['image']!='front.png'


def test_character_sheet_single_call_and_used_as_reference(setup, monkeypatch):
    from PIL import Image
    store, client = setup
    p = project(store); data = creative_fixture()
    data['characters'][0]['image'] = 'front.png'
    Image.new('RGB', (90,160)).save(store.folder(p['id'])/'front.png')
    calls = []
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid, ratio='9:16'):
        calls.append(prompt)
        assert ratio == '16:9'
        assert '严格90度侧面' in prompt and '严格背面' in prompt
        assert Path(refs[0]).name == 'front.png'
        target=folder/'sheet.png'; Image.new('RGB',(160,90)).save(target); return target
    monkeypatch.setattr(api,'pool',Immediate())
    monkeypatch.setattr(api.providers,'image',image)
    response=client.post(f'/api/ink/projects/{p["id"]}/generate-setting-image',json={'settings':data,'group':'characters','asset_id':data['characters'][0]['id'],'view':'sheet'})
    assert response.status_code == 200
    assert response.json()['jobs'][0]['state'] == 'completed'
    assert len(calls) == 1
    draft=response.json()['creative_draft']
    assert not draft['characters'][0]['views']
    assert draft['characters'][0]['image'] != 'front.png'
    saved=client.put(f'/api/ink/projects/{p["id"]}/creative-settings',json=draft)
    assert saved.status_code == 200
    refs=api.creative_refs(store.load(p['id']),dict(character_ids=[data['characters'][0]['id']],camera='侧面',motion=''))
    assert Path(refs[0]).name == draft['characters'][0]['image']


def test_video_settings_preserve_image_and_storyboard(setup):
    store, client = setup
    p=project(store); s=p['shots'][0]
    s.update(image='keep.png',image_stale=False,clip='old.mp4',rendered='old-sound.mp4')
    old_motion=s['motion']; old_camera=s['camera']; store.save(p)
    response=client.put(f'/api/ink/projects/{p["id"]}/shots/{s["id"]}/video-settings',json={'motion':'slowly turn head','camera':'slow push in','duration':5})
    assert response.status_code==200
    result=store.load(p['id'])['shots'][0]
    assert result['image']=='keep.png' and not result['image_stale']
    assert result['motion']==old_motion and result['camera']==old_camera
    assert result['video_settings']=={'motion':'slowly turn head','camera':'slow push in','mode':'first_frame','end_shot_id':None}
    assert result['clip']=='old.mp4' and result['clip_stale']
    assert result['rendered']=='old-sound.mp4' and result['rendered_stale']


def test_storyboard_draft_discard_keeps_current(setup):
    store, client = setup
    p = project(store)
    p['shots'][0]['image'] = 'original.png'
    p['storyboard_draft'] = example_board()
    store.save(p)
    response = client.post(f"/api/ink/projects/{p['id']}/storyboard-draft/discard")
    assert response.status_code == 200
    saved = store.load(p['id'])
    assert saved['shots'] == p['shots']
    assert 'storyboard_draft' not in saved


def test_storyboard_draft_adopt_archives_media_and_changes_ids(setup):
    store, client = setup
    p = project(store)
    p['shots'][0]['image'] = 'original.png'
    p['shots'][0]['clip'] = 'original.mp4'
    p['storyboard_draft'] = example_board()
    p['storyboard_draft']['shots'][0]['content'] = '新的首帧'
    store.save(p)
    response = client.post(f"/api/ink/projects/{p['id']}/storyboard-draft/adopt")
    assert response.status_code == 200
    saved = store.load(p['id'])
    assert saved['shots'][0]['content'] == '新的首帧'
    assert saved['shots'][0]['id'] != p['shots'][0]['id']
    assert saved['storyboard_history'][0]['shots'] == p['shots']
    assert saved['shots'][0]['image'] is None
    assert saved['final_stale'] and not saved['storyboard_confirmed']
    assert client.post(f"/api/ink/projects/{p['id']}/storyboard-draft/adopt").status_code == 409


def test_storyboard_edit_retires_old_video_override(setup):
    store, client = setup
    p = project(store)
    s = p['shots'][0]
    s['video_settings'] = {'motion': '旧动作', 'camera': '旧运镜'}
    store.save(p)
    body = {key: s[key] for key in ('content', 'scene', 'camera', 'motion', 'character_ids', 'dialogues')}
    body['motion'] = '分镜列表：\n分镜1：[5秒] 特写，少女递出伞。'
    response = client.patch(f"/api/ink/projects/{p['id']}/shots/{s['id']}", json=body)
    assert response.status_code == 200
    saved = store.load(p['id'])['shots'][0]
    assert saved['motion'] == body['motion']
    assert 'video_settings' not in saved


def test_video_mode_inputs_and_missing_assets(setup, monkeypatch):
    store, client = setup
    p = project(store)
    first, second = p['shots'][:2]
    monkeypatch.setattr(api, 'video_modes', lambda: [dict(id=m, supported=True) for m in ('first_frame', 'start_end_frame', 'reference')])
    with pytest.raises(UserError, match='尾帧'):
        api.video_inputs(p, first, 'start_end_frame')
    folder = store.asset(p['id'], 'tail.png').parent
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'tail.png').write_bytes(b'image')
    second.update(image='tail.png', image_stale=False)
    tail, refs = api.video_inputs(p, first, 'start_end_frame')
    assert tail.name == 'tail.png' and refs == []
    with pytest.raises(UserError, match='角色和场景'):
        api.video_inputs(p, first, 'reference')
    p['creative_settings'] = {'characters': [{'id': 'c1', 'image': 'tail.png'}], 'scenes': []}
    tail, refs = api.video_inputs(p, first, 'reference')
    assert tail is None and refs == [str(folder / 'tail.png')]
    monkeypatch.setattr(api, 'video_modes', lambda: [dict(id='reference', supported=False)])
    with pytest.raises(UserError, match='不支持'):
        api.video_inputs(p, first, 'reference')


@pytest.mark.parametrize('mode', ['first_frame', 'start_end_frame', 'reference'])
def test_video_adapter_reuses_base_client(tmp_path, monkeypatch, mode):
    from scenarios.ink_drama import providers as module
    from models.video_client import VideoClient
    calls = []
    target = tmp_path / 'video.mp4'
    def generate(self, **kwargs):
        calls.append(kwargs)
        target.write_bytes(b'video')
    monkeypatch.setattr(VideoClient, 'generate_video', generate)
    monkeypatch.setattr(module, 'video_model', lambda selected: 'model-' + selected)
    module.Providers().video(tmp_path/'first.png', '动作', target, mode=mode,
        last_image=tmp_path/'tail.png' if mode=='start_end_frame' else None,
        references=['role.png','scene.png'] if mode=='reference' else None)
    call = calls[0]
    assert call['model'] == 'model-' + mode
    assert (call['image_path'] is None) == (mode=='reference')
    assert bool(call['last_image_path']) == (mode=='start_end_frame')
    assert bool(call['reference_image_paths']) == (mode=='reference')


def test_video_request_records_actual_parameters(tmp_path, monkeypatch):
    from scenarios.ink_drama import providers as module
    from models.video_client import VideoClient
    monkeypatch.setattr(module, 'video_model', lambda mode: 'wan2.7-i2v')
    seen = []
    def generate(self, **kwargs):
        seen.append(kwargs)
        Path(kwargs['save_path']).write_bytes(b'video')
    monkeypatch.setattr(VideoClient, 'generate_video', generate)
    target = tmp_path/'result.mp4'
    module.Providers().video(tmp_path/'first.png', '分镜列表：动作', target)
    record = json.loads(target.with_suffix('.request.json').read_text())
    assert record['request'] == seen[0]
    assert record['state'] == 'completed'
    assert record['request']['prompt_extend'] is False
    assert 'audio' not in record['request']
    assert 'generate_audio' not in record['request']
    assert record['audio_policy'] == 'preserve_original'
    assert 'shot_type' not in record['request']
    assert record['shot_policy'] == 'single_continuous'
    assert '只生成一个连续镜头' in record['request']['prompt']
    def fail(self, **kwargs):
        raise RuntimeError('provider failed')
    monkeypatch.setattr(VideoClient, 'generate_video', fail)
    with pytest.raises(RuntimeError):
        module.Providers().video(tmp_path/'first.png', '动作', tmp_path/'failed.mp4')
    assert json.loads((tmp_path/'failed.request.json').read_text())['state'] == 'failed'


@pytest.mark.parametrize('content', [
    '少女望向画外书生，右手稳握闭合伞，伞柄朝向书生所在方向。',
    '少女望向画外的年轻书生。',
    '书生不入镜，少女面向书生所在方向。',
    '年轻书生在画面外，少女独自站立。',
    '少女独自站立。',
])
def test_first_frame_allows_offscreen_character(content):
    from scenarios.ink_drama.creative import check_visible_characters
    p = {'characters': [{'id': 'c1', 'name': '年轻书生'}]}
    check_visible_characters(p, dict(content=content, motion='书生随后走入画面', character_ids=[]))


def test_speech_handshake_failure_is_actionable_and_sanitized(monkeypatch, tmp_path):
    from pipelines import tts
    from scenarios.ink_drama.providers import Providers
    WSServerHandshakeError = type('WSServerHandshakeError', (Exception,), {})
    async def fail(*args, **kwargs):
        raise WSServerHandshakeError('private endpoint must not be exposed')
    monkeypatch.setattr(tts, 'generate_edge_tts', fail)
    with pytest.raises(ValueError, match='Edge 配音服务连接被拒绝') as error:
        Providers().speak('测试', 'voice', tmp_path/'audio.mp3')
    assert 'private endpoint' not in str(error.value)


@pytest.mark.parametrize('speech_fails', [False, True])
def test_video_automatically_adds_sound_and_preserves_clip_on_speech_failure(setup, monkeypatch, speech_fails):
    store, client = setup
    p = project(store)
    s = p['shots'][0]
    s.update(image='start.png', image_stale=False, content='仅供生图的静态构图', camera='中景，腰部以上', motion='中景，右手轻拂衣袖',
             dialogues=[{'character_id': 'c1', 'text': '测试'}])
    store.asset(p['id'], 'start.png').write_bytes(b'test')
    store.save(p)
    monkeypatch.setattr(api, 'video_durations', lambda mode='first_frame': [5])
    monkeypatch.setattr(api, 'video_inputs', lambda *args: (None, None))
    def video(image, motion, target, **kw):
        assert '仅供生图的静态构图' not in motion
        assert '腰部以上' not in motion
        assert '中景，' not in motion
        assert '右手轻拂衣袖' in motion
        target.write_bytes(b'video')
    monkeypatch.setattr(api.providers, 'video', video)
    monkeypatch.setattr(api.providers, 'duration', lambda target: 1 if target.suffix == '.mp3' else 5)
    def speak(text, voice, target):
        if speech_fails:
            raise ValueError('connection failed')
        target.write_bytes(b'audio')
    monkeypatch.setattr(api.providers, 'speak', speak)
    monkeypatch.setattr(api.providers, 'render', lambda video, lines, folder, target, **kw: target.write_bytes(b'rendered'))
    jid = store.enqueue(p['id'], 'alice', 'video')
    api.run_job(jid, p['id'], {'id': 'alice', 'limits': {'video': 2, 'speech': 2}}, 'video', s['id'])
    result = store.load(p['id'])['shots'][0]
    assert store.asset(p['id'], result['clip']).read_bytes() == b'video'
    assert result['clip_stale'] is False
    data = client.get(f"/api/ink/projects/{p['id']}").json()
    if speech_fails:
        assert data['jobs'][0]['state'] == 'failed'
        assert '视频已生成并保留' in data['jobs'][0]['error']
        assert not result['rendered']
        # Retrying audio must not invoke video generation again.
        monkeypatch.setattr(api.providers, 'video', lambda *a, **kw: pytest.fail('must not regenerate video'))
        monkeypatch.setattr(api.providers, 'speak', lambda text, voice, target: target.write_bytes(b'audio'))
        jid = store.enqueue(p['id'], 'alice', 'sound')
        api.run_job(jid, p['id'], {'id': 'alice', 'limits': {'speech': 2}}, 'sound', s['id'])
        assert store.load(p['id'])['shots'][0]['rendered']
    else:
        assert data['jobs'][0]['state'] == 'completed'
        assert result['rendered'] and result['media_step'] == 'complete'


def test_video_history_is_shot_scoped_and_includes_legacy_and_retry_renders(setup, monkeypatch):
    store, client = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(clip='current.mp4', clip_versions=['old.mp4', 'current.mp4', 'missing.mp4', 'old.mp4'],
                rendered='retry-sound.mp4', rendered_versions=['previous-retry.mp4'],
                image='image.png', image_stale=False, clip_stale=False, rendered_stale=False)
    for name in ('current.mp4', 'old.mp4', 'old-sound.mp4', 'retry-sound.mp4', 'previous-retry.mp4', 'other-shot.mp4', 'image.png'):
        store.asset(p['id'], name).write_bytes(b'fixture')
    p['shots'][1]['clip_versions'] = ['other-shot.mp4']
    store.save(p)
    base = f"/api/ink/projects/{p['id']}/shots/{shot['id']}"
    response = client.get(base+'/video-history')
    assert response.status_code == 200
    items = response.json()['videos']
    assert {x['video'] for x in items} == {'current.mp4', 'old.mp4', 'old-sound.mp4', 'retry-sound.mp4', 'previous-retry.mp4'}
    assert len(items) == 5
    assert [x['video'] for x in items if x['current']] == ['retry-sound.mp4']
    for item in items:
        assert client.get(item['video_url']).status_code == 200
    shot['clip_stale'] = True
    shot['rendered_stale'] = True
    store.save(p)
    stale_items = client.get(base+'/video-history').json()['videos']
    selected = next(x for x in stale_items if x['current'])
    assert selected['video'] == 'current.mp4'
    assert selected['needs_confirmation'] is True
    assert client.get(f"/api/ink/projects/{p['id']}/shots/missing/video-history").status_code == 404
    monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
    assert client.post('/api/ink/login', json={'token': 'bob-test'}).status_code == 200
    assert client.get(base+'/video-history').status_code == 200  # Shared trial demos allow read-only viewing.
    client.cookies.clear()
    assert client.get(base+'/video-history').status_code == 401


def test_sound_retry_retains_previous_subtitled_video(setup, monkeypatch):
    store, _ = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(clip='clip.mp4', rendered='old-sound.mp4')
    store.asset(p['id'], 'clip.mp4').write_bytes(b'video')
    store.asset(p['id'], 'old-sound.mp4').write_bytes(b'old')
    monkeypatch.setattr(api.providers, 'render', lambda video, lines, folder, target, **kwargs: target.write_bytes(b'new'))
    api.add_shot_sound(p, shot, {'id': 'alice'}, store.folder(p['id']), 'new')
    assert shot['rendered_versions'] == ['old-sound.mp4', 'new-sound.mp4']
    assert store.asset(p['id'], 'old-sound.mp4').read_bytes() == b'old'


def test_local_pose_edit_uses_current_adopted_image_and_keeps_video_motion(setup, monkeypatch):
    from PIL import Image
    store, client = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(image='selected-history.png', image_versions=['older.png', 'selected-history.png'])
    for name in shot['image_versions']:
        Image.new('RGB', (9, 16), 'white').save(store.folder(p['id'])/name)
    p['characters'][0].update(image='role.png', desc='固定黑布巾束发，灰蓝衣')
    Image.new('RGB', (9, 16), 'white').save(store.folder(p['id'])/'role.png')
    store.save(p)
    instruction = '书生右手抬到胸前，手掌向上；其他保持不变'
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    def image(prompt, refs, folder, pid):
        assert refs == [str(store.asset(pid, 'selected-history.png')), str(store.asset(pid, 'role.png'))]
        assert '固定黑布巾束发' in prompt
        assert '参考图2' in prompt
        assert instruction in prompt
        assert '允许仅修改要求中明确指定的人物局部动作' in prompt
        assert '保持人物姿势、相互位置' not in prompt
        target = folder/'pose.png'
        Image.new('RGB', (9, 16), 'blue').save(target)
        return target
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'image', image)
    body = {'mode': 'detail', 'instruction': instruction,
            'shot': {key: copy.deepcopy(shot[key]) for key in api.ShotInput.model_fields}}
    response = client.post(f"/api/ink/projects/{p['id']}/shots/{shot['id']}/preview", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data['jobs'][0]['state'] == 'completed'
    saved = data['shots'][0]
    assert saved['image'] == 'selected-history.png'
    assert saved['motion'] == shot['motion']
    assert saved['image_proposal']['shot']['motion'] == shot['motion']
    assert instruction in saved['image_proposal']['shot']['content']

    assert saved['image_proposal']['reference_images'] == ['selected-history.png', 'role.png']
    assert saved['image_proposal']['generation_recipe'] == 'detail-identity-v2'


def test_sound_preserves_original_audio_without_tts_or_render(setup, monkeypatch):
    store, _ = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(clip='native.mp4', rendered='old-dub.mp4', dialogues=[{'character_id':'c1', 'text':'测试'}])
    monkeypatch.setattr(api.providers, 'has_audio', lambda path: True)
    monkeypatch.setattr(api.providers, 'speak', lambda *args: pytest.fail('must preserve native voice'))
    monkeypatch.setattr(api.providers, 'render', lambda *args, **kwargs: pytest.fail('must not replace native audio'))
    api.add_shot_sound(p, shot, {'id':'alice'}, store.folder(p['id']), 'new')
    assert shot['rendered'] == shot['clip'] == 'native.mp4'
    assert shot['audio_source'] == 'original'
    assert shot['rendered_versions'] == ['old-dub.mp4']


def test_adopt_video_uses_selected_artifact_without_regeneration(setup, monkeypatch):
    store, client = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(image='frame.png', clip='latest.mp4', clip_versions=['old.mp4'],
                rendered='dub.mp4', rendered_stale=True)
    p['final'] = 'final.mp4'
    for name in ('old.mp4','latest.mp4','dub.mp4','other.mp4'):
        store.asset(p['id'], name).write_bytes(b'original artifact')
    store.save(p)
    monkeypatch.setattr(api.providers, 'duration', lambda path: 3.02)
    monkeypatch.setattr(api.providers, 'speak', lambda *a: pytest.fail('no speech call on adoption'))
    monkeypatch.setattr(api.providers, 'video', lambda *a, **kw: pytest.fail('no video call on adoption'))
    base = f"/api/ink/projects/{p['id']}/shots/{shot['id']}"
    body = dict(video='other.mp4', revision=shot['revision'], current_clip='latest.mp4')
    assert client.post(base+'/adopt-video', json=body).status_code == 422
    body.update(video='old.mp4', revision=shot['revision']+1)
    assert client.post(base+'/adopt-video', json=body).status_code == 409
    body['revision'] = shot['revision']
    result = client.post(base+'/adopt-video', json=body)
    assert result.status_code == 200
    data = result.json(); selected = data['shots'][0]
    assert selected['clip'] == selected['rendered'] == 'old.mp4'
    assert selected['duration'] == 3 and selected['audio_source'] == 'original'
    assert not selected['clip_stale'] and not selected['rendered_stale']
    assert data['final_stale']
    history = client.get(base+'/video-history').json()['videos']
    assert sum(x['current'] for x in history) == 1
    assert {'dub.mp4', 'latest.mp4'} <= {x['video'] for x in history}
    assert store.asset(p['id'], 'old.mp4').read_bytes() == b'original artifact'
    body.update(video='dub.mp4', revision=selected['revision'], current_clip='old.mp4')
    adopted_dub = client.post(base+'/adopt-video', json=body).json()['shots'][0]
    assert adopted_dub['rendered'] == 'dub.mp4'
    monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
    assert client.post('/api/ink/login', json={'token':'bob-test'}).status_code == 200
    assert client.post(base+'/adopt-video', json=body).status_code == 403


@pytest.mark.parametrize('has_dialogue', [False, True])
def test_native_video_includes_dialogue_and_keeps_returned_audio(setup, monkeypatch, has_dialogue):
    store, _ = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(image='frame.png', motion='右手轻拂衣袖',
                dialogues=[{'character_id': 'c1', 'text': '你不怕我不回来？'}] if has_dialogue else [])
    store.save(p)
    monkeypatch.setattr(api, 'video_model', lambda mode: 'wan2.7-i2v')
    monkeypatch.setattr(api, 'video_durations', lambda mode: [5])
    monkeypatch.setattr(api, 'video_inputs', lambda *args: (None, None))
    def video(image, motion, target, **kwargs):
        assert '右手轻拂衣袖' in motion
        if has_dialogue:
            assert '书生说：“你不怕我不回来？”' in motion
            assert '动作与声音同步' in motion
        else:
            assert '本镜无台词' in motion
        target.write_bytes(b'native audio and video')
    monkeypatch.setattr(api.providers, 'video', video)
    monkeypatch.setattr(api.providers, 'duration', lambda path: 5)
    monkeypatch.setattr(api.providers, 'has_audio', lambda path: True)
    monkeypatch.setattr(api.providers, 'speak', lambda *args: pytest.fail('must not overdub native audio'))
    monkeypatch.setattr(api.providers, 'render', lambda *args, **kwargs: pytest.fail('must keep original artifact'))
    jid = store.enqueue(p['id'], 'alice', 'video')
    api.run_job(jid, p['id'], {'id':'alice', 'limits': {'video':2}}, 'video', shot['id'])
    result = store.load(p['id'])['shots'][0]
    assert store.jobs(p['id'])[0]['state'] == 'completed'
    assert result['rendered'] == result['clip']
    assert result['audio_source'] == 'original'


def spatial_pair(store):
    p = project(store)
    p['characters'].append({'id':'c2', 'name':'守寺少女', 'desc':'浅色长裙'})
    for s in p['shots']:
        s['scene_id'] = 'scene1'
    p['shots'][0].update(image='correct.png', character_ids=['c1','c2'], image_stale=False,
                         clip='keep.mp4', rendered='keep-sound.mp4')
    store.asset(p['id'], 'correct.png').write_bytes(b'keep image')
    p['final'] = 'keep-final.mp4'
    store.save(p)
    return p


def test_scene_layout_save_freezes_reference_and_preserves_existing_results(setup, monkeypatch):
    store, client = setup
    p = spatial_pair(store)
    base = f"/api/ink/projects/{p['id']}"
    before = client.get(base).json()
    layout = before['scene_layouts'][0]
    layout['placements'][0]['anchor'] = '门外'
    layout['placements'][1]['anchor'] = '从门内走到檐下'
    layout['references'] = [{'shot_id':'s1','image':'correct.png'}]
    body = {'version':0, 'layouts':[layout]}
    bad = copy.deepcopy(body); bad['layouts'][0]['references'][0]['image'] = 'not-owned.png'
    assert client.put(base+'/scene-layouts',json=bad).status_code == 409
    bad = copy.deepcopy(body); bad['layouts'][0]['placements'][1]['character_id'] = 'c1'
    assert client.put(base+'/scene-layouts',json=bad).status_code == 422
    jid = store.enqueue(p['id'], 'alice', 'image')
    assert client.put(base+'/scene-layouts',json=body).status_code == 409
    store.finish(jid)
    result = client.put(base+'/scene-layouts',json=body)
    assert result.status_code == 200
    saved = result.json()
    assert saved['spatial_version'] == 1 and not saved['final_stale']
    shot = saved['shots'][0]
    assert shot['image'] == 'correct.png' and shot['clip'] == 'keep.mp4' and not shot['image_stale']
    assert not shot['clip_stale'] and not shot['rendered_stale']
    assert store.asset(p['id'], 'correct.png').read_bytes() == b'keep image'
    assert saved['scene_layouts'] == client.get(base).json()['scene_layouts']
    assert client.put(base+'/scene-layouts',json=body).status_code == 409
    monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
    assert client.post('/api/ink/login',json={'token':'bob-test'}).status_code == 200
    assert client.put(base+'/scene-layouts',json={**body,'version':1}).status_code == 403


def test_retired_spatial_reference_is_ignored_and_missing_file_does_not_block(setup):
    from scenarios.ink_drama.spatial import layouts_for, with_spatial_reference
    store, _ = setup
    p = spatial_pair(store)
    p['scene_layouts'] = layouts_for(p)
    p['scene_layouts'][0]['references'] = [{'shot_id':'s1','image':'correct.png'}]
    p['shots'][0]['image'] = 'later-bad.png'
    prompt, refs = with_spatial_reference(p, p['shots'][1], '首帧', ['identity.png'], store)
    assert refs == ['identity.png'] and prompt == '首帧'
    assert store.asset(p['id'], 'correct.png').is_file()
    store.asset(p['id'], 'correct.png').unlink()
    assert with_spatial_reference(p, p['shots'][1], '首帧', [], store) == ('首帧', [])


def test_candidate_with_failed_spatial_check_cannot_be_adopted(setup):
    store, client = setup
    p = spatial_pair(store)
    p['shots'][0]['image_proposal'] = {'id':'candidate', 'style_check':{'spatial_policy':2,'regions':{'staging':{'status':'deviates'}}}}
    store.save(p)
    response = client.post(f"/api/ink/projects/{p['id']}/shots/s1/adopt",json={'candidate_id':'candidate'})
    assert response.status_code == 422 and '场景' in response.json()['detail']
    assert store.load(p['id'])['shots'][0]['image'] == 'correct.png'


def test_video_generation_receives_shared_layout_without_regenerating_still(setup, monkeypatch):
    store, _ = setup
    p = spatial_pair(store)
    shot = p['shots'][0]
    shot.update(motion='两人相视一笑',dialogues=[])
    store.save(p)
    monkeypatch.setattr(api,'video_inputs',lambda *args: (None, []))
    monkeypatch.setattr(api,'video_durations',lambda mode: [5])
    def video(image, motion, target, **kwargs):
        assert '不固定人物在画面中的左、右' in motion
        assert '按明确的动作路径走动' in motion and '不自行切镜' in motion
        target.write_bytes(b'video')
    monkeypatch.setattr(api.providers,'video',video)
    monkeypatch.setattr(api.providers,'has_audio',lambda path: True)
    monkeypatch.setattr(api.providers,'duration',lambda path: 5)
    jid = store.enqueue(p['id'],'alice','video')
    api.run_job(jid,p['id'],{'id':'alice','limits':{'video':2}},'video','s1')
    assert store.jobs(p['id'])[0]['state'] == 'completed'
    assert store.load(p['id'])['shots'][0]['image'] == 'correct.png'


@pytest.mark.parametrize('motion', ['少女面对镜头', '少女在画面左侧，书生在画面右侧'])
def test_shot_camera_direction_is_not_rejected_as_global_position_conflict(setup, monkeypatch, motion):
    store, _ = setup
    p = spatial_pair(store)
    p['shots'][0]['video_settings'] = {'motion':motion,'camera':''}
    p['shots'][0]['dialogues'] = []
    store.save(p)
    monkeypatch.setattr(api,'video_inputs',lambda *args: (None, []))
    monkeypatch.setattr(api,'video_durations',lambda mode: [5])
    def video(image, prompt, target, **kwargs):
        assert motion in prompt
        target.write_bytes(b'video')
    monkeypatch.setattr(api.providers,'video',video)
    monkeypatch.setattr(api.providers,'has_audio',lambda path: True)
    monkeypatch.setattr(api.providers,'duration',lambda path: 5)
    jid = store.enqueue(p['id'],'alice','video')
    api.run_job(jid,p['id'],{'id':'alice','limits':{'video':2}},'video','s1')
    assert store.jobs(p['id'])[0]['state'] == 'completed'


def test_old_left_right_review_cannot_block_adoption_under_new_policy(setup):
    store, client = setup
    p = spatial_pair(store)
    shot = p['shots'][0]
    candidate = {'id':'candidate','image':'new.png','mode':'redesign','prompt':'new prompt',
                 'shot':{k: copy.deepcopy(shot[k]) for k in api.ShotInput.model_fields},
                 'stamp':api.proposal_stamp(p,shot),'style_check':{'regions':{'staging':{'status':'deviates'}}}}
    shot['image_proposal'] = candidate
    store.asset(p['id'],'new.png').write_bytes(b'image')
    store.save(p)
    base = f"/api/ink/projects/{p['id']}"
    assert client.get(base).json()['shots'][0]['image_proposal']['style_check'] is None
    assert client.post(base+'/shots/s1/adopt',json={'candidate_id':'candidate'}).status_code == 200


def test_recheck_old_candidate_against_new_geography_allows_adoption(setup, monkeypatch):
    store, client = setup
    p = spatial_pair(store)
    shot = p['shots'][0]
    old_stamp = api.proposal_stamp(p,shot)
    p['spatial_version'] = 1
    shot['image_proposal'] = {'id':'candidate','image':'candidate.png','mode':'redesign','prompt':'candidate',
        'shot':{k:copy.deepcopy(shot[k]) for k in api.ShotInput.model_fields}, 'stamp':old_stamp}
    store.asset(p['id'],'candidate.png').write_bytes(b'image')
    store.save(p)
    monkeypatch.setattr(api.providers,'review_style',lambda *args,**kwargs: {'spatial_policy':2,'regions':{'staging':{'status':'consistent'}},'message':'关系一致','techniques':[],'uncertainties':[]})
    base = f"/api/ink/projects/{p['id']}/shots/s1"
    response = client.post(base+'/check-style',json={'candidate_id':'candidate'})
    assert response.status_code == 200
    assert client.post(base+'/adopt',json={'candidate_id':'candidate'}).status_code == 200


def video_edit_setup(setup, monkeypatch):
    from scenarios.ink_drama import video_editing
    store, client = setup
    p = project(store); s = p['shots'][0]
    s.update(image='frame.png', clip='current.mp4', rendered='dub.mp4',
             clip_versions=['old.mp4'], image_stale=False, clip_stale=False, rendered_stale=False)
    p['final'] = 'final.mp4'; p['final_stale'] = False
    for name in ('current.mp4', 'dub.mp4', 'old.mp4', 'other.mp4'):
        store.asset(p['id'], name).write_bytes(name.encode())
    store.save(p)
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    monkeypatch.setattr(api.providers, 'duration', lambda path: 3.0)
    monkeypatch.setattr(video_editing, 'ensure_available', lambda: None)
    return store, client, p, s, f"/api/ink/projects/{p['id']}/shots/{s['id']}"


def test_video_edit_preview_preserves_source_then_adopts_without_generation(setup, monkeypatch):
    from scenarios.ink_drama import video_editing
    store, client, p, s, base = video_edit_setup(setup, monkeypatch)
    calls = []
    def edit(source, instruction, target, project):
        calls.append((source.name, instruction)); target.write_bytes(b'edited')
    monkeypatch.setattr(video_editing, 'edit_video', edit)
    response = client.post(base+'/preview-video', json={'video':'old.mp4','revision':s['revision'], 'instruction':'仅放慢右手接伞动作'})
    assert response.status_code == 200
    data = response.json(); shot = data['shots'][0]; candidate = shot['video_proposal']
    assert calls == [('old.mp4', '仅放慢右手接伞动作')]
    assert shot['clip'] == 'current.mp4' and shot['rendered'] == 'dub.mp4'
    assert not data['final_stale'] and shot['revision'] == s['revision']
    assert data['jobs'][0]['state'] == 'completed'
    assert client.get(candidate['source_url']).content == b'old.mp4'
    assert client.get(candidate['video_url']).content == b'edited'
    assert client.get('/api/ink/projects/'+p['id']).json()['shots'][0]['video_proposal']['id'] == candidate['id']
    assert client.post(base+'/adopt-video-candidate',json={'candidate_id':'wrong'}).status_code == 409
    adopted = client.post(base+'/adopt-video-candidate',json={'candidate_id':candidate['id']}).json()
    selected = adopted['shots'][0]
    assert selected['clip'] == selected['rendered'] == candidate['video']
    assert selected['video_proposal'] is None and selected['video_edit_draft'] is None
    assert selected['media_step'] == 'complete' and not selected['clip_stale'] and not selected['rendered_stale']
    assert adopted['final_stale'] and len(calls) == 1
    assert selected['duration'] == 3
    assert store.asset(p['id'], 'dub.mp4').read_bytes() == b'dub.mp4'
    history = client.get(base+'/video-history').json()['videos']
    assert next(v for v in history if v['video'] == candidate['video'])['kind'] == 'edited'
    assert {'current.mp4', 'dub.mp4', 'old.mp4'} <= {v['video'] for v in history}


def test_video_edit_guards_source_busy_revision_blank_and_readonly(setup, monkeypatch):
    from scenarios.ink_drama import video_editing
    store, client, p, s, base = video_edit_setup(setup, monkeypatch)
    monkeypatch.setattr(video_editing, 'edit_video', lambda *a: pytest.fail('invalid input must not call model'))
    body = dict(video='other.mp4', revision=s['revision'], instruction='抬右手')
    assert client.post(base+'/preview-video',json=body).status_code == 422
    body.update(video='old.mp4', instruction='  ')
    assert client.post(base+'/preview-video',json=body).status_code == 422
    body.update(instruction='抬右手', revision=s['revision']+1)
    assert client.post(base+'/preview-video',json=body).status_code == 409
    body['revision'] = s['revision']
    jid = store.enqueue(p['id'], 'alice', 'video')
    assert client.post(base+'/preview-video',json=body).status_code == 409
    store.finish(jid)
    monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
    client.post('/api/ink/login',json={'token':'bob-test'})
    assert client.post(base+'/preview-video',json=body).status_code == 403


def test_video_edit_failure_discard_and_stale_candidate_preserve_media(setup, monkeypatch):
    from scenarios.ink_drama import video_editing
    store, client, p, s, base = video_edit_setup(setup, monkeypatch)
    def edit(source, instruction, target, project): target.write_bytes(b'candidate')
    monkeypatch.setattr(video_editing, 'edit_video', edit)
    body = dict(video='old.mp4', revision=s['revision'], instruction='抬右手')
    data = client.post(base+'/preview-video',json=body).json()
    first = data['shots'][0]['video_proposal']
    def failed(*a): raise UserError('测试：编辑失败')
    monkeypatch.setattr(video_editing, 'edit_video', failed)
    data = client.post(base+'/preview-video',json=body).json()
    assert data['jobs'][0]['state'] == 'failed'
    assert data['shots'][0]['video_proposal']['id'] == first['id']
    assert data['shots'][0]['video_edit_draft']['instruction'] == '抬右手'
    # Changing the shot invalidates adoption, even though candidate files remain.
    p = store.load(p['id']); p['shots'][0]['revision'] += 1; store.save(p)
    assert client.post(base+'/adopt-video-candidate',json={'candidate_id':first['id']}).status_code == 409
    data = client.post(base+'/discard-video-candidate',json={'candidate_id':first['id']}).json()
    assert data['shots'][0]['clip'] == 'current.mp4' and data['shots'][0]['rendered'] == 'dub.mp4'
    assert not data['final_stale']
    assert first['video'] in {v['video'] for v in client.get(base+'/video-history').json()['videos']}


def test_video_edit_replacement_archives_previous_candidate(setup, monkeypatch):
    from scenarios.ink_drama import video_editing
    store, client, p, s, base = video_edit_setup(setup, monkeypatch)
    monkeypatch.setattr(video_editing, 'edit_video', lambda source, instruction, target, project: target.write_bytes(b'edited'))
    body = dict(video='old.mp4', revision=s['revision'], instruction='抬右手')
    first = client.post(base+'/preview-video',json=body).json()['shots'][0]['video_proposal']
    second = client.post(base+'/preview-video',json=body).json()['shots'][0]['video_proposal']
    assert first['id'] != second['id']
    history = client.get(base+'/video-history').json()['videos']
    assert first['video'] in {v['video'] for v in history}
    assert second['video'] not in {v['video'] for v in history}
    assert client.post(base+'/adopt-video-candidate',json={'candidate_id':first['id']}).status_code == 409
