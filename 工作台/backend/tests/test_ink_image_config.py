import copy

import pytest

from config import Config
from models.image_client import ImageClient
from models.config_model import MODEL_CONFIG
from scenarios.ink_drama.domain import UserError
from scenarios.ink_drama.providers import Providers
from test_ink_demo import setup, api, project


@pytest.mark.parametrize('refs', [[], ['reference.png']])
def test_missing_image_key_stops_before_client_and_names_the_required_provider(monkeypatch, tmp_path, refs):
    monkeypatch.setattr(Config, 'IMAGE_T2I_MODEL', 'doubao-seedream-5-0-260128')
    monkeypatch.setattr(Config, 'IMAGE_IT2I_MODEL', 'doubao-seedream-5-0-260128')
    monkeypatch.setattr(Config, 'ARK_API_KEY', '')
    monkeypatch.setattr(Config, 'DEEPSEEK_API_KEY', 'test-text-key')
    def unexpected_client(self, *args, **kwargs):
        pytest.fail('A missing credential must never initialize a generation client')
    monkeypatch.setattr(ImageClient, '__init__', unexpected_client)
    with pytest.raises(UserError, match='火山方舟 Ark.*尚未配置 API Key') as error:
        Providers().image('测试画面', refs, tmp_path, 'test')
    assert '右上角“模型与 API”' in str(error.value)
    assert 'test-text-key' not in str(error.value)
    assert not list(tmp_path.iterdir())


def test_image_to_image_checks_its_own_provider_instead_of_the_text_image_key(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'IMAGE_T2I_MODEL', 'doubao-seedream-5-0-260128')
    monkeypatch.setattr(Config, 'IMAGE_IT2I_MODEL', 'wan2.7-image')
    monkeypatch.setattr(Config, 'ARK_API_KEY', 'test-ark-key')
    monkeypatch.setattr(Config, 'DASHSCOPE_API_KEY', '')
    requests = []
    def generate(self, **kwargs):
        requests.append(kwargs)
        return [str(tmp_path / 'generated.png')]
    monkeypatch.setattr(ImageClient, 'generate_image', generate)
    Providers().image('测试画面', [], tmp_path, 'test')
    with pytest.raises(UserError, match='阿里云百炼 DashScope.*尚未配置 API Key'):
        Providers().image('测试画面', ['reference.png'], tmp_path, 'test')
    assert len(requests) == 1
    assert requests[0]['model'] == 'doubao-seedream-5-0-260128'


@pytest.mark.parametrize('model, registered', [('custom-image-endpoint', True), ('doubao-seedream-custom', False)])
def test_image_key_check_respects_registered_provider_and_legacy_model_aliases(monkeypatch, tmp_path, model, registered):
    monkeypatch.setattr(Config, 'IMAGE_T2I_MODEL', model)
    monkeypatch.setattr(Config, 'ARK_API_KEY', '')
    if registered:
        monkeypatch.setitem(MODEL_CONFIG['models'], model, {'provider': 'ark'})
    with pytest.raises(UserError, match='火山方舟 Ark.*尚未配置 API Key'):
        Providers().image('测试画面', [], tmp_path, 'test')


def test_configured_provider_empty_result_keeps_the_distinct_service_error(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'IMAGE_T2I_MODEL', 'doubao-seedream-5-0-260128')
    monkeypatch.setattr(Config, 'ARK_API_KEY', 'test-ark-key')
    monkeypatch.setattr(ImageClient, 'generate_image', lambda self, **kwargs: [])
    with pytest.raises(UserError, match='火山方舟 Ark.*响应中未包含可用图片'):
        Providers().image('测试画面', [], tmp_path, 'test')


def test_missing_image_key_job_preserves_existing_setting_image_without_consuming_usage(setup, monkeypatch):
    store, client = setup
    monkeypatch.setattr(Config, 'IMAGE_IT2I_MODEL', 'doubao-seedream-5-0-260128')
    monkeypatch.setattr(Config, 'ARK_API_KEY', '')
    monkeypatch.setattr(api, 'providers', Providers())
    class Immediate:
        def submit(self, fn, *args):
            fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    def unexpected_generation(self, **kwargs):
        pytest.fail('The job must stop before any image generation request')
    monkeypatch.setattr(ImageClient, 'generate_image', unexpected_generation)
    p = project(store)
    settings = dict(characters=[], scenes=[dict(id='scene1', name='大殿', desc='寺门与屋檐', image='existing.png')], props=[], style='兼工带写')
    p['creative_settings'] = copy.deepcopy(settings)
    store.asset(p['id'], 'existing.png').write_bytes(b'original-image')
    store.save(p)
    response = client.post(f"/api/ink/projects/{p['id']}/generate-setting-image", json=dict(settings=settings, group='scenes', asset_id='scene1'))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['jobs'][0]['state'] == 'failed'
    assert '火山方舟 Ark' in result['jobs'][0]['error'] and '模型与 API' in result['jobs'][0]['error']
    assert store.load(p['id'])['creative_settings'] == settings
    assert store.load(p['id'])['creative_draft']['scenes'][0]['desc'] == '寺门与屋檐'
    assert store.asset(p['id'], 'existing.png').read_bytes() == b'original-image'
    assert store.usage('alice').get('image', 0) == 0


def test_image_request_failure_after_preflight_still_keeps_call_history(setup, monkeypatch):
    store, client = setup
    monkeypatch.setattr(Config, 'IMAGE_T2I_MODEL', 'doubao-seedream-5-0-260128')
    monkeypatch.setattr(Config, 'ARK_API_KEY', 'test-ark-key')
    monkeypatch.setattr(api, 'providers', Providers())
    def fail(self, **kwargs):
        raise RuntimeError('provider request failed')
    monkeypatch.setattr(ImageClient, 'generate_image', fail)
    p = project(store)
    with pytest.raises(RuntimeError, match='provider request failed'):
        api.call_image(dict(id='alice', limits={'image':2}, trial_mode=True), p['id'], '测试画面', [], store.folder(p['id']))
    assert store.usage('alice').get('image', 0) == 1
