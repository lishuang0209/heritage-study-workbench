"""One narrator profile shared by shot dubbing and the three study chapters."""
from scenarios.ink_drama.dialogue import NARRATOR

DEFAULT_VOICE = 'zh-CN-XiaoxiaoNeural'
VOICE_PROFILES = {
    DEFAULT_VOICE: {'label': '晓晓 · 亲切女声（推荐）', 'speed': .95},
    'zh-CN-YunxiaNeural': {'label': '云夏 · 小学生男声', 'speed': 1.0},
    'zh-CN-YunxiNeural': {'label': '云希 · 自然男声', 'speed': .95},
    'zh-CN-YunjianNeural': {'label': '云健 · 沉稳男声', 'speed': 1.0},
}


def profile(project):
    voice = (project.get('voices') or {}).get(NARRATOR, DEFAULT_VOICE)
    if voice not in VOICE_PROFILES:
        voice = DEFAULT_VOICE
    return {'voice': voice, **VOICE_PROFILES[voice]}


def public_profile(project):
    return {**profile(project), 'choices': [dict(voice=voice, **details) for voice, details in VOICE_PROFILES.items()]}


def narrated_shot(project, shot):
    return project.get('project_type') == 'heritage' and any(
        line['character_id'] == NARRATOR for line in shot.get('dialogues', []))


def speak(provider, project, text, target):
    selected = profile(project)
    provider.speak(text, selected['voice'], target, speed=selected['speed'])
