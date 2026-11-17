"""No paid calls: verify landscape requests, legacy media and real encoded output."""
import copy
import json
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from test_ink_demo import api, project, setup
from scenarios.ink_drama.domain import ShotInput
from scenarios.ink_drama.providers import Providers, checked_ffmpeg, ffmpeg_executable


def media_size(path):
    result = subprocess.run([ffmpeg_executable(), '-hide_banner', '-i', str(path)], capture_output=True, text=True)
    match = re.search(r'Video:.*?\b(\d{2,5})x(\d{2,5})\b', result.stderr)
    assert match, result.stderr
    return tuple(map(int, match.groups()))


def test_existing_heritage_switches_format_without_mutating_saved_media_or_old_ink(setup):
    store, client = setup
    old = project(store)
    before = copy.deepcopy(store.load(old['id']))
    p = copy.deepcopy(before)
    p.update(project_type='heritage', final='old-portrait.mp4')
    store.save(p)
    result = client.get('/api/ink/projects/' + p['id']).json()
    assert result['media_format'] == dict(ratio='16:9', width=1280, height=720)
    assert result['final_stale'] and result['final_url'].endswith('old-portrait.mp4')
    assert store.load(p['id']) == p
    store.save(before)
    result = client.get('/api/ink/projects/' + p['id']).json()
    assert result['media_format'] == dict(ratio='9:16', width=720, height=1280)
    assert store.load(p['id']) == before


def test_image_and_saved_storyboard_candidate_requests_both_use_wide_format(setup, monkeypatch):
    store, client = setup
    p = project(store)
    p.update(project_type='heritage')
    store.save(p)
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    requests = []
    def image(prompt, refs, folder, pid, ratio='9:16'):
        requests.append((prompt, ratio))
        path = folder / f'fake-{len(requests)}.png'
        Image.new('RGB', (1280, 720), 'white').save(path)
        return path
    monkeypatch.setattr(api.providers, 'image', image)
    sid = p['shots'][0]['id']
    base = f'/api/ink/projects/{p["id"]}'
    assert client.post(base + '/actions/image', params={'sid': sid}).status_code == 200
    saved = store.load(p['id'])
    old_image = saved['shots'][0]['image']
    assert old_image
    draft = ShotInput.model_validate({key:saved['shots'][0][key] for key in ShotInput.model_fields}).model_dump()
    result = client.post(base + f'/shots/{sid}/preview', json={'mode':'redesign', 'shot':draft})
    assert result.status_code == 200, result.text
    assert result.json()['jobs'][0]['state'] == 'completed'
    assert store.load(p['id'])['shots'][0]['image'] == old_image
    assert store.load(p['id'])['shots'][0]['image_proposal']
    assert len(requests) == 2
    assert all(ratio == '16:9' and '横屏16:9' in prompt for prompt, ratio in requests)


@pytest.mark.parametrize('mode', ['first_frame', 'start_end_frame', 'reference'])
def test_video_requests_and_first_last_frames_use_wide_canvas(tmp_path, monkeypatch, mode):
    from models.video_client import VideoClient
    original = tmp_path / 'portrait.png'
    Image.new('RGB', (180, 320), 'red').save(original)
    original_bytes = original.read_bytes()
    requests = []
    def generate(self, **request):
        requests.append(request)
        Path(request['save_path']).write_bytes(b'mock provider video')
    monkeypatch.setattr(VideoClient, 'generate_video', generate)
    target = tmp_path / 'result.mp4'
    Providers().video(original, '固定镜头', target, project={'project_type':'heritage'},
        mode=mode, last_image=original if mode == 'start_end_frame' else None,
        references=[str(original)] if mode == 'reference' else None)
    assert requests[0]['video_ratio'] == '16:9'
    if mode == 'reference':
        assert requests[0]['reference_image_paths'] == [str(original)]
    else:
        with Image.open(requests[0]['image_path']) as fitted:
            assert fitted.size == (1280, 720)
            assert fitted.getpixel((640,360)) == (255,0,0)
            assert fitted.getpixel((0,360)) == (250,248,242)
        if mode == 'start_end_frame':
            with Image.open(requests[0]['last_image_path']) as last:
                assert last.size == (1280,720)
    assert original.read_bytes() == original_bytes
    record = json.loads(target.with_suffix('.request.json').read_text())
    assert record['request']['video_ratio'] == '16:9'


def test_wide_render_subtitles_and_mixed_clip_assembly_preserve_frames_and_sound(tmp_path):
    media = Providers()
    portrait, wide, speech = [tmp_path/name for name in ('portrait.mp4','wide.mp4','speech.wav')]
    for path,size,color in ((portrait,'180x320','red'),(wide,'320x180','blue')):
        checked_ffmpeg(['-f','lavfi','-i',f'color=c={color}:s={size}:r=24:d=2',
            '-f','lavfi','-i','sine=frequency=440:duration=2', '-t','2',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)])
    checked_ffmpeg(['-f','lavfi','-i','sine=frequency=880:duration=1',str(speech)])
    rendered = tmp_path/'narrated.mp4'
    media.render(portrait,[('测试旁白',1,speech)],tmp_path,rendered,duration_seconds=2,ratio='16:9')
    assert media_size(rendered) == (1280,720) and media.has_audio(rendered)
    subtitles = rendered.with_suffix('.ass').read_text()
    assert 'PlayResX: 1920' in subtitles and 'PlayResY: 1080' in subtitles
    final = tmp_path/'final.mp4'
    media.assemble([rendered,wide],None,tmp_path,final,ratio='16:9')
    assert media_size(final) == (1280,720) and media.has_audio(final)
    assert abs(media.duration(final)-4) < .1
    def pixel(second, x):
        return subprocess.check_output([ffmpeg_executable(),'-v','error','-ss',str(second),'-i',str(final),
            '-frames:v','1','-vf',f'crop=1:1:{x}:300,format=rgb24','-f','rawvideo','pipe:1'])
    assert max(pixel(.5,100)) < 10  # Old portrait has side padding, not stretched content.
    for second, color in ((.5,(255,0,0)),(2.5,(0,0,255))):
        assert max(abs(a-b) for a,b in zip(pixel(second,640),color)) < 20
