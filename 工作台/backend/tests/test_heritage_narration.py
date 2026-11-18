from types import SimpleNamespace

import pytest

from scenarios.heritage_study import media
from scenarios.heritage_study.narration import DEFAULT_VOICE, VOICE_PROFILES, profile
from scenarios.ink_drama.dialogue import NARRATOR
from scenarios.ink_drama.providers import Providers
from test_ink_demo import api, project, setup


def narration_project(store):
    p = project(store)
    p.update(project_type='heritage', characters=[])
    p['shots'][0].update(clip='native.mp4', rendered='native.mp4',
        audio_source='original', character_ids=[],
        dialogues=[dict(character_id=NARRATOR, text='一起来找斗拱吧。')])
    store.asset(p['id'], 'native.mp4').write_bytes(b'original video and voice')
    store.save(p)
    return p


@pytest.mark.parametrize('voice', [None, *VOICE_PROFILES])
def test_same_profile_replaces_native_shot_and_all_three_export_chapters(setup, monkeypatch, voice):
    store, _ = setup
    p = narration_project(store)
    if voice: p['voices'] = {NARRATOR: voice}
    chosen = profile(p)
    calls = []
    def speak(text, voice, target, *, speed):
        calls.append((text, voice, speed))
        target.write_bytes(b'dubbed audio')
    monkeypatch.setattr(api.providers, 'speak', speak)
    monkeypatch.setattr(api.providers, 'duration', lambda _: 1)
    monkeypatch.setattr(api.providers, 'has_audio', lambda _: True)
    monkeypatch.setattr(api.providers, 'render', lambda clip, lines, folder, target, **kwargs: target.write_bytes(b'new dub'))
    shot = p['shots'][0]
    api.add_shot_sound(p, shot, {'id':'alice','limits':{'speech':8}}, store.folder(p['id']), 'test')
    assert calls == [('一起来找斗拱吧。', chosen['voice'], chosen['speed'])]
    assert shot['clip'] == 'native.mp4' and shot['rendered'] != shot['clip']
    assert shot['audio_source'] == 'tts' and shot['narration_profile'] == chosen
    assert store.asset(p['id'], 'native.mp4').read_bytes() == b'original video and voice'
    assert 'native.mp4' in shot['clip_versions'] or shot['clip'] == 'native.mp4'

    def ffmpeg(args):
        from pathlib import Path
        Path(args[-1]).write_bytes(b'assembled with unified narration')
    monkeypatch.setattr(media, 'checked_ffmpeg', ffmpeg)
    facade = SimpleNamespace(providers=api.providers, call=lambda user, kind, pid, fn: fn())
    movie = store.folder(p['id'])/'movie.mp4';movie.write_bytes(b'old export')
    media.add_voiceover(facade, p, dict(intro='历史', location='观察', task='任务'), movie, {})
    assert calls[1:] == [(text, chosen['voice'], chosen['speed']) for text in ('历史','观察','任务')]
    assert movie.read_bytes() == b'assembled with unified narration'


def test_heritage_voice_change_invalidates_native_sound_without_touching_picture(setup):
    store, client = setup
    p = narration_project(store);p['final']='old.mp4';store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    response = client.post(base+'/voices', json={'voices':{NARRATOR:'zh-CN-YunxiNeural'}})
    assert response.status_code == 200, response.text
    saved = store.load(p['id']);shot = saved['shots'][0]
    assert shot['rendered_stale'] and saved['final_stale']
    assert not shot.get('clip_stale') and not shot.get('image_stale')
    assert shot['clip'] == shot['rendered'] == 'native.mp4'
    assert response.json()['heritage_narration']['voice'] == 'zh-CN-YunxiNeural'
    # Saving the same choice cannot invalidate an already updated dub again.
    shot['rendered_stale']=False;saved['final_stale']=False;store.save(saved)
    client.post(base+'/voices', json={'voices':{NARRATOR:'zh-CN-YunxiNeural'}})
    assert not store.load(p['id'])['shots'][0]['rendered_stale']


def test_heritage_default_is_public_without_rewriting_saved_project(setup):
    store, client = setup
    p = narration_project(store)
    result = client.get(f'/api/ink/projects/{p["id"]}').json()
    assert result['heritage_narration']['voice'] == DEFAULT_VOICE
    assert result['heritage_narration']['speed'] == .95
    assert 'voices' not in store.load(p['id'])
    assert store.load(p['id'])['shots'][0]['audio_source'] == 'original'


def test_speech_failure_preserves_original_video_and_selected_render(setup, monkeypatch):
    store, _ = setup;p = narration_project(store)
    def fail(*args, **kwargs):raise ValueError('offline')
    monkeypatch.setattr(api.providers, 'speak', fail)
    jid = store.enqueue(p['id'], 'alice', 'sound')
    api.run_job(jid, p['id'], {'id':'alice','limits':{'speech':2}}, 'sound', p['shots'][0]['id'])
    saved = store.load(p['id'])['shots'][0]
    assert store.jobs(p['id'])[0]['state'] == 'failed'
    assert saved['clip'] == saved['rendered'] == 'native.mp4'
    assert saved['audio_source'] == 'original'


def test_full_film_dubbing_reuses_picture_without_requiring_per_shot_redubbing(setup):
    from scenarios.ink_drama.domain import UserError
    store, _ = setup;p=narration_project(store);p['shots']=p['shots'][:1]
    shot=p['shots'][0];shot['rendered_stale']=True
    assert media.story_clips(api,p,True)==[store.asset(p['id'],'native.mp4')]
    with pytest.raises(UserError):media.story_clips(api,p,False)
    # Audio replacement never excuses an outdated image or video.
    shot['clip_stale']=True
    with pytest.raises(UserError):media.story_clips(api,p,True)


def test_provider_forwards_profile_speed_to_tts(monkeypatch, tmp_path):
    from pipelines import tts
    received=[]
    async def generate(text, target, *, voice, speed):received.append((voice,speed))
    monkeypatch.setattr(tts, 'generate_edge_tts', generate)
    Providers().speak('一起找斗拱', DEFAULT_VOICE, tmp_path/'speech.mp3', speed=.95)
    assert received == [(DEFAULT_VOICE,.95)]


def test_new_heritage_video_avoids_random_native_narrator(setup, monkeypatch):
    store, _ = setup;p = narration_project(store);shot=p['shots'][0];shot['image']='frame.png';store.save(p)
    monkeypatch.setattr(api, 'video_model', lambda _: 'wan2.7-i2v')
    monkeypatch.setattr(api, 'video_durations', lambda _: [5])
    monkeypatch.setattr(api, 'video_inputs', lambda *args:(None,None))
    def video(image, prompt, target, **kwargs):
        assert '统一旁白将在后期添加' in prompt and '画外旁白' not in prompt
        target.write_bytes(b'video')
    monkeypatch.setattr(api.providers,'speak',lambda *args,**kwargs:None)
    monkeypatch.setattr(api.providers,'video',video)
    monkeypatch.setattr(api.providers,'duration',lambda _:5)
    monkeypatch.setattr(api,'add_shot_sound',lambda *args:None)
    jid=store.enqueue(p['id'],'alice','video')
    api.run_job(jid,p['id'],{'id':'alice','limits':{'video':2,'speech':2}},'video',shot['id'])
    assert store.jobs(p['id'])[0]['state']=='completed'


@pytest.mark.parametrize('changed_during_export',[False,True])
def test_export_route_uses_selected_voice_and_rejects_a_mid_export_change(setup,monkeypatch,changed_during_export):
    from test_heritage_study import prepared
    from scenarios.heritage_study import api as study_api
    store,client=setup;p=prepared(setup)
    p=store.load(p['id']);p.update(voices={NARRATOR:'zh-CN-YunxiNeural'},final='old.mp4')
    store.asset(p['id'],'old.mp4').write_bytes(b'old export');store.save(p)
    class Immediate:
        def submit(self,fn,*args):fn(*args)
    monkeypatch.setattr(api,'pool',Immediate())
    def video(api,p,station,script,folder,target,*,replace_narration):
        assert replace_narration
        target.write_bytes(b'new video');return []
    def voiceover(api,p,script,target,user):
        assert profile(p)['voice']=='zh-CN-YunxiNeural'
        target.write_bytes(b'new unified narration')
        if changed_during_export:
            current=store.load(p['id']);current['voices'][NARRATOR]=DEFAULT_VOICE;store.save(current)
    monkeypatch.setattr(study_api,'export_video',video)
    monkeypatch.setattr(media,'add_voiceover',voiceover)
    result=client.post(f'/api/ink/projects/{p["id"]}/heritage/export',json={
        'version':p['heritage_version'],'kind':'video','narration':True}).json()
    if changed_during_export:
        assert result['jobs'][0]['state']=='failed'
        assert '讲解音色变化' in result['jobs'][0]['error']
        assert result['final']=='old.mp4'
    else:
        assert result['jobs'][0]['state']=='completed'
        assert result['heritage_export_voice']['voice']=='zh-CN-YunxiNeural'
        assert result['heritage_audio_policy']=='narration'
    assert store.asset(p['id'],'old.mp4').read_bytes()==b'old export'


def test_overlong_narration_stops_before_video_request(setup, monkeypatch):
    store, _ = setup
    p = narration_project(store)
    shot = p['shots'][0]
    shot.update(duration=2, image='frame.png')
    store.save(p)
    monkeypatch.setattr(api, 'video_durations', lambda _: [2])
    monkeypatch.setattr(api, 'video_inputs', lambda *args: (None, None))
    monkeypatch.setattr(api.providers, 'speak', lambda *args, **kwargs: None)
    monkeypatch.setattr(api.providers, 'duration', lambda _: 3.5)
    monkeypatch.setattr(api.providers, 'video', lambda *args, **kwargs: pytest.fail('unexpected video call'))
    jid = store.enqueue(p['id'], 'alice', 'video')
    api.run_job(jid, p['id'], {'id':'alice','limits':{'speech':2,'video':2}}, 'video', shot['id'])
    assert '配音累计3.5秒，超过2秒' in store.jobs(p['id'])[0]['error']
    assert store.load(p['id'])['shots'][0]['clip'] == 'native.mp4'
