"""No network: simulate the provider result, verify actual FFmpeg audio retention."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from scenarios.ink_drama.video_editing import edit_video
from scenarios.ink_drama.domain import UserError
from scenarios.ink_drama.providers import checked_ffmpeg, ffmpeg_executable, Providers


@pytest.mark.parametrize('with_audio', [True, False])
@pytest.mark.parametrize('project_type', ['ink', 'heritage'])
def test_edit_video_submits_source_once_and_retains_source_audio(tmp_path, monkeypatch, with_audio, project_type):
    from config import Config
    from dashscope import VideoSynthesis
    import requests
    monkeypatch.setattr(Config, 'DASHSCOPE_API_KEY', 'test-only')
    source, generated, target = [tmp_path / name for name in ('source.mp4', 'generated.mp4', 'candidate.mp4')]
    inputs = ['-f', 'lavfi', '-i', 'color=c=white:s=240x320:r=10:d=3']
    if with_audio: inputs += ['-f','lavfi','-i','sine=frequency=440:duration=3']
    checked_ffmpeg([*inputs, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)])
    # The simulated model result deliberately contains a different soundtrack.
    checked_ffmpeg(['-f','lavfi','-i','color=c=black:s=240x320:r=10:d=3',
                    '-f','lavfi','-i','sine=frequency=880:duration=3',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(generated)])
    submissions = []
    def submit(**kwargs):
        submissions.append(kwargs)
        return SimpleNamespace(status_code=200, output={'task_id':'task-test'})
    monkeypatch.setattr(VideoSynthesis, 'async_call', submit)
    monkeypatch.setattr(VideoSynthesis, 'fetch', lambda **kw: SimpleNamespace(status_code=200,
        output={'task_status':'SUCCEEDED','video_url':'https://provider.invalid/result.mp4'}))
    class Download:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield generated.read_bytes()
    monkeypatch.setattr(requests, 'get', lambda *a, **kw: Download())
    edit_video(source, '仅放慢右手动作', target, {'project_type':project_type,'creative_settings':{'style':'兼工带写'}})
    assert len(submissions) == 1
    request = submissions[0]
    assert request['model'] == 'wan2.7-videoedit'
    assert request['media'] == [{'type':'video','url':source.as_uri()}]
    assert request['audio_setting'] == 'origin' and request['prompt_extend'] is False
    assert 'duration' not in request and 'ratio' not in request
    assert '仅放慢右手动作' in request['prompt']
    assert Providers().has_audio(target) == with_audio
    from test_heritage_widescreen import media_size
    assert media_size(target) == ((1280,720) if project_type == 'heritage' else (240,320))
    if with_audio:
        def audio_bytes(path):
            return subprocess.check_output([ffmpeg_executable(),'-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','adts','pipe:1'])
        assert audio_bytes(target) == audio_bytes(source)
        assert audio_bytes(target) != audio_bytes(generated)
    record = json.loads(target.with_suffix('.request.json').read_text())
    assert record['task_id'] == 'task-test' and record['state'] == 'completed'
    assert 'api_key' not in record


def test_video_edit_submission_failure_does_not_retry(tmp_path, monkeypatch):
    from config import Config
    from dashscope import VideoSynthesis
    monkeypatch.setattr(Config, 'DASHSCOPE_API_KEY', 'test-only')
    calls = []
    def submit(**kw):
        calls.append(kw); raise TimeoutError('unknown outcome')
    monkeypatch.setattr(VideoSynthesis, 'async_call', submit)
    with pytest.raises(TimeoutError):
        edit_video(tmp_path/'source.mp4', '抬右手', tmp_path/'candidate.mp4', {})
    assert len(calls) == 1
