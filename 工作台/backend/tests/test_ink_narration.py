import copy
import json

import pytest
from core.agents.storyboard_agent import StoryboardAgent
from scenarios.ink_drama.domain import ShotInput, UserError, board
from scenarios.ink_drama.dialogue import NARRATOR, native_dialogue_prompt
from scenarios.ink_drama.storyboard import split_storyboard
from test_ink_demo import api, project, setup


def fields(speaker=NARRATOR):
    return dict(duration=5, content='保国寺殿内梁架', scene='保国寺大殿', camera='仰拍特写',
                motion='固定镜头，光线缓缓变化', character_ids=[],
                dialogues=[dict(character_id=speaker, text='保国寺大殿重建于北宋。')])


@pytest.mark.parametrize('speaker', [NARRATOR, '旁白', '解说', '画外音', 'Narrator', 'voiceover'])
def test_audio_only_narration_needs_no_visible_character(speaker):
    result = board(json.dumps(dict(characters=[], shots=[fields(speaker)]), ensure_ascii=False))
    assert result['characters'] == []
    assert result['shots'][0]['character_ids'] == []
    assert result['shots'][0]['dialogues'][0]['character_id'] == NARRATOR


@pytest.mark.parametrize('speaker', ['c1', 'unknown'])
def test_regular_or_unknown_dialogue_still_requires_visible_defined_character(speaker):
    with pytest.raises(UserError, match='台词角色必须出现在镜头中'):
        board(json.dumps(dict(characters=[], shots=[fields(speaker)])))


@pytest.mark.parametrize('cast_narrator', [False, True])
def test_full_storyboard_pipeline_preserves_narration_without_cast_or_retries(cast_narrator):
    source = dict(characters=[dict(id='c1', name='旁白', desc='画外音')] if cast_narrator else [],
                  settings=[dict(name='保国寺大殿')], script='**第1集-第1场 日 内 保国寺大殿**\n人物：无\n旁白（平静）：保国寺大殿重建于北宋。')
    agent = StoryboardAgent()
    _, units = agent._annotate_episode_script(source['script'], [], source['settings'])
    plans = agent._validate_segment_plan(1, [dict(unit_ids=[unit['unit_id'] for unit in units])], units)
    designs = [agent._fallback_design_segment(1, plan) for plan in plans]
    frame = fields('c1' if cast_narrator else '旁白')
    if cast_narrator: frame['character_ids'] = ['c1']
    replies = [source, [dict(unit_ids=[unit['unit_id'] for unit in units])], *designs, dict(patches=[]),
               *[copy.deepcopy(frame) for design in designs for _ in design['shots']], dict(patches=[])]
    prompts = []
    def query(prompt):
        prompts.append(prompt)
        return json.dumps(replies[len(prompts)-1], ensure_ascii=False)
    result = split_storyboard('保国寺大殿重建于北宋。', query)
    assert len(prompts) == len(replies)
    assert all('character_id固定为narrator' in prompt for prompt in prompts)
    assert result['characters'] == [] and result['shots']
    assert all(shot['character_ids'] == [] for shot in result['shots'])
    assert all(shot['dialogues'][0]['text'] == '保国寺大殿重建于北宋。' for shot in result['shots'])
    assert all(shot['dialogues'][0]['character_id'] == NARRATOR for shot in result['shots'])


def test_narration_can_be_added_edited_and_kept_in_image_adjustment(setup, monkeypatch):
    store, client = setup
    p = project(store)
    p.update(characters=[], baseline={'version':1,'characters':[],'ink_style':{}})
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    result = client.post(base + '/shots', json=fields('旁白'))
    assert result.status_code == 200, result.text
    shot = result.json()['shots'][-1]
    changed = {**fields(), 'dialogues': [dict(character_id=NARRATOR, text='沿柱子向上观察斗拱。')]}
    result = client.patch(base + '/shots/' + shot['id'], json=changed)
    assert result.status_code == 200, result.text
    assert result.json()['shots'][-1]['dialogues'] == changed['dialogues']
    monkeypatch.setattr(api.pool, 'submit', lambda *args: None)  # Only validate and save the draft.
    result = client.post(base + '/shots/' + shot['id'] + '/preview', json=dict(mode='redesign', instruction='', shot=changed))
    assert result.status_code == 200, result.text
    assert result.json()['shots'][-1]['image_draft']['shot']['dialogues'] == changed['dialogues']


def test_narrator_voice_and_tts_subtitles_work_without_cast(setup, monkeypatch):
    store, client = setup
    p = project(store)
    p['characters'] = []
    shot = p['shots'][0]
    shot.update(fields(), clip='silent.mp4', rendered='older.mp4')
    store.asset(p['id'], 'silent.mp4').write_bytes(b'test clip')
    store.save(p)
    result = client.post(f'/api/ink/projects/{p["id"]}/voices', json=dict(voices={NARRATOR:'zh-CN-XiaoxiaoNeural'}))
    assert result.status_code == 200, result.text
    spoken = []
    monkeypatch.setattr(api.providers, 'has_audio', lambda _: False)
    def speak(text, voice, target):
        spoken.append((text,voice)); target.write_bytes(b'test audio')
    monkeypatch.setattr(api.providers, 'speak', speak)
    monkeypatch.setattr(api.providers, 'duration', lambda _: 2.5)
    def render(clip, lines, folder, target, **kwargs):
        assert lines[0][0] == fields()['dialogues'][0]['text']
        target.write_bytes(b'test rendered narration and subtitles')
    monkeypatch.setattr(api.providers, 'render', render)
    jid = store.enqueue(p['id'], 'alice', 'sound')
    api.run_job(jid, p['id'], {'id':'alice','limits':{'speech':2}}, 'sound', shot['id'])
    saved = store.load(p['id'])
    assert store.jobs(p['id'])[0]['state'] == 'completed'
    assert spoken == [(fields()['dialogues'][0]['text'],'zh-CN-XiaoxiaoNeural')]
    assert saved['characters'] == [] and saved['shots'][0]['audio_source'] == 'tts'
    assert saved['shots'][0]['clip'] == 'silent.mp4'


def test_native_video_narration_keeps_picture_empty_and_original_audio(setup, monkeypatch):
    store, _ = setup
    p = project(store); p['characters'] = []
    shot = p['shots'][0]; shot.update(fields(), image='frame.png')
    store.save(p)
    monkeypatch.setattr(api, 'video_model', lambda _: 'wan2.7-i2v')
    monkeypatch.setattr(api, 'video_durations', lambda _: [5])
    monkeypatch.setattr(api, 'video_inputs', lambda *args: (None, None))
    def video(image, motion, target, **kwargs):
        assert '画外旁白' in motion and '不新增出镜人物，不安排人物口型' in motion
        assert '旁白：“保国寺大殿重建于北宋。”' in motion
        assert '同期对白' not in motion
        target.write_bytes(b'test native video')
    monkeypatch.setattr(api.providers, 'video', video)
    monkeypatch.setattr(api.providers, 'duration', lambda _: 5)
    monkeypatch.setattr(api.providers, 'has_audio', lambda _: True)
    monkeypatch.setattr(api.providers, 'speak', lambda *args: pytest.fail('Do not dub native narration twice'))
    jid = store.enqueue(p['id'], 'alice', 'video')
    api.run_job(jid,p['id'],{'id':'alice','limits':{'video':2}},'video',shot['id'])
    saved = store.load(p['id'])['shots'][0]
    assert store.jobs(p['id'])[0]['state'] == 'completed'
    assert saved['audio_source'] == 'original' and saved['rendered'] == saved['clip']


def test_mixed_native_speech_preserves_narrative_order():
    lines = [dict(character_id=NARRATOR,text='先讲历史'),dict(character_id='c1',text='再找斗拱'),dict(character_id=NARRATOR,text='最后观察')]
    prompt = native_dialogue_prompt([dict(id='c1',name='学生')],lines)
    assert prompt.index('先讲历史') < prompt.index('再找斗拱') < prompt.index('最后观察')
    assert '对应人物口型' in prompt and '不安排人物口型' in prompt
