import copy
from types import SimpleNamespace

import pytest
import requests

from config import Config
from models.image_client import ImageClient
from models.image_dashscope import DashScopeClient, ImageGeneration
from models.image_failures import ImageFailure, exception_failure
from scenarios.ink_drama.domain import UserError
from scenarios.ink_drama.providers import Providers
from test_ink_demo import setup, api, project


@pytest.fixture
def configured_image(monkeypatch):
    monkeypatch.setattr(Config, 'IMAGE_T2I_MODEL', 'wan2.7-image')
    monkeypatch.setattr(Config, 'IMAGE_IT2I_MODEL', 'wan2.7-image')
    monkeypatch.setattr(Config, 'DASHSCOPE_API_KEY', 'test-image-key')


@pytest.mark.parametrize('refs,stage', [([], 'request'), (['reference.png'], 'upload')])
def test_ssl_error_survives_sdk_and_facade_without_exposing_request_data(configured_image, monkeypatch, tmp_path, refs, stage):
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        url = 'https://example.test/api/v1/uploads?token=private-fixture' if refs else 'https://example.test/generate?token=private-fixture'
        raise requests.exceptions.SSLError('[SSL: UNEXPECTED_EOF_WHILE_READING] ' + url)
    monkeypatch.setattr(ImageGeneration, 'call', fail)
    with pytest.raises(UserError, match='安全连接中断（TLS/SSL）') as caught:
        Providers().image('测试画面', refs, tmp_path, 'test')
    text = str(caught.value)
    assert '阿里云百炼 DashScope' in text
    assert ('上传参考图时' if stage == 'upload' else '请求生图时') in text
    assert 'private-fixture' not in text and 'test-image-key' not in text and 'example.test' not in text
    assert len(calls) == 1


@pytest.mark.parametrize('status,code,reason', [
    (401, 'InvalidApiKey', 'API Key 无效或已失效'),
    (403, 'AccessDenied', '没有模型访问权限'),
    (400, 'Arrearage', '余额或可用配额不足'),
    (429, 'Throttling', '触发限流'),
    (404, 'ModelNotFound', '模型不存在'),
    (400, 'DataInspectionFailed', '内容审核拒绝'),
    (400, 'InvalidParameter', '未接受请求参数'),
    (503, 'ServiceUnavailable', '服务商暂时异常'),
])
def test_provider_http_failures_have_distinct_safe_messages(configured_image, monkeypatch, tmp_path, status, code, reason):
    response = SimpleNamespace(status_code=status, code=code, message='sensitive-fixture-token')
    monkeypatch.setattr(ImageGeneration, 'call', lambda **kwargs: response)
    with pytest.raises(UserError, match=reason) as caught:
        Providers().image('测试画面', ['reference.png'], tmp_path, 'test')
    assert f'HTTP {status}' in str(caught.value)
    assert 'sensitive-fixture-token' not in str(caught.value)


def test_download_tls_error_is_not_misreported_as_empty_generation(configured_image, monkeypatch, tmp_path):
    response = SimpleNamespace(status_code=200, output=SimpleNamespace(choices=[{'message':{'content':[{'image':'https://example.test/image.png'}]}}]))
    monkeypatch.setattr(ImageGeneration, 'call', lambda **kwargs: response)
    def fail(*args, **kwargs):
        raise requests.exceptions.SSLError('certificate verify failed: private-download-token')
    monkeypatch.setattr('models.image_processor.ImageProcessor.download_image', fail)
    with pytest.raises(UserError, match='下载生成图片时证书校验失败') as caught:
        Providers().image('测试画面', [], tmp_path, 'test')
    assert 'private-download-token' not in str(caught.value)


def test_success_resets_a_previous_failure(configured_image, monkeypatch):
    client = DashScopeClient(api_key='test-image-key')
    monkeypatch.setattr(ImageGeneration, 'call', lambda **kwargs: SimpleNamespace(status_code=429, code='Throttling', message='limited'))
    assert client.generate_image('测试') == []
    assert client.last_error.kind == 'rate_limit'
    response = SimpleNamespace(status_code=200, output=SimpleNamespace(choices=[{'message':{'content':[{'image':'https://example.test/image.png'}]}}]))
    monkeypatch.setattr(ImageGeneration, 'call', lambda **kwargs: response)
    assert client.generate_image('测试') == ['https://example.test/image.png']
    assert client.last_error is None


@pytest.mark.parametrize('error,kind', [(requests.exceptions.ReadTimeout('private-fixture'), 'timeout'), (requests.exceptions.ConnectionError('private-fixture'), 'network')])
def test_transport_exception_types_and_unknown_errors_remain_safe(error, kind):
    failure = exception_failure(error)
    assert failure.kind == kind
    assert 'private-fixture' not in failure.message('服务商')
    assert 'private-fixture' not in exception_failure(RuntimeError('private-fixture')).message('服务商')


def test_wrapped_provider_failure_keeps_the_inner_diagnostic(configured_image, tmp_path):
    class Wrapped:
        last_error = ImageFailure('auth', status=401)
        def generate_image(self, **kwargs):
            raise RuntimeError('SDK wrapper lost the original exception: private-fixture')
    client = ImageClient()
    client._gpt_client = Wrapped()
    assert client.generate_image('测试', model='gpt-image-2', save_dir=str(tmp_path)) == []
    assert client.last_error.kind == 'auth'
    assert 'private-fixture' not in client.last_error.message('OpenAI')


def test_asset_job_records_tls_reason_and_keeps_original_image(setup, configured_image, monkeypatch):
    store, client = setup
    monkeypatch.setattr(api, 'providers', Providers())
    class Immediate:
        def submit(self, fn, *args):
            fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    def fail(**kwargs):
        raise requests.exceptions.SSLError('[SSL: UNEXPECTED_EOF_WHILE_READING] https://example.test/uploads?token=private-fixture')
    monkeypatch.setattr(ImageGeneration, 'call', fail)
    p = project(store)
    settings = dict(characters=[], scenes=[dict(id='scene1', name='大殿', desc='木构大殿', image='original.png')], props=[], style='兼工带写')
    p['creative_settings'] = copy.deepcopy(settings)
    store.asset(p['id'], 'original.png').write_bytes(b'original-image')
    store.save(p)
    result = client.post(f"/api/ink/projects/{p['id']}/generate-setting-image", json=dict(settings=settings, group='scenes', asset_id='scene1')).json()
    job = result['jobs'][0]
    assert job['state'] == 'failed' and '上传参考图时安全连接中断（TLS/SSL）' in job['error']
    assert 'private-fixture' not in job['error']
    assert store.asset(p['id'], 'original.png').read_bytes() == b'original-image'
    assert store.load(p['id'])['creative_settings'] == settings
    assert store.usage('alice').get('image', 0) == 1
