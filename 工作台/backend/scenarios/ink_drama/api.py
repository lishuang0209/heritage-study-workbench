"""Private trial API for the ink scenario; never serves base config or keys."""
from __future__ import annotations

import copy
import json
import logging
import os
import secrets
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from typing import Literal
from functools import wraps
from threading import RLock

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from .domain import Caption, ShotInput, Store, UserError, caption, frame_prompt, image_edit_prompt, invalidate
from .spatial import SceneLayout, layouts_for, scene_key, spatial_prompt, planning_context, with_spatial_reference, spatial_reference_paths, SPATIAL_POLICY, PLANNING_MARKER
from .providers import Providers, video_durations, video_modes, video_model
from .styles import image_style, negative_style, with_style_reference, profile_for, check_material_styles, style_observation, check_frame_style, restyle_request, restyle_change_warning
from .background import background_context
from .identity import detail_request
from .dialogue import NARRATOR, NARRATION_RULE, invalid_speakers, native_dialogue_prompt
from .asset_history import remember as remember_setting_image, remember_settings, versions as setting_versions
from .creative import CreativeSettings, validate_settings, apply_settings, check_references, check_visible_characters
from .media_format import format_for, generation_options, frame_instruction
from .history_retention import annotated_versions

LOG = logging.getLogger(__name__)
router = APIRouter(prefix='/api/ink', tags=['Ink demo'])
store = Store(os.environ.get('SFA_INK_DATA_DIR') or Path(__file__).resolve().parents[2] / '.ink-demo')
store.recover()
providers = Providers()
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ink-demo')
VOICES = {'c1': 'zh-CN-YunjianNeural', 'c2': 'zh-CN-XiaoxiaoNeural', NARRATOR: 'zh-CN-YunjianNeural'}
ZERO = dict(text=0, vl=0, image=0, video=0, speech=0)
mutation_lock = RLock()

def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with mutation_lock:
            return fn(*args, **kwargs)
    return wrapped


def invites():
    data = json.loads(os.environ.get('SFA_INK_INVITES', '[]'))
    if not isinstance(data, list):
        raise HTTPException(503, '试用邀请配置无效')
    return data


def local(request):
    forwarded = request.headers.get('x-forwarded-for', '').split(',')[0].strip()
    return (request.client is not None and request.client.host in {'127.0.0.1', '::1', 'testclient'}
            and (not forwarded or forwarded in {'127.0.0.1', '::1'})
            and os.environ.get('SFA_INK_PUBLIC') != '1')


def origin_check(request):
    origin = request.headers.get('origin')
    if origin:
        allowed = {'http://127.0.0.1:3000', 'http://localhost:3000', 'http://127.0.0.1:3001', 'http://localhost:3001', os.environ.get('SFA_INK_ORIGIN', '')}
        if origin.rstrip('/') not in allowed:
            raise HTTPException(403, '请求来源不在试用范围内')


def trial_mode():
    return os.environ.get('SFA_INK_TRIAL_MODE') == '1'


# Local workspace settings. Never return secret values or expose settings to invitees.
SETTING_MODELS = {'llm': 'llm', 'vlm': 'vlm', 'image_t2i': 't2i', 'image_it2i': 'i2i', 'video_first_frame': 'video', 'video_start_end': 'video', 'video_reference': 'video'}


def settings_owner(request):
    origin_check(request)
    if not local(request) or trial_mode():
        raise HTTPException(403, '仅本机创作模式可以修改模型与 API 设置')


def model_choices():
    from config import PROVIDERS
    from models.config_model import load_model_config
    choices = {key: [] for key in SETTING_MODELS}
    for mid, info in load_model_config()['models'].items():
        types = info.get('type', [])
        if isinstance(types, str):
            types = [types]
        if info.get('provider') not in PROVIDERS:
            continue
        for key, kind in SETTING_MODELS.items():
            if kind not in types and not (key == 'llm' and 'vlm' in types):
                continue
            if key.startswith('video_'):
                capabilities = info.get('capabilities', {})
                abilities = capabilities.get('adapter_ability_types', capabilities.get('ability_types', []))
                ability = {'video_first_frame': 'first_frame_i2v', 'video_start_end': 'start_end_frame_i2v', 'video_reference': 'reference_to_video'}[key]
                if ability not in abilities or (key != 'video_first_frame' and info.get('provider') != 'dashscope'):
                    continue
            choices[key].append({'id': mid, 'name': info.get('name', mid), 'provider': info['provider']})
    return choices


def settings_view():
    from config import Config, PROVIDERS
    config = Config.as_dict()
    return {'models': {k: config['models'][k] for k in SETTING_MODELS},
            'choices': model_choices(), 'env_overrides': Config.ENV_OVERRIDDEN_PATHS,
            'providers': {key: {'label': spec['label'],
                'base_url': config['api_providers'][key].get('base_url', ''),
                'secrets': {field: bool(config['api_providers'][key].get(field)) for field in spec['secrets']}}
                for key, spec in PROVIDERS.items()}}


@router.get('/settings')
def get_ink_settings(request: Request, response: Response):
    settings_owner(request)
    response.headers['Cache-Control'] = 'no-store'
    return settings_view()


@router.put('/settings')
@serialized
def put_ink_settings(request: Request, response: Response, body: dict):
    from config import Config, PROVIDERS
    settings_owner(request)
    if any(store.busy(p['id']) for p in store.list()):
        raise HTTPException(409, '有生成任务正在进行，请完成后再保存设置')
    if set(body) - {'models', 'providers'}:
        raise HTTPException(422, '设置字段不支持')
    models, provider_updates = body.get('models', {}), body.get('providers', {})
    if not isinstance(models, dict) or not isinstance(provider_updates, dict):
        raise HTTPException(422, '设置格式无效')
    choices = model_choices()
    updates = {'models': {}, 'api_providers': {}}
    for key, value in models.items():
        if key not in choices or not isinstance(value, str) or value not in {m['id'] for m in choices[key]}:
            raise HTTPException(422, '请选择对应任务支持的模型')
        if 'models.' + key in Config.ENV_OVERRIDDEN_PATHS:
            raise HTTPException(409, '该模型由启动环境指定，暂不能从页面修改')
        updates['models'][key] = value
    for key, values in provider_updates.items():
        if key not in PROVIDERS or not isinstance(values, dict):
            raise HTTPException(422, '服务商设置无效')
        allowed = {'base_url', *PROVIDERS[key]['secrets']}
        if set(values) - allowed or any(not isinstance(v, str) or len(v) > 4096 for v in values.values()):
            raise HTTPException(422, '服务商字段无效')
        for field, value in values.items():
            if f'api_providers.{key}.{field}' in Config.ENV_OVERRIDDEN_PATHS:
                raise HTTPException(409, '该字段由启动环境指定，暂不能从页面修改')
            if field == 'base_url' and value:
                url = urlparse(value)
                if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise HTTPException(422, '接口地址需为 HTTP 或 HTTPS 地址，不能包含密钥或查询参数')
        updates['api_providers'][key] = {field: value.strip() for field, value in values.items()}
    try:
        Config.update_config(updates)
    except Exception:
        raise HTTPException(500, '设置保存失败，请检查本地配置文件是否可写') from None
    response.headers['Cache-Control'] = 'no-store'
    return settings_view()


@router.get('/mode')
def mode(request: Request):
    origin_check(request)
    return {'trial_mode': trial_mode()}


def identity(request: Request):
    origin_check(request)
    if not trial_mode():
        if not local(request):
            raise HTTPException(403, '当前为本地创作模式，请从本机打开工作台')
        return {'id': 'local', 'limits': ZERO, 'local': True, 'trial_mode': False}
    token = request.cookies.get('ink_trial', '')
    for entry in invites():
        expected = str(entry.get('token', ''))
        if expected and secrets.compare_digest(token, expected):
            return {'id': str(entry['user']), 'limits': entry.get('limits', ZERO), 'local': False, 'trial_mode': True}
    if token == 'local' and local(request) and not invites():
        return {'id': 'local', 'limits': json.loads(os.environ.get('SFA_INK_LOCAL_LIMITS', json.dumps(ZERO))), 'local': True, 'trial_mode': True}
    raise HTTPException(401, '请输入负责人提供的试用邀请码')


def access(pid, user, write=False, idle=True):
    try:
        p = store.load(pid)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if user.get('trial_mode', True) and store.ended(p['owner']) and __import__('time').time() >= store.ended(p['owner']) + 7 * 86400:
        raise HTTPException(410, '项目已到保留期限')
    if write:
        if user.get('trial_mode', True) and p['owner'] != user['id']:
            raise HTTPException(403, '他人项目只读，请先复制为自己的项目')
        if user.get('trial_mode', True) and store.ended(user['id']):
            raise HTTPException(403, '试用已结束，保留期内仅可查看和下载')
        if idle and store.busy(pid):
            raise HTTPException(409, '项目正在处理，请等待完成后修改')
    return p


def shot_at(p, sid):
    for shot in p['shots']:
        if shot['id'] == sid:
            return shot
    raise UserError('镜头不存在')


def remember_image(s, name, snapshot=None, prompt='', state='history', mode='generated'):
    if not name:
        return
    history = s.setdefault('image_history', {})
    if name not in history:
        history[name] = dict(image=name, created=None, shot=copy.deepcopy(snapshot), prompt=prompt, state=state, mode=mode)
    else:
        history[name]['state'] = state


def image_history(p, s, include_deleted=False):
    entries = copy.deepcopy(s.get('image_history', {}))
    names = list(s.get('image_versions', [])) + [s.get('image')]
    proposal = s.get('image_proposal')
    if proposal:
        names.append(proposal['image'])
        entries.setdefault(proposal['image'], dict(image=proposal['image'], shot=proposal.get('shot'), prompt=proposal.get('prompt',''), mode=proposal.get('mode','generated')))
    undo = s.get('image_undo')
    if undo and undo.get('image'):
        names.append(undo['image'])
        entries.setdefault(undo['image'], dict(image=undo['image'], shot={k: undo.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, prompt=undo.get('used_prompt', '')))
    for name in names:
        if name:
            entries.setdefault(name, dict(image=name, shot=None, prompt=''))
    result = []
    for name, item in entries.items():
        path = store.asset(p['id'], name)
        if not path.is_file():
            continue
        item['created'] = item.get('created') or path.stat().st_mtime
        item['status'] = ('current' if name == s.get('image') else 'candidate' if proposal and name == proposal['image'] else ('discarded' if item.get('state') == 'discarded' else 'history'))
        item['image_url'] = f'/api/ink/projects/{p["id"]}/assets/{name}'
        item['has_snapshot'] = bool(item.get('shot'))
        result.append(item)
    protected = {s.get('image'): '正在使用的图片不能删除，请先采用其他版本'}
    if proposal: protected[proposal['image']] = '候选待确认，请先采用或放弃候选'
    return annotated_versions(p, 'image', s['id'], sorted(result, key=lambda item: item['created'], reverse=True),
                              'image', protected, include_deleted)


def video_history(p, shot, include_deleted=False):
    # Legacy renders used the source clip stem. Only collect files associated
    # with this shot, never every mp4 in the project's shared asset directory.
    clips = set(shot.get('clip_versions', [])) | {shot.get('clip')}
    rendered = set(shot.get('rendered_versions', [])) | {shot.get('rendered')}
    rendered.update(Path(name).stem + '-sound.mp4' for name in clips if name)
    rendered -= clips  # A retained original can also be the final selected video.
    active = (shot.get('rendered') if shot.get('rendered') and not any(
        shot.get(key) for key in ('image_stale', 'clip_stale', 'rendered_stale')) else shot.get('clip'))
    result = []
    for kind, names in (('original', clips), ('subtitled', rendered)):
        for name in names:
            if not name:
                continue
            path = store.asset(p['id'], name)
            if not path.is_file() or path.suffix.lower() != '.mp4':
                continue
            result.append(dict(video=name, video_url=f'/api/ink/projects/{p["id"]}/assets/{name}',
                               created=path.stat().st_mtime, kind='edited' if name in shot.get('video_edit_versions', []) else kind, current=name == active,
                               needs_confirmation=bool(name == active and any(shot.get(key) for key in
                                   ('image_stale', 'clip_stale', 'rendered_stale')))))
    protected = {shot.get('clip'): '当前视频底稿不能删除，请先更换视频',
                 shot.get('rendered'): '正在使用的视频不能删除，请先采用其他版本'}
    for key in ('video_proposal', 'video_edit_draft'):
        for field in ('video', 'source'):
            name = (shot.get(key) or {}).get(field)
            if name: protected[name] = '视频调整仍在使用此版本，请先处理调整候选或草稿'
    return annotated_versions(p, 'video', shot['id'], sorted(result, key=lambda item: item['created'], reverse=True),
                              'video', protected, include_deleted)


def public(p):
    p = copy.deepcopy(p)
    p['media_format'] = format_for(p)
    p['jobs'] = store.jobs(p['id'])
    p['video_durations'] = video_durations()
    p['video_modes'] = video_modes()
    p['scene_layouts'] = layouts_for(p)
    p['spatial_version'] = p.get('spatial_version', 0)
    p['spatial_policy'] = SPATIAL_POLICY
    p['deleted_shots'] = [
        {**{key: item[key] for key in ('id', 'index', 'deleted_at')},
         'shot_id': item['shot']['id'], 'scene': item['shot']['scene'], 'content': item['shot']['content']}
        for item in p.get('deleted_shots', [])
    ]
    for shot in p['shots']:
        shot['spatial_warnings'] = []  # Screen-side swaps are not geography errors.
        shot['duration'] = shot.get('duration') or 5
        for key in ('image', 'clip', 'rendered'):
            name = shot.get(key)
            shot[key + '_url'] = f'/api/ink/projects/{p["id"]}/assets/{name}' if name else None
        video_proposal = shot.get('video_proposal')
        if video_proposal:
            for field in ('video', 'source'):
                video_proposal[field + '_url'] = f'/api/ink/projects/{p["id"]}/assets/{video_proposal[field]}'
        proposal = shot.get('image_proposal')
        if proposal:
            review = proposal.get('style_check')
            if review and review.get('spatial_policy') != SPATIAL_POLICY and 'staging' in review.get('regions', {}):
                proposal['style_check'] = None
            proposal['image_url'] = f'/api/ink/projects/{p["id"]}/assets/{proposal["image"]}'
    from scenarios.heritage_study.domain import decorate
    p = decorate(p)
    p['final_url'] = f'/api/ink/projects/{p["id"]}/assets/{p["final"]}' if p.get('final') else None
    return p


def call(user, kind, pid, fn):
    cid = (store.reserve(user['id'], kind, pid, user['limits'])
           if user.get('trial_mode', True) else store.record_call(user['id'], kind, pid))
    try:
        result = fn()
    except Exception:
        store.settle(cid, 'failed_or_unknown')
        raise
    store.settle(cid, 'completed')
    return result


def call_image(user, pid, prompt, refs, folder, **options):
    project = store.load(pid)
    if project.get('project_type') == 'heritage':
        options.setdefault('ratio', format_for(project)['ratio'])
        prompt += '\n' + frame_instruction(project)
    # A known missing credential is a local validation failure, not a provider call.
    check = getattr(providers, 'check_image_configuration', None)
    if check:
        check(refs)
    return call(user, 'image', pid, lambda: providers.image(prompt, refs, folder, pid, **options))


def differences(observed, baseline):
    if not baseline:
        return []
    result = [f'人物需核对：{c["desc"]}' for c in observed['characters'] if c['match_status'] != 'consistent']
    if observed['ink_style'] != baseline['ink_style']:
        result.append('水墨特征与已确认基线不同，请人工核对；基线未更新')
    return result


REFERENCE_PRESETS = {
    'soft': {'techniques': ['工笔细线条', '淡墨晕染'], 'whitespace': '多', 'bleed_strength': '弱'},
    'simple': {'techniques': ['工笔细线条', '简笔写意', '淡墨晕染'], 'whitespace': '多', 'bleed_strength': '弱'},
    'bold': {'techniques': ['泼墨', '枯笔飞白', '焦墨重墨'], 'whitespace': '中', 'bleed_strength': '中'},
}


def prepare_shot_lines(p, s, user, folder, stem):
    from scenarios.heritage_study.narration import speak
    pid = p['id']
    duration_seconds = s.get('duration') or 5
    lines, total = [], 0.0
    for i, d in enumerate(s['dialogues']):
        target = folder / (stem + f'-{i}.mp3')
        voice = (p.get('voices') or {}).get(d['character_id'], VOICES.get(d['character_id'], VOICES['c1']))
        if p.get('project_type') == 'heritage' and d['character_id'] == NARRATOR:
            call(user, 'speech', pid, lambda d=d, target=target: speak(providers, p, d['text'], target))
        else:
            call(user, 'speech', pid, lambda d=d, target=target, voice=voice: providers.speak(d['text'], voice, target))
        duration = providers.duration(target)
        remaining = duration_seconds - total
        excess = round(duration - remaining, 6)
        if excess > 0:
            if (i == len(s['dialogues']) - 1 and remaining > 0 and excess <= 1 / 24
                    and providers.silent_after(target, remaining)):
                duration = remaining
            else:
                measured = f'{total + duration:.2f}'.rstrip('0').rstrip('.')
                raise UserError(f'本镜头配音累计{measured}秒，超过{duration_seconds}秒。请延长镜头或精简台词')
        total += duration
        lines.append((d['text'], duration, target))
    return lines


def add_shot_sound(p, s, user, folder, stem, prepared_lines=None):
    from scenarios.heritage_study.narration import narrated_shot, profile
    pid = p['id']
    if not s.get('clip') or s.get('clip_stale'):
        raise UserError('请先更新该镜头的独立视频片段')
    has_audio = getattr(providers, 'has_audio', None)
    if not narrated_shot(p, s) and has_audio and has_audio(store.asset(pid, s['clip'])):
        if s.get('rendered') and s['rendered'] != s['clip']:
            versions = s.setdefault('rendered_versions', [])
            if s['rendered'] not in versions:
                versions.append(s['rendered'])
        s.update(rendered=s['clip'], rendered_stale=False, media_step='complete', audio_source='original')
        p['final_stale'] = bool(p.get('final'))
        return
    duration_seconds = s.get('duration') or 5
    lines = prepared_lines if prepared_lines is not None else prepare_shot_lines(p, s, user, folder, stem)
    target = folder / (stem + '-sound.mp4')
    providers.render(store.asset(pid, s['clip']), lines, folder, target, duration_seconds=duration_seconds, **generation_options(p))
    versions = s.setdefault('rendered_versions', [])
    for name in (s.get('rendered'), target.name):
        if name and name not in versions:
            versions.append(name)
    s.update(rendered=target.name, rendered_stale=False, media_step='complete', audio_source='tts')
    if narrated_shot(p, s):
        s['narration_profile'] = profile(p)
    p['final_stale'] = bool(p.get('final'))


def run_job(jid, pid, user, action, sid, preset=None):
    try:
        p = store.load(pid)
        folder = store.folder(pid)
        stem = uuid.uuid4().hex
        s = shot_at(p, sid) if sid else None
        if action == 'settings':
            p['creative_draft'] = call(user, 'text', pid, lambda: providers.extract_settings(p['script'] + '\n项目背景规则：' + background_context(p, include_references=True)))
        elif action == 'split':
            script = p['script'] + '\n项目背景规则：' + background_context(p) + '\n' + NARRATION_RULE
            settings = p.get('creative_settings')
            if p.get('project_type') == 'heritage':
                from scenarios.heritage_study.workflow import planning_settings
                settings = planning_settings(p)
            if settings:
                label = ('素材目录（角色ID、场景scene_id、道具prop_ids必须使用这些编号，不另造设定；画风与参考图可在分镜确认后调整）：'
                         if p.get('project_type') == 'heritage' else '已确认设定（角色ID、场景scene_id、道具prop_ids必须使用这些编号，不另造设定）：')
                script += '\n' + label + json.dumps(settings, ensure_ascii=False)
            script += PLANNING_MARKER + planning_context(p)
            options = {'settings': settings} if settings else {}
            if p.get('project_type') == 'heritage':
                from scenarios.heritage_study.timing import timing_for
                from scenarios.heritage_study.workflow import planning_research
                from scenarios.heritage_study.narration import profile
                options['planning'] = dict(speech_speed=profile(p)['speed'],kind='heritage-history',duration_seconds=timing_for(p)['intro'],narration=p['script'],research=planning_research(p))
                options['progress'] = lambda message,completed,total: store.progress(jid,message,completed,total)
            data = call(user, 'text', pid, lambda: providers.split(script, **options))
            if p.get('project_type') == 'heritage':
                data['heritage_story_source'] = p['script']
                from scenarios.heritage_study.workflow import planning_fingerprint
                data['heritage_story_research_stamp'] = planning_fingerprint(p)
            if settings:
                data['characters'] = settings['characters']
                for item in data['shots']:
                    if not item.get('scene_id'):
                        match = next((x for x in settings['scenes'] if x['name'] == item['scene']), None)
                        if match: item['scene_id'] = match['id']
                    check_references(settings, item)
            if p.get('project_type') == 'heritage' and not p.get('creative_settings'):
                data['creative_draft'] = settings
            if p['shots']:
                p['storyboard_draft'] = data
            else:
                p.update(data)
                if p.get('project_type') == 'heritage': p['heritage_story_stale']=False
                p['storyboard_confirmed'] = False
        elif action in {'image', 'reference'}:
            from scenarios.heritage_study.guide import require_reference
            require_reference(p,s,store)
            first = p['shots'][0]['id'] == sid
            if action == 'image' and not first and not p.get('baseline') and not p.get('creative_settings'):
                raise UserError('请先分析首张图并确认锁定人物与画风')
            if p.get('baseline') and not p.get('creative_settings'):
                known = {c['character_id'] for c in p['baseline']['characters']}
                if action == 'image' and not set(s['character_ids']) <= known:
                    raise UserError('基线缺少本镜头角色，请补充参考图并确认角色后再生成')
            refs = [str(store.asset(pid, name)) for name in p.get('baseline', {}).get('reference_images', [])] if p.get('baseline') else []
            if p.get('creative_settings'): refs = creative_refs(p, s)
            prompt_project = copy.deepcopy(p)
            if action == 'reference':
                reference = prompt_project.setdefault('baseline', None) or {'characters': [], 'ink_style': {}}
                known = {c['character_id'] for c in reference['characters']}
                reference['characters'].extend({'character_id': c['id'], 'desc': c['desc']} for c in p['characters'] if c['id'] not in known)
                if preset:
                    prompt_project['_style_override'] = preset
                    reference['ink_style'].update(REFERENCE_PRESETS[preset])
                prompt_project['baseline'] = reference
            prompt = frame_prompt(prompt_project, s)
            from scenarios.heritage_study.material_views import frame_style_references
            prompt, refs = frame_style_references(prompt_project,prompt,refs,with_style_reference,shot=s)
            prompt, refs = with_spatial_reference(p, s, prompt, refs, store)
            generated = call_image(user, pid, prompt, refs, folder)
            target = folder / (stem + '.png')
            with Image.open(generated) as image:
                image.convert('RGB').save(target)
            remember_image(s, s.get('image'), None if s.get('image_stale') else {k: s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, s.get('used_prompt', ''))
            invalidate(p, s)
            s.update(image=target.name, image_stale=False, used_prompt=prompt,
                     image_reference_images=[Path(ref).name for ref in refs],
                     image_baseline_version=p['baseline']['version'] if action == 'image' and p.get('baseline') else None)
            s['image_versions'].append(target.name)
            remember_image(s, target.name, {k: s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, s.get('used_prompt', ''))
            s['pending_image_edits'] = []
            if action == 'reference':
                # Persist the paid image even when the following vision call fails.
                store.save(p)
                observed = call(user, 'vl', pid, lambda: providers.analyze(store.asset(pid, s['image']), p))
                s.update(candidate=observed, candidate_image=s['image'], differences=differences(observed, p.get('baseline')))
        elif action == 'caption':
            if not s.get('image') or s.get('image_stale'):
                raise UserError('请先生成或上传当前镜头的有效图片')
            observed = call(user, 'vl', pid, lambda: providers.analyze(store.asset(pid, s['image']), p))
            s.update(candidate=observed, candidate_image=s['image'], differences=differences(observed, p.get('baseline')))
        elif action == 'video':
            if not s.get('image') or s.get('image_stale'):
                raise UserError('请先确认当前分镜图片')
            target = folder / (stem + '.mp4')
            duration_seconds = s.get('duration') or 5
            video_settings = s.get('video_settings') or {}
            mode = video_settings.get('mode', 'first_frame')
            last_image, references = video_inputs(p, s, mode, video_settings.get('end_shot_id'))
            if duration_seconds not in video_durations(mode):
                raise UserError('当前视频模型不支持此时长，请在分镜编辑中选择支持的时长后重试')
            video_settings = s.get('video_settings') or {}
            motion = video_settings.get('motion', s['motion'])
            if 'motion' not in video_settings:
                # The still's scale can disagree with its authored text. Do not
                # trigger a reframe by repeating a planning label in I2V motion.
                import re
                motion = re.sub(r'^\s*(?:大特写|特写|近景|中近景|中景|全景|远景)[，,、：:\s]+', '', motion)
            # Shot camera describes only the still first frame, never every video shot.
            camera = video_settings.get('camera', '')
            from scenarios.heritage_study.guide import entrance_motion
            motion = entrance_motion(p, s, motion, camera, mode)
            if camera:
                motion += '\n运镜与构图：' + camera
            if mode == 'reference':
                settings = p.get('creative_settings') or {}
                items = [x for x in settings.get('characters', []) if x['id'] in s['character_ids']]
                items += [x for x in settings.get('scenes', []) if x['id'] == s.get('scene_id')]
                labels = []
                from scenarios.heritage_study.visit_route import interior_view
                interior=p.get('project_type')=='heritage' and interior_view(s)
                if interior:labels.append('参考图1：已确认的内部首帧，保持其空间、构件、画风和机位，不切回外立面。')
                for item in ([] if interior else items):
                    from scenarios.heritage_study.material_views import material_reference
                    path = material_reference(p,s,item,store)
                    if path in references:labels.append(f"参考图{references.index(path)+1}：{item['name']}，{item['desc']}")
                for path in spatial_reference_paths(p, s, store):
                    labels.append(f"参考图{references.index(path)+1}：本场空间参考，参考人物与场景地标的关系，不复制画面左右、机位或动作")
                motion = '\n'.join(labels) + '\n遵循参考图的人物外貌、服饰与场景。画面安排：' + s['content'] + '\n依次执行：\n' + motion
            else:
                motion = '从输入图的实际状态开始，只执行以下动作：\n' + motion
            empty_cast = p.get('project_type') == 'heritage' and not s['character_ids']
            if not empty_cast:
                motion += '\n' + spatial_prompt(p, s, video=True)
            if video_model(mode).startswith('wan2.7'):
                from scenarios.heritage_study.narration import narrated_shot
                if narrated_shot(p, s) and all(d['character_id']==NARRATOR for d in s['dialogues']):
                    motion += '\n仅生成画面和环境声，不生成人声、讲解或音乐；统一旁白将在后期添加。'
                else:
                    motion += '\n' + native_dialogue_prompt(p['characters'], s['dialogues'])
            from scenarios.heritage_study.narration import narrated_shot
            prepared_lines = prepare_shot_lines(p, s, user, folder, stem) if narrated_shot(p, s) else None
            call(user, 'video', pid, lambda: providers.video(store.asset(pid, s['image']), motion, target, project={**p, 'heritage_empty_cast_video': True} if empty_cast else p, duration_seconds=duration_seconds, **({'mode': mode, 'last_image': last_image, 'references': references} if mode != 'first_frame' else {})))
            actual = providers.duration(target)
            if abs(actual - duration_seconds) > 0.3:
                raise UserError(f'视频未返回约{duration_seconds}秒片段，请核对模型；原结果保留')
            if s.get('clip') and s['clip'] not in s['clip_versions']:
                s['clip_versions'].append(s['clip'])
            s.update(clip=target.name, clip_stale=False, rendered_stale=bool(s.get('rendered')))
            s['clip_versions'].append(target.name)
            p['final_stale'] = bool(p.get('final'))
            # Commit the completed video before the external speech step.
            s['media_step'] = 'sound'
            store.save(p)
            try:
                add_shot_sound(p, s, user, folder, stem, prepared_lines)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, UserError) else '配音或字幕处理失败，请检查配音服务连接后重试。'
                raise UserError('视频已生成并保留，配音字幕未完成。' + reason) from exc
        elif action == 'sound':
            add_shot_sound(p, s, user, folder, stem)
        elif action == 'assemble':
            if p.get('music') and not p.get('music_credit'):
                raise UserError('所选配乐缺少授权记录，请重新选择')
            clips = []
            for shot in p['shots']:
                if not shot.get('rendered') or shot.get('image_stale') or shot.get('clip_stale') or shot.get('rendered_stale'):
                    raise UserError('每个镜头须完成最新视频及配音字幕处理，再拼接短片')
                clips.append(store.asset(pid, shot['rendered']))
            if not 1 <= len(clips) <= 6:
                raise UserError('请完成1—6个片段')
            target = folder / (stem + '-final.mp4')
            providers.assemble(clips, store.asset(pid, p['music']) if p.get('music') else None, folder, target, **generation_options(p))
            p.update(final=target.name, final_stale=False, final_media_format=format_for(p))
            p['final_versions'].append(target.name)
        store.save(p)
        store.event(pid, user['id'], action, {'shot': sid})
        if action=='split' and p.get('project_type')=='heritage':
            store.progress(jid,'新分镜已保存',3,3)
        store.finish(jid)
    except Exception as exc:
        # Do not expose SDK errors (which can contain endpoints/credentials) to clients.
        message = str(exc) if isinstance(exc, UserError) else '该步骤失败，已有结果保留。请检查模型设置或服务商任务记录，再手动重试'
        store.finish(jid, message[:600])
        store.event(pid, user['id'], 'failed', {'action': action, 'shot': sid})
        LOG.warning('Ink job failed: job=%s type=%s', jid, type(exc).__name__)


class Login(BaseModel):
    token: str = Field(default='', max_length=300)


@router.post('/login')
def login(body: Login, request: Request, response: Response):
    origin_check(request)
    if not trial_mode():
        raise HTTPException(404, '本地创作模式无需登录')
    token = body.token
    if not invites() and local(request):
        token = 'local'
    elif not any(str(e.get('token', '')) and secrets.compare_digest(token, str(e['token'])) for e in invites()):
        raise HTTPException(401, '邀请码无效，或服务端尚未设置邀请')
    secure = urlparse(os.environ.get('SFA_INK_ORIGIN', '')).scheme == 'https'
    response.set_cookie('ink_trial', token, httponly=True, secure=secure, samesite='strict', max_age=7 * 86400, path='/api/ink')
    return {'ok': True}


@router.post('/logout')
def logout(response: Response):
    response.delete_cookie('ink_trial', path='/api/ink')
    return {'ok': True}


@router.get('/me')
def me(user=Depends(identity)):
    from config import Config
    return {**user, 'usage': store.usage(user['id']), 'ended': store.ended(user['id']) if user.get('trial_mode', True) else None,
            'models': {'text': Config.LLM_MODEL, 'vl': Config.VLM_MODEL,
                       'image': Config.IMAGE_T2I_MODEL, 'video': Config.VIDEO_FIRST_FRAME_MODEL}}


class NewProject(BaseModel):
    project_type: Literal['ink', 'heritage'] = 'ink'
    title: str = Field(min_length=1, max_length=100)
    script: str = Field(min_length=1, max_length=20000)


@router.get('/projects')
def list_projects(user=Depends(identity)):
    items = []
    for p in store.list():
        if user.get('trial_mode', True) and store.ended(p['owner']) and __import__('time').time() >= store.ended(p['owner']) + 7 * 86400:
            continue
        shots = p.get('shots') or []
        image = shots[0].get('image') if shots else None
        items.append({**{k: p[k] for k in ('id', 'owner', 'title', 'created_at')},
                      'project_type': p.get('project_type', 'ink'),
                      'archived': bool(p.get('archived')),
                      'cover_url': f'/api/ink/projects/{p["id"]}/assets/{image}' if image else None})
    return {'projects': items}


@router.delete('/projects/{pid}')
@serialized
def archive_project(pid: str, user=Depends(identity)):
    p = access(pid, user, True)
    p['archived'] = True
    store.save(p)
    store.event(pid, user['id'], 'archive_project', {})
    return {'ok': True}


@router.post('/projects')
@serialized
def new_project(body: NewProject, user=Depends(identity)):
    if user.get('trial_mode', True) and store.ended(user['id']):
        raise HTTPException(403, '试用已结束')
    p = store.create(user['id'], body.title, body.script)
    if body.project_type == 'heritage':
        from scenarios.heritage_study.domain import empty_station
        p.update(project_type='heritage', heritage_station=empty_station(), heritage_version=0)
        store.save(p)
    return public(p)


@router.get('/projects/{pid}')
def get_project(pid: str, user=Depends(identity)):
    return public(access(pid, user))


class LayoutInput(BaseModel):
    version: int = Field(ge=0)
    layouts: list[SceneLayout] = Field(max_length=42)


@router.put('/projects/{pid}/scene-layouts')
@serialized
def save_scene_layouts(pid: str, body: LayoutInput, user=Depends(identity)):
    p = access(pid, user, True)
    if body.version != p.get('spatial_version', 0):
        raise HTTPException(409, '站位设定已变化，请刷新后重试')
    previous = {x['scene_id']: x for x in layouts_for(p)}
    values = [x.model_dump() for x in body.layouts]
    if len(values) != len(previous) or {x['scene_id'] for x in values} != set(previous):
        raise HTTPException(422, '请为当前每个场景保留一份站位设定')
    ids = {c['id'] for c in p['characters']}
    for item in values:
        placement_ids = [x['character_id'] for x in item['placements']]
        if len(placement_ids) != len(ids) or set(placement_ids) != ids:
            raise HTTPException(422, '请为每位已确认角色保留一份位置与走位描述')
        seen = set()
        previous_refs = {(x['shot_id'], x['image']) for x in previous[item['scene_id']]['references']}
        for ref in item['references']:
            if ref['shot_id'] in seen:
                raise HTTPException(422, '空间参考镜头不能重复')
            seen.add(ref['shot_id'])
            source = next((x for x in p['shots'] if x['id'] == ref['shot_id']), None)
            valid_source = (source and scene_key(source) == item['scene_id'] and len(source['character_ids']) >= min(2, len(ids))
                            and source.get('image') == ref['image'] and not source.get('image_stale'))
            if not valid_source and (ref['shot_id'], ref['image']) not in previous_refs:
                raise HTTPException(409, '请选择同场景已有的空间参考图片；图片已变化时请重新选择')
            try:
                if not store.asset(pid, ref['image']).is_file(): raise UserError('空间参考图片不存在')
            except ValueError as exc:
                raise HTTPException(422, '空间参考图片无效') from exc
    changed = {x['scene_id'] for x in values if x != previous[x['scene_id']]}
    if changed:
        # New guidance is for subsequent generation. Existing media stays selected
        # and playable; a correct reference must not become stale just by selecting it.
        p['spatial_version'] = p.get('spatial_version', 0) + 1
    p['scene_layouts'] = values
    p['spatial_policy'] = SPATIAL_POLICY
    store.save(p)
    store.event(pid, user['id'], 'scene_layouts', {'scenes': sorted(changed)})
    return public(p)


@router.post('/projects/{pid}/clone')
@serialized
def clone_project(pid: str, user=Depends(identity)):
    access(pid, user)
    if user.get('trial_mode', True) and store.ended(user['id']):
        raise HTTPException(403, '试用已结束')
    try:
        return public(store.clone(pid, user['id']))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def video_inputs(p, shot, mode, end_shot_id=None):
    check_frame_style(p, shot)
    option = next((x for x in video_modes() if x['id'] == mode), None)
    if mode != 'first_frame' and (not option or not option['supported']):
        raise UserError('此模式的模型尚未配置或适配器不支持，请在 API 设置中选择对应视频模型')
    if mode == 'start_end_frame':
        index = next(i for i, x in enumerate(p['shots']) if x['id'] == shot['id'])
        end = next((x for x in p['shots'] if x['id'] == end_shot_id), None) if end_shot_id else next(iter(p['shots'][index+1:index+2]), None)
        if not end or end['id'] == shot['id'] or not end.get('image') or end.get('image_stale'):
            raise UserError('请选择另一张已确认的分镜图片作为尾帧；默认使用下一片段图片')
        check_frame_style(p, end)
        path = store.asset(p['id'], end['image'])
        if not path.is_file():
            raise UserError('尾帧图片不存在，请重新生成或上传')
        return path, []
    if mode == 'reference':
        from scenarios.heritage_study.visit_route import interior_view
        if p.get('project_type')=='heritage' and interior_view(shot):
            path=store.asset(p['id'],shot['image'])
            if not path.is_file():raise UserError('内部首帧图片不存在，请先生成并确认画面')
            return None,[str(path)]
        settings = p.get('creative_settings') or {}
        items = [x for x in settings.get('characters', []) if x['id'] in shot['character_ids']]
        items += [x for x in settings.get('scenes', []) if x['id'] == shot.get('scene_id')]
        if len(items) != len(shot['character_ids']) + bool(shot.get('scene_id')) or not items or any(not x.get('image') for x in items):
            raise UserError('请先为本片段引用的角色和场景生成并确认图片')
        check_material_styles(p, items)
        from scenarios.heritage_study.material_views import material_reference
        paths = list(dict.fromkeys(material_reference(p,shot,x,store) for x in items))
        if any(not Path(x).is_file() for x in paths):
            raise UserError('角色或场景参考图文件不存在，请更新素材')
        paths = list(dict.fromkeys(paths + spatial_reference_paths(p, shot, store)))
        return None, paths
    return None, []


class VideoSettingsInput(BaseModel):
    mode: Literal['first_frame', 'start_end_frame', 'reference'] = 'first_frame'
    end_shot_id: str | None = None
    motion: str
    camera: str = ''
    duration: int


@router.put('/projects/{pid}/shots/{sid}/video-settings')
@serialized
def save_video_settings(pid: str, sid: str, body: VideoSettingsInput, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    if not s.get('image') or s.get('image_stale'):
        raise HTTPException(422, '请先确认当前分镜图片')
    if not body.motion.strip() or len(body.motion) > 6000 or len(body.camera) > 500:
        raise HTTPException(422, '请填写动作描述，动作最多1500字，运镜最多500字')
    try:
        video_inputs(p, s, body.mode, body.end_shot_id)
    except UserError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.duration not in video_durations(body.mode):
        raise HTTPException(422, '当前模型不支持此时长')
    s['video_settings'] = {'motion': body.motion.strip(), 'camera': body.camera.strip(), 'mode': body.mode, 'end_shot_id': body.end_shot_id}
    s['duration'] = body.duration
    s['clip_stale'] = bool(s.get('clip'))
    s['rendered_stale'] = bool(s.get('rendered'))
    p['final_stale'] = bool(p.get('final'))
    store.save(p)
    return public(p)


@router.post('/projects/{pid}/shots')
@serialized
def add_shot(pid: str, body: ShotInput, user=Depends(identity)):
    p = access(pid, user, True)
    if len(p['shots']) >= 30:
        raise HTTPException(409, '最多保留30个分镜，请先删除不需要的分镜')
    data = body.model_dump()
    try:
        if not data['content'].strip():
            raise UserError('请填写画面内容')
        if len(data['character_ids']) != len(set(data['character_ids'])):
            raise UserError('出场角色不能重复')
        if len(data['prop_ids']) != len(set(data['prop_ids'])):
            raise UserError('道具不能重复')
        if not set(data['character_ids']) <= {c['id'] for c in p['characters']}:
            raise UserError('角色 ID 无效')
        if invalid_speakers(data):
            raise UserError('台词角色必须在本镜头出场')
        if p.get('creative_settings'):
            check_references(p['creative_settings'], data)
        elif p.get('project_type') == 'heritage':
            from scenarios.heritage_study.workflow import check_board_references
            check_board_references(p, data)
        elif data['scene_id'] is not None or data['prop_ids']:
            raise UserError('请先在创作设定中确认场景和道具')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    used_ids = {shot['id'] for shot in p['shots']}
    for item in p.get('deleted_shots', []):
        used_ids.add(item['shot']['id'])
        used_ids.update(item['order'])
    sid = 's_' + uuid.uuid4().hex
    while sid in used_ids:
        sid = 's_' + uuid.uuid4().hex
    # Manual shots use the same empty output state as split shots.
    data.update(id=sid, revision=1, image=None, image_versions=[], image_stale=False,
                clip=None, clip_versions=[], clip_stale=False, rendered=None,
                rendered_stale=False, candidate=None, candidate_image=None, differences=[])
    p['shots'].append(data)
    # Restored older shots retain their original position before manually appended shots.
    for item in p.get('deleted_shots', []):
        item['order'].append(sid)
    p['storyboard_confirmed'] = False
    p['final_stale'] = bool(p.get('final'))
    store.save(p)
    store.event(pid, user['id'], 'add_shot', {'shot': sid})
    return public(p)


@router.patch('/projects/{pid}/shots/{sid}')
@serialized
def edit_shot(pid: str, sid: str, body: ShotInput, user=Depends(identity)):
    p = access(pid, user, True)
    try:
        s = shot_at(p, sid)
        data = body.model_dump()
        if not set(data['character_ids']) <= {c['id'] for c in p['characters']}:
            raise UserError('角色 ID 无效')
        if invalid_speakers(data):
            raise UserError('台词角色必须在本镜头出场')
        if p.get('creative_settings'):
            check_references(p['creative_settings'], data)
        elif p.get('project_type') == 'heritage':
            from scenarios.heritage_study.workflow import check_board_references
            check_board_references(p, data)
        changed = {key for key in ShotInput.model_fields
                   if data[key] != s.get(key, 5 if key == 'duration' else [] if key == 'prop_ids' else None)}
        if not changed:
            return public(p)
        # Old edit drafts and candidates contain full shot snapshots (including dialogue).
        # Archive their images before retiring the snapshots so they cannot replace this edit.
        remember_image(s, s.get('image'), None if s.get('image_stale') else
                       {key: copy.deepcopy(s.get(key, 5 if key == 'duration' else [] if key == 'prop_ids' else None))
                        for key in ShotInput.model_fields}, s.get('used_prompt', ''))
        proposal = s.get('image_proposal')
        if proposal:
            remember_image(s, proposal['image'], proposal.get('shot'), proposal.get('prompt', ''),
                           state='history', mode=proposal.get('mode', 'generated'))
        undo = s.get('image_undo')
        if undo:
            remember_image(s, undo.get('image'),
                           {key: copy.deepcopy(undo.get(key, 5 if key == 'duration' else [] if key == 'prop_ids' else None))
                            for key in ShotInput.model_fields}, undo.get('used_prompt', ''))
        s.update(image_draft=None, image_proposal=None, image_undo=None, image_undo_stamp=None)
        p['storyboard_confirmed'] = False
        visual_fields = changed - {'dialogues', 'duration'}
        visual = bool(visual_fields)
        if visual:
            s['pending_image_edits'] = sorted(set(s.get('pending_image_edits', [])) | visual_fields)
            invalidate(p, s)
        elif 'duration' in changed:
            invalidate(p, s, image=False)
        elif data['dialogues'] != s['dialogues']:
            s['rendered_stale'] = bool(s.get('rendered'))
            p['final_stale'] = bool(p.get('final'))
        # A new storyboard action sequence supersedes any earlier video-only override.
        if changed & {'motion', 'camera', 'duration'}:
            s.pop('video_settings', None)
        s.update(data, revision=s['revision'] + 1)
        store.save(p)
        store.event(pid, user['id'], 'edit_shot', {'shot': sid, 'category': 'visual' if visual else 'audio'})
        return public(p)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class DeleteShotInput(BaseModel):
    model_config = {'extra': 'forbid'}
    revision: int = Field(ge=1, strict=True)


def shot_restore_context(p, shot):
    """Only rendering dependencies; deletion itself never invalidates other shots."""
    references = ([Path(path).name for path in creative_refs(p, shot)] if p.get('creative_settings') else
                  (p.get('baseline') or {}).get('reference_images', []))
    from scenarios.heritage_study.narration import profile
    return {'visual': {'prompt': frame_prompt(p, shot), 'references': references},
            'voices': {d['character_id']: profile(p)['voice'] if p.get('project_type') == 'heritage' and d['character_id'] == NARRATOR else (p.get('voices') or {}).get(d['character_id'], VOICES.get(d['character_id'], VOICES['c1']))
                       for d in shot['dialogues']}}


@router.delete('/projects/{pid}/shots/{sid}')
@serialized
def delete_shot(pid: str, sid: str, body: DeleteShotInput, user=Depends(identity)):
    p = access(pid, user, True)
    index = next((i for i, shot in enumerate(p['shots']) if shot['id'] == sid), None)
    if index is None:
        raise HTTPException(404, '分镜不存在或已删除，请刷新后查看')
    shot = p['shots'][index]
    if shot['revision'] != body.revision:
        raise HTTPException(409, '分镜内容已变化，请重新查看后删除')
    if len(p['shots']) <= 1:
        raise HTTPException(409, '至少保留一个分镜')
    order = (p['deleted_shots'][-1]['order'] if p.get('deleted_shots') else
             [item['id'] for item in p['shots']])
    entry = {'id': uuid.uuid4().hex, 'shot': copy.deepcopy(shot), 'index': index,
             'deleted_at': time.time(), 'context': shot_restore_context(p, shot),
             'stamp': proposal_stamp(p, shot),
             'order': copy.deepcopy(order)}
    p.setdefault('deleted_shots', []).append(entry)
    p['shots'].pop(index)
    p['storyboard_confirmed'] = False
    p['final_stale'] = bool(p.get('final'))
    store.save(p)
    store.event(pid, user['id'], 'delete_shot', {'shot': sid, 'deletion_id': entry['id']})
    return public(p)


@router.post('/projects/{pid}/deleted-shots/{deletion_id}/restore')
@serialized
def restore_deleted_shot(pid: str, deletion_id: str, user=Depends(identity)):
    p = access(pid, user, True)
    deleted = p.get('deleted_shots', [])
    entry = next((item for item in deleted if item['id'] == deletion_id), None)
    if entry is None:
        raise HTTPException(404, '该分镜已恢复或不存在，请刷新后查看')
    shot = copy.deepcopy(entry['shot'])
    if any(item['id'] == shot['id'] for item in p['shots']):
        raise HTTPException(409, '该分镜已经存在，请刷新后查看')
    if len(p['shots']) >= 30:
        raise HTTPException(409, '最多保留30个分镜，请先删除其他分镜')
    # Preserve the full order across deletes, including when undo is out of order.
    order = entry['order']
    rank = order.index(shot['id'])
    index = next((i for i, item in enumerate(p['shots'])
                  if item['id'] in order and order.index(item['id']) > rank), len(p['shots']))
    context = shot_restore_context(p, shot)
    visual_changed = entry['context']['visual'] != context['visual']
    if visual_changed:
        invalidate(p, shot, reason='删除期间设定已调整，请检查恢复的图片是否仍适用')
    elif entry['context']['voices'] != context['voices']:
        shot['rendered_stale'] = bool(shot.get('rendered'))
    shot['revision'] += 1
    # A proposal/undo can reference different assets from the current shot.
    # Keep the baseline guard even when the current shot's visual context is unchanged.
    can_rebase_stamp = (not visual_changed and
                        entry['stamp'][2] == (p.get('baseline') or {}).get('version'))
    proposal = shot.get('image_proposal')
    if proposal:
        if can_rebase_stamp and proposal.get('stamp') == entry['stamp']:
            proposal['stamp'] = proposal_stamp(p, shot)
        else:
            remember_image(shot, proposal['image'], proposal.get('shot'), proposal.get('prompt', ''),
                           state='history', mode=proposal.get('mode', 'generated'))
            shot['image_proposal'] = None
    undo = shot.get('image_undo')
    if undo:
        if can_rebase_stamp and shot.get('image_undo_stamp') == entry['stamp']:
            shot['image_undo_stamp'] = proposal_stamp(p, shot)
        else:
            remember_image(shot, undo.get('image'), {key: undo.get(key) for key in ShotInput.model_fields},
                           undo.get('used_prompt', ''))
            shot['image_undo'] = None
            shot['image_undo_stamp'] = None
    p['shots'].insert(index, shot)
    p['deleted_shots'] = [item for item in deleted if item['id'] != deletion_id]
    p['storyboard_confirmed'] = False
    p['final_stale'] = bool(p.get('final'))
    store.save(p)
    store.event(pid, user['id'], 'restore_shot', {'shot': shot['id'], 'deletion_id': deletion_id})
    return public(p)


@router.post('/projects/{pid}/baseline/{sid}')
@serialized
def lock_baseline(pid: str, sid: str, body: Caption, user=Depends(identity)):
    p = access(pid, user, True)
    try:
        s = shot_at(p, sid)
        if not s.get('candidate') or s['candidate_image'] != s.get('image') or s.get('image_stale'):
            raise UserError('请先分析当前有效参考图，再确认候选设定')
        approved = caption(body.model_dump(), [c['id'] for c in p['characters']])
        if any(c['character_id'] is None or c['visibility'] == 'unclear' for c in approved['characters']):
            raise UserError('人物看不清或未关联角色，请编辑候选或换参考图；无人图应使用空人物数组')
        old = p.get('baseline')
        baseline = copy.deepcopy(old) if old else {'characters': [], 'ink_style': {}, 'reference_images': []}
        by_id = {c['character_id']: c for c in baseline['characters']}
        by_id.update({c['character_id']: c for c in approved['characters']})
        baseline.update(characters=list(by_id.values()), ink_style=approved['ink_style'], version=(old or {}).get('version', 0) + 1)
        baseline['reference_images'] = list(dict.fromkeys([*baseline['reference_images'], s['image']]))[-3:]
        if old:
            p['baseline_history'].append(old)
        p['baseline'] = baseline
        s.update(candidate=approved, candidate_image=s['image'])
        for other in p['shots']:
            if other['id'] != sid:
                invalidate(p, other, reason="人物或画风设定已调整，请检查原图是否仍适用")
        # Current reference stays valid but its downstream must reflect the new approval.
        invalidate(p, s, image=False)
        store.save(p)
        store.event(pid, user['id'], 'confirm_baseline', {'version': baseline['version']})
        return public(p)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/projects/{pid}/shots/{sid}/image')
async def upload_image(pid: str, sid: str, file: UploadFile = File(...), user=Depends(identity)):
    p = access(pid, user, True)
    try:
        s = shot_at(p, sid)
        data = await file.read(12 * 1024 * 1024 + 1)
        if len(data) > 12 * 1024 * 1024:
            raise UserError('图片不能超过12MB')
        from io import BytesIO
        with Image.open(BytesIO(data)) as img:
            if img.width * img.height > 30_000_000:
                raise UserError('图片像素过大，请缩小后上传')
            img.load()
            target = store.folder(pid) / (uuid.uuid4().hex + '.png')
            img.convert('RGB').save(target)
        with mutation_lock:
            # Recheck after awaiting file I/O to avoid overwriting an active job.
            p = access(pid, user, True)
            s = shot_at(p, sid)
            remember_image(s, s.get('image'), None if s.get('image_stale') else {k: s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, s.get('used_prompt', ''))
            invalidate(p, s)
            s.update(image=target.name, image_stale=False, pending_image_edits=[])
            s['image_versions'].append(target.name)
            remember_image(s, target.name, {k: s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, s.get('used_prompt', ''))
            s['pending_image_edits'] = []
            store.save(p)
            store.event(pid, user['id'], 'upload_image', {'shot': sid})
            return public(p)
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, '无法接收图片：请上传有效且不超过12MB的图片') from exc


@router.post('/projects/{pid}/actions/{action}')
@serialized
def action(pid: str, action: str, sid: str | None = None, preset: Literal['soft', 'simple', 'bold'] | None = None, user=Depends(identity)):
    p = access(pid, user, True)
    if action not in {'settings', 'split', 'image', 'reference', 'caption', 'video', 'sound', 'assemble'}:
        raise HTTPException(404, '动作不存在')
    if action == 'assemble' and p.get('project_type') == 'heritage':
        raise HTTPException(422, '请到研学工作区的“导出”加入实拍片尾并合成30秒短片')
    if action == 'split' and p.get('storyboard_draft'):
        raise HTTPException(409, '请先采用或放弃已有分镜草稿')
    if action in {'image', 'reference', 'caption', 'video', 'sound'}:
        try:
            shot_at(p, sid)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
    if action in {'image', 'reference'}:
        try: check_visible_characters(p, shot_at(p, sid))
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    try:
        jid = store.enqueue(pid, user['id'], action)
        pool.submit(run_job, jid, pid, user, action, sid, preset)
        return {'job_id': jid}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/projects/{pid}/assets/{name}')
def asset(pid: str, name: str, user=Depends(identity)):
    access(pid, user)
    try:
        path = store.asset(pid, name)
    except ValueError as exc:
        raise HTTPException(404, '文件不存在') from exc
    if not path.is_file():
        raise HTTPException(404, '文件不存在或已清理')
    return FileResponse(path, filename=name, content_disposition_type='inline', headers={'Cache-Control': 'private, no-store'})


def music_library():
    root = Path(__file__).resolve().parent / 'music'
    manifest = root / 'manifest.json'
    if not manifest.is_file():
        return []
    items = json.loads(manifest.read_text())
    return [m for m in items if m.get('license') and m.get('id') and Path(m.get('file', '')).name == m.get('file') and (root / m['file']).is_file()]


@router.get('/music')
def music(user=Depends(identity)):
    return {'tracks': [{k: m[k] for k in ('id', 'title', 'license')} for m in music_library()]}


class MusicChoice(BaseModel):
    id: str


@router.post('/projects/{pid}/music')
@serialized
def select_music(pid: str, body: MusicChoice, user=Depends(identity)):
    p = access(pid, user, True)
    if not body.id:
        p.update(music=None, music_credit=None, final_stale=bool(p.get('final')))
        store.save(p)
        return public(p)
    item = next((m for m in music_library() if m['id'] == body.id), None)
    if not item:
        raise HTTPException(422, '曲目不存在或尚未登记使用授权')
    source = Path(__file__).resolve().parent / 'music' / item['file']
    target = store.folder(pid) / (uuid.uuid4().hex + source.suffix)
    shutil.copy2(source, target)
    p.update(music=target.name, music_credit={'title': item['title'], 'license': item['license']}, final_stale=bool(p.get('final')))
    store.save(p)
    return public(p)


class VoiceChoice(BaseModel):
    voices: dict[str, str]


@router.post('/projects/{pid}/voices')
@serialized
def select_voices(pid: str, body: VoiceChoice, user=Depends(identity)):
    p = access(pid, user, True)
    known = {c['id'] for c in p['characters']}
    from scenarios.heritage_study.narration import VOICE_PROFILES, narrated_shot, profile
    supported = set(VOICES.values()) | (set(VOICE_PROFILES) if p.get('project_type') == 'heritage' else set())
    if not known <= set(body.voices) <= known | {NARRATOR} or not set(body.voices.values()) <= supported:
        raise HTTPException(422, '请为角色和旁白选择支持的预设音色')
    old = {**VOICES, **(p.get('voices') or {})}
    if p.get('project_type') == 'heritage': old[NARRATOR] = profile(p)['voice']
    next_voices = {**VOICES, **body.voices}
    if p.get('project_type') == 'heritage': next_voices[NARRATOR] = profile({'voices':body.voices})['voice']
    changed = {cid for cid in old.keys() | next_voices.keys() if old.get(cid) != next_voices.get(cid)}
    p['voices'] = body.voices
    for shot in p['shots']:
        if (shot.get('audio_source') != 'original' or narrated_shot(p, shot)) and any(d['character_id'] in changed for d in shot['dialogues']):
            shot['rendered_stale'] = bool(shot.get('rendered'))
            p['final_stale'] = bool(p.get('final'))
    if p.get('project_type') == 'heritage' and NARRATOR in changed:
        p['final_stale'] = bool(p.get('final'))
    store.save(p)
    store.event(pid, user['id'], 'edit_voices', {'characters': sorted(changed)})
    return public(p)


class Feedback(BaseModel):
    visual: Literal['明显减少', '有所减少', '不变', '增加', '说不清']
    saved_work: str = Field(max_length=3000)
    audio: str = Field(max_length=1000)
    previous_method: str = Field(min_length=1, max_length=1000)




@router.post('/projects/{pid}/feedback')
@serialized
def feedback(pid: str, body: Feedback, user=Depends(identity)):
    if not user.get('trial_mode', True):
        raise HTTPException(404, '试用反馈暂未启用')
    p = access(pid, user, True)
    p['feedback'] = body.model_dump()
    store.save(p)
    store.event(pid, user['id'], 'feedback', body.model_dump())
    return public(p)


@router.post('/end-trial')
@serialized
def end_trial(user=Depends(identity)):
    if not user.get('trial_mode', True):
        raise HTTPException(404, '试用功能暂未启用')
    if any(store.busy(p['id']) for p in store.list() if p['owner'] == user['id']):
        raise HTTPException(409, '有任务运行中，请完成后再结束试用')
    store.end_trial(user['id'])
    return {'ended': store.ended(user['id']) if user.get('trial_mode', True) else None, 'retention_days': 7}


class PreviewInput(BaseModel):
    mode: Literal['detail', 'redesign', 'style']
    shot: ShotInput
    instruction: str = Field(default='', max_length=1000)


class CandidateChoice(BaseModel):
    candidate_id: str


def proposal_stamp(p, s):
    stamp = [s['revision'], s.get('image'), (p.get('baseline') or {}).get('version')]
    return stamp + [p['spatial_version']] if 'spatial_version' in p else stamp


def run_preview(jid, pid, user, sid, request, stamp):
    try:
        p = store.load(pid)
        s = shot_at(p, sid)
        draft = request['shot']
        style_reference = None
        if request['mode'] == 'style':
            prompt, refs = restyle_request(p, store.asset(pid, s['image']), request['instruction'])
        elif request['mode'] == 'detail':
            check_frame_style(p, s)
            prompt, refs = detail_request(p, s, request['instruction'], store)
        else:
            from scenarios.heritage_study.guide import require_reference
            require_reference(p,draft,store)
            refs = creative_refs(p, draft)
            # No full storyboard image is used as a composition/pose reference.
            context = copy.deepcopy(p)
            if context.get('baseline'):
                known = {c['character_id'] for c in context['baseline']['characters']}
                context['baseline']['characters'].extend(
                    {'character_id': c['id'], 'desc': c['desc']} for c in p['characters'] if c['id'] not in known)
            prompt = frame_prompt(context, draft)
            from scenarios.heritage_study.material_views import frame_style_references
            prompt, refs = frame_style_references(context,prompt,refs,with_style_reference,shot=draft)
            prompt, refs = with_spatial_reference(p, draft, prompt, refs, store)
        if request['mode'] != 'redesign':
            prompt += '\n' + spatial_prompt(p, draft)
        generated = call_image(user, pid, prompt, refs, store.folder(pid))
        change_warning = restyle_change_warning(store.asset(pid, s['image']), generated) if request['mode'] == 'style' else None
        name = uuid.uuid4().hex + '.png'
        with Image.open(generated) as img:
            img.convert('RGB').save(store.folder(pid) / name)
        remember_image(s, s.get('image'), None if s.get('image_stale') else {k: s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, s.get('used_prompt', ''))
        remember_image(s, name, draft, prompt, state='candidate', mode=request['mode'])
        previous = s.get('image_proposal')
        if previous:
            remember_image(s, previous['image'], previous['shot'], previous['prompt'], state='history', mode=previous['mode'])
        s['image_proposal'] = dict(id=uuid.uuid4().hex, image=name, mode=request['mode'],
                                   instruction=request['instruction'], shot=draft, stamp=stamp, prompt=prompt,
                                   style_reference=style_reference, change_warning=change_warning,
                                   generation_recipe='restyle-v2' if request['mode'] == 'style' else 'detail-identity-v2' if request['mode'] == 'detail' else 'frame-style-v1-restored', reference_images=[Path(ref).name for ref in refs])
        store.save(p)
        store.finish(jid)
    except Exception as exc:
        store.finish(jid, str(exc)[:600] if isinstance(exc, UserError) else '候选生成失败，原图与调整内容已保留，请手动重试')
        LOG.warning('Ink preview failed: job=%s type=%s', jid, type(exc).__name__)


@router.post('/projects/{pid}/shots/{sid}/preview')
@serialized
def preview_image(pid: str, sid: str, body: PreviewInput, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    request = body.model_dump()
    if body.mode == 'style':
        if not s.get('image'):
            raise HTTPException(422, '请先生成或上传图片，再修正画风')
        if profile_for(p) is None:
            raise HTTPException(422, '请先在创作设定中选择水墨类型')
        request['shot'] = ShotInput.model_validate({
            k: copy.deepcopy(s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None))
            for k in ShotInput.model_fields
        }).model_dump()
    draft = request['shot']
    if p.get('creative_settings'):
        try: check_references(p['creative_settings'], draft)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    if not set(draft['character_ids']) <= {c['id'] for c in p['characters']}:
        raise HTTPException(422, '出场人物无效')
    if invalid_speakers(draft):
        raise HTTPException(422, '台词角色必须在本镜头出场')
    if body.mode == 'detail':
        if not s.get('image') or not body.instruction.strip():
            raise HTTPException(422, '请先准备图片，并填写局部调整要求')
        # Local edits preserve unedited shot fields, including the later video motion.
        draft = {k: copy.deepcopy(s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None)) for k in ShotInput.model_fields}
        draft['content'] += '\n局部调整（对应部位以此为准）：' + body.instruction.strip()
        if len(draft['content']) > 3000:
            raise HTTPException(422, '累计局部调整描述过长，请用重新设计整理画面内容')
        request['shot'] = ShotInput.model_validate(draft).model_dump()
    try: check_visible_characters(p, request['shot'])
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    s['image_draft'] = request
    store.save(p)
    jid = store.enqueue(pid, user['id'], 'preview')
    pool.submit(run_preview, jid, pid, user, sid, request, proposal_stamp(p, s))
    return public(store.load(pid))


@router.post('/projects/{pid}/shots/{sid}/check-style')
@serialized
def check_candidate_style(pid: str, sid: str, body: CandidateChoice, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    candidate = s.get('image_proposal')
    if not candidate or candidate['id'] != body.candidate_id:
        raise HTTPException(409, '候选已变化，请刷新后重试')
    try:
        observed = call(user, 'vl', pid, lambda: providers.review_style(store.asset(pid, candidate['image']), p, candidate['shot'],
            reference=store.asset(pid, candidate['style_reference']) if candidate.get('style_reference') else None,
            spatial_references=spatial_reference_paths(p, candidate['shot'], store)))
    except Exception as exc:
        raise HTTPException(422, '画风检查失败，候选图保留，请检查视觉模型配置后重试') from exc
    candidate['style_check'] = observed
    current_stamp = proposal_stamp(p, s)
    if candidate.get('stamp', [])[:3] == current_stamp[:3]:
        # A saved geography change alone does not discard an older candidate.
        # A fresh visual review checks it against the new spatial policy.
        candidate['stamp'] = current_stamp
    store.save(p)
    return public(p)


@router.post('/projects/{pid}/shots/{sid}/adopt')
@serialized
def adopt_image(pid: str, sid: str, body: CandidateChoice, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    candidate = s.get('image_proposal')
    if not candidate or candidate['id'] != body.candidate_id:
        raise HTTPException(409, '候选已变化，请刷新后重试')
    if ((candidate.get('style_check') or {}).get('spatial_policy') == SPATIAL_POLICY
        and ((candidate['style_check'].get('regions') or {}).get('staging') or {}).get('status') == 'deviates'):
        raise HTTPException(422, '候选人物与场景的位置关系不一致，请继续调整后再采用')
    if candidate['stamp'] != proposal_stamp(p, s):
        raise HTTPException(409, '原图或设定已变化，请重新生成候选')
    remember_image(s, s.get('image'), None if s.get('image_stale') else {k: s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, s.get('used_prompt', ''))
    remember_image(s, candidate['image'], candidate['shot'], candidate['prompt'], state='history', mode=candidate['mode'])
    s['image_undo'] = {k: copy.deepcopy(s.get(k, 5 if k == 'duration' else None)) for k in (*ShotInput.model_fields, 'image', 'image_stale', 'used_prompt', 'image_baseline_version')}
    invalidate(p, s)
    s.update(candidate['shot'])
    s.update(image=candidate['image'], image_stale=False, used_prompt=candidate['prompt'],
             revision=s['revision'] + 1, pending_image_edits=[], image_proposal=None, image_draft=None)
    s['image_versions'].append(s['image'])
    s['image_undo_stamp'] = proposal_stamp(p, s)
    store.save(p)
    return public(p)


@router.post('/projects/{pid}/shots/{sid}/discard')
@serialized
def discard_image(pid: str, sid: str, body: CandidateChoice, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    if not s.get('image_proposal') or s['image_proposal']['id'] != body.candidate_id:
        raise HTTPException(409, '候选已变化，请刷新后重试')
    candidate = s['image_proposal']
    remember_image(s, candidate['image'], candidate.get('shot'), candidate.get('prompt', ''), state='discarded', mode=candidate.get('mode', 'generated'))
    s.update(image_proposal=None, image_draft=None)
    store.save(p)
    return public(p)


@router.post('/projects/{pid}/shots/{sid}/undo-image')
@serialized
def undo_image(pid: str, sid: str, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    if not s.get('image_undo') or s.get('image_undo_stamp') != proposal_stamp(p, s):
        raise HTTPException(409, '后续内容已变化，不能撤回这次采用')
    previous = s['image_undo']
    invalidate(p, s)
    s.update(previous)
    s.update(revision=s['revision'] + 1, image_undo=None, image_proposal=None, image_draft=None)
    store.save(p)
    return public(p)


@router.get('/projects/{pid}/shots/{sid}/history')
def get_image_history(pid: str, sid: str, include_deleted: bool = False, user=Depends(identity)):
    p = access(pid, user)
    return {'images': image_history(p, shot_at(p, sid), include_deleted)}


@router.get('/projects/{pid}/shots/{sid}/video-history')
def get_video_history(pid: str, sid: str, include_deleted: bool = False, user=Depends(identity)):
    p = access(pid, user)
    try:
        shot = shot_at(p, sid)
    except UserError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {'videos': video_history(p, shot, include_deleted)}


class AdoptVideo(BaseModel):
    video: str
    revision: int
    current_clip: str | None = None


@router.post('/projects/{pid}/shots/{sid}/adopt-video')
@serialized
def adopt_history_video(pid: str, sid: str, body: AdoptVideo, user=Depends(identity)):
    p = access(pid, user, True)
    try:
        s = shot_at(p, sid)
    except UserError as exc:
        raise HTTPException(404, str(exc)) from exc
    if s['revision'] != body.revision or s.get('clip') != body.current_clip:
        raise HTTPException(409, '当前视频已变化，请重新打开历史版本')
    item = next((x for x in video_history(p, s) if x['video'] == body.video), None)
    if item is None:
        raise HTTPException(422, '该视频不属于本镜头或文件已不存在')
    duration = providers.duration(store.asset(pid, body.video))
    if not 2 <= round(duration) <= 15 or abs(duration - round(duration)) > .3:
        raise HTTPException(422, '该视频时长不适合当前片段')
    for name in (s.get('rendered'), body.video):
        versions = s.setdefault('rendered_versions', [])
        if name and name not in versions:
            versions.append(name)
    # Adopt the entire selected audiovisual artifact; never replace its audio.
    if item['kind'] == 'original':
        versions = s.setdefault('clip_versions', [])
        for name in (s.get('clip'), body.video):
            if name and name not in versions:
                versions.append(name)
        s['clip'] = body.video
    s.update(rendered=body.video, clip_stale=False, rendered_stale=False, duration=round(duration),
             audio_source='original' if item['kind'] == 'original' else 'historical', media_step='complete',
             revision=s['revision'] + 1)
    p['final_stale'] = bool(p.get('final'))
    store.save(p)
    store.event(pid, user['id'], 'adopt_video', {'shot': sid, 'video': body.video})
    return public(p)


class RestoreImage(BaseModel):
    image: str
    revision: int
    current_image: str | None = None


@router.post('/projects/{pid}/shots/{sid}/restore-image')
@serialized
def restore_history_image(pid: str, sid: str, body: RestoreImage, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    if s['revision'] != body.revision or s.get('image') != body.current_image:
        raise HTTPException(409, '当前分镜已变化，请刷新历史列表')
    item = next((v for v in image_history(p, s) if v['image'] == body.image), None)
    if not item:
        raise HTTPException(404, '该图片不属于此镜头历史或文件已不存在')
    if s.get('image') == body.image:
        return public(p)
    remember_image(s, s.get('image'), None if s.get('image_stale') else {k: s.get(k, 5 if k == 'duration' else [] if k == 'prop_ids' else None) for k in ShotInput.model_fields}, s.get('used_prompt', ''))
    s['image_undo'] = {k: copy.deepcopy(s.get(k, 5 if k == 'duration' else None)) for k in (*ShotInput.model_fields, 'image', 'image_stale', 'used_prompt', 'image_baseline_version')}
    proposal = s.get('image_proposal')
    if proposal:
        remember_image(s, proposal['image'], proposal['shot'], proposal['prompt'], state='history', mode=proposal['mode'])
    invalidate(p, s)
    if item.get('shot'):
        s.update(ShotInput.model_validate(item['shot']).model_dump())
    s.update(image=body.image, image_stale=False, used_prompt=item.get('prompt',''), image_baseline_version=None,
             revision=s['revision'] + 1, pending_image_edits=[], image_proposal=None, image_draft=None)
    remember_image(s, body.image, item.get('shot'), item.get('prompt',''), state='history')
    s['image_undo_stamp'] = proposal_stamp(p, s)
    store.save(p)
    return public(p)


class ConfirmCurrentImage(BaseModel):
    image: str
    revision: int


@router.post('/projects/{pid}/shots/{sid}/confirm-image')
@serialized
def confirm_current_image(pid: str, sid: str, body: ConfirmCurrentImage, user=Depends(identity)):
    p = access(pid, user, True)
    s = shot_at(p, sid)
    if s.get('image') != body.image or s['revision'] != body.revision:
        raise HTTPException(409, '图片或镜头内容已变化，请重新查看后确认')
    if not s.get('image') or not store.asset(pid, s['image']).is_file():
        raise HTTPException(422, '请先生成或上传图片')
    s.update(image_stale=False, image_stale_reason=None, pending_image_edits=[],
             image_baseline_version=(p.get('baseline') or {}).get('version'))
    store.save(p)
    store.event(pid, user['id'], 'confirm_current_image', {'shot': sid, 'image': s['image']})
    return public(p)


@router.post('/projects/{pid}/confirm-story')
@serialized
def confirm_story(pid: str, user=Depends(identity)):
    p = access(pid, user, True)
    p['story_confirmed'] = True
    store.save(p)
    return public(p)


@router.put('/projects/{pid}/creative-settings')
@serialized
def save_creative_settings(pid: str, body: CreativeSettings, user=Depends(identity)):
    p = access(pid, user, True)
    try:
        data = validate_settings(body.model_dump())
        for group in ('characters','scenes','props'):
            for item in data[group]:
                if item.get('image') and not store.asset(pid, item['image']).is_file():
                    raise UserError('设定参考图不存在，请重新上传')
        remember_settings(p, p.get('creative_settings'))
        remember_settings(p, p.get('creative_draft'))
        remember_settings(p, data)
        if p.get('project_type') == 'heritage':
            from scenarios.heritage_study.workflow import apply_materials
            apply_materials(p, data)
        else:
            apply_settings(p, data)
        store.save(p)
        return public(p)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/projects/{pid}/storyboard-draft/{choice}')
@serialized
def choose_storyboard_draft(pid: str, choice: str, user=Depends(identity)):
    p = access(pid, user, True)
    if choice not in {'adopt', 'discard'}:
        raise HTTPException(404, '操作不存在')
    draft = p.get('storyboard_draft')
    if not draft:
        raise HTTPException(409, '没有待确认的分镜草稿')
    if choice == 'adopt':
        if p.get('project_type') == 'heritage' and (p.get('heritage_story_stale') or draft.get('heritage_story_source') is not None) and draft.get('heritage_story_source') != p['script']:
            raise HTTPException(409, '历史脚本已更新，请根据当前旁白重新生成分镜')
        if p.get('project_type') == 'heritage' and draft.get('heritage_story_research_stamp'):
            from scenarios.heritage_study.workflow import planning_fingerprint, refresh_draft_images
            if draft['heritage_story_research_stamp'] != planning_fingerprint(p) and not refresh_draft_images(p, draft):
                raise HTTPException(409, '研学资料、时长或素材已更新，请重新解析资料并生成分镜')
        draft_settings=(draft.get('creative_draft') if p.get('project_type')=='heritage' else None) or p.get('creative_settings')
        if draft_settings:
            try:
                for shot in draft['shots']: check_references(draft_settings, shot)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        p.setdefault('storyboard_history', []).append({
            'shots': p['shots'], 'characters': p['characters'],
            'deleted_shots': p.get('deleted_shots', []), 'final': p.get('final'),
            'creative_settings':copy.deepcopy(p.get('creative_settings'))})
        p.update(draft)
        if p.get('project_type')=='heritage' and draft.get('creative_draft'):
            p['creative_settings']=copy.deepcopy(draft['creative_draft'])
        if p.get('project_type') == 'heritage': p['heritage_story_stale']=False
        # New IDs cannot collide with archived shots or their pending edits.
        for shot in p['shots']: shot['id'] = 's' + uuid.uuid4().hex
        p['deleted_shots'] = []
        p['storyboard_confirmed'] = False
        p['final_stale'] = True
    p.pop('storyboard_draft', None)
    store.save(p)
    return public(p)


@router.post('/projects/{pid}/confirm-storyboard')
@serialized
def confirm_storyboard(pid: str, user=Depends(identity)):
    p = access(pid, user, True)
    if not p['shots'] or (p.get('project_type') != 'heritage' and not p.get('creative_settings')):
        raise HTTPException(422, '请先确认创作设定并生成分镜')
    try:
        if p.get('project_type') == 'heritage':
            from scenarios.heritage_study.workflow import confirm_board
            confirm_board(p)
        else:
            for shot in p['shots']: check_references(p['creative_settings'], shot)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    p['storyboard_confirmed'] = True
    store.save(p)
    return public(p)


@router.post('/projects/{pid}/setting-image')
async def upload_setting_image(pid: str, file: UploadFile = File(...), user=Depends(identity)):
    access(pid, user, True)
    data = await file.read(12*1024*1024+1)
    if len(data) > 12*1024*1024: raise HTTPException(422, '图片不能超过12MB')
    try:
        from io import BytesIO
        with Image.open(BytesIO(data)) as img:
            if img.width*img.height > 30_000_000: raise ValueError('图片像素过大')
            with mutation_lock:
                access(pid, user, True)
                name = uuid.uuid4().hex+'.png'
                img.convert('RGB').save(store.folder(pid)/name)
        return {'image':name, 'url':f'/api/ink/projects/{pid}/assets/{name}'}
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422,'请上传有效图片') from exc


class SettingImageInput(BaseModel):
    settings: CreativeSettings
    group: Literal['characters','scenes','props']
    asset_id: str
    redesign: bool = False
    view: Literal['sheet', 'front', 'side', 'back'] = 'front'


def run_setting_image(jid, pid, user, data, group, asset_id, redesign=False, view='front'):
    crop_path = None
    try:
        p = store.load(pid)
        item = next(x for x in data[group] if x['id'] == asset_id)
        from scenarios.heritage_study.visual_reference import reference_plan, prepare_reference, material_purpose, material_description
        heritage_plan = reference_plan(p, group, item)
        guide_generation=p.get('project_type')=='heritage' and group=='characters' and asset_id==(p.get('heritage_guide') or {}).get('character_id')
        purpose = {'characters':'单个人物全身设定图，清楚展示脸部和发型；衣纹详略由所选画风决定，不要求全身精细描线。空白浅色背景，不添加其他人物，不额外安排手持器物，仅在人物描述明确要求时画该道具。只绘人物，不制作图鉴、服饰说明页或带标题的海报', 'scenes':'无人空场景设定图，只展示建筑、自然环境、光线和空间布局。人物数量为零；不画人物、手脚、剪影、人影或人物倒影，不表现递伞等剧情动作。描述中即使涉及人物活动也仅提取空间环境。留出之后放置角色的空间', 'props':'单个道具设定图，独立展示形状、材质和颜色，背景留白。人物数量为零，不画手持道具的手、人体局部、人物、剪影或人物倒影，不添加建筑和山水背景'}[group]
        if heritage_plan:
            purpose = material_purpose(group)
        if group == 'characters' and view == 'sheet':
            purpose = '同一角色的正面、侧面、背面三视图设定图，浅色空白背景，无文字无印章，不添加其他角色或剧情动作。'
        description=material_description(group,item['name'],item['desc']) if heritage_plan else item['desc']
        prompt = background_context(p)+'\n'+image_style({'creative_settings': data})+'\n'+purpose+'\n'+item['name']+'：'+description+'\n避免：'+negative_style({'creative_settings': data})
        refs = []
        from .identity_reference import identity_source, portrait_reference
        source_name = identity_source(p, item) if group == 'characters' and not redesign else None
        source_record = p.get('setting_generation_records', {}).get(source_name, {})
        source_style = source_record.get('style') or (p.get('creative_settings') or {}).get('style', '')
        source_profile = profile_for({'creative_settings': {'style': source_style}})
        target_profile = profile_for({'creative_settings': data})
        restyling = bool(source_profile and target_profile and source_profile is not target_profile)
        if source_name and view in ('front', 'sheet'):
            source = store.asset(pid, source_name)
            if restyling:
                crop_path = store.folder(pid) / (uuid.uuid4().hex + '-identity.png')
                refs.append(portrait_reference(source, crop_path))
                prompt += '\n本次跨画风重新绘制。第1张仅为同一人物的头部局部参考，保持脸型、五官比例、发际线、发髻和头饰形状；不要照搬局部图的笔墨、纸张和阴影。输出仍须为完整全身角色，不输出头像。服装版型、腰带、内领与固有色按人物文字设定，不自行换装。'
            else:
                refs.append(str(source))
            prompt += '\n本次必须按目标画风从头重新绘制整个角色。保持角色身份，用户明确要求的修改除外；旧图墨块不是服装固有色，不因保持身份而复制旧笔墨。'
        elif group == 'characters' and redesign:
            prompt += '\n本次重新设计角色，只按当前文字设定设计新形象，不沿用旧角色图。'
        if group == 'characters':
            if view == 'sheet':
                prompt += '\n最高优先级：生成一张角色三视图设定图，同一个角色从左到右并排展示正面、严格90度侧面、严格背面。三个视角等高、全身完整、头顶与脚底对齐，姿态自然。脸型、发型头饰、衣服版型、腰带、鞋子与固有色完全一致。参考图仅用于角色身份和服饰，不照搬其视角排列或旧画风。浅色空白背景，不加文字、标签、题字或印章。这是同一人的三个视角，不是三个不同角色。'
            elif view == 'front':
                prompt += '\n正面全身角色设定，脸与身体朝向观众，完整展示头顶到鞋底，双手自然下垂。'
            else:
                refs = [str(store.asset(pid, item['image']))]
                angle = '严格侧面全身，面部与身体均旋转90度' if view == 'side' else '严格背面全身，背对观众，不回头，不显示正面五官'
                prompt = background_context(p) + '\n' + image_style({'creative_settings': data}) + '\n' + item['desc'] + '\n' + angle + '。第1张是已选正面标准图，绘制同一人物的另一个视角。保持身材比例、发型头饰、服装版型、主色、腰带与鞋子一致，不换人不换装。空白背景，单人单幅，无文字，无多视图拼贴。\n避免：' + negative_style({'creative_settings': data})
        heritage_reference = None
        if heritage_plan:
            instruction, refs, heritage_reference = prepare_reference(p, store, heritage_plan)
            # Whole-building layouts come from research, not a cropped field
            # photo or a style sample depicting an unrelated subject.
            prompt = instruction + '\n' + prompt
        elif guide_generation:
            prompt += '\n这是教学虚构小向导的角色参考，只按当前人物描述与选定水墨画风设计。服饰年代仅约束人物，不画建筑复原。固定脸型、发髻数量、布巾形状、衣领、腰带与服装固有色；不参考其他人物的身份、年龄或发型。'
        else:
            prompt, refs = with_style_reference({'creative_settings': data}, prompt, refs, asset_group=group)
        generated = call_image(user, pid, prompt, refs, store.folder(pid), **({'ratio': '16:9'} if heritage_plan or group == 'characters' and view == 'sheet' else {}))
        name = uuid.uuid4().hex+'.png'
        with Image.open(generated) as img: img.convert('RGB').save(store.folder(pid)/name)
        remember_settings(p, p.get('creative_settings'))
        remember_settings(p, p.get('creative_draft'))
        remember_setting_image(p, group, item, data['style'])
        p.setdefault('setting_generation_records', {})[name] = {'style': data['style'], 'prompt': prompt, 'references': [str(ref).replace('\\', '/').rsplit('/', 1)[-1] for ref in refs], 'group': group, 'asset_id': asset_id, 'identity_source': source_name, 'reference_mode': 'heritage-research' if heritage_reference else 'portrait' if crop_path is not None else 'full' if source_name else 'text', **({'heritage_reference': heritage_reference} if heritage_reference else {})}
        if group == 'characters' and view in ('side', 'back'):
            item.setdefault('views', {})[view] = {'image': name, 'source': item['image'], 'style': data['style'], 'description': item['desc']}
        else:
            item['image'] = name
            if group == 'characters' and view == 'sheet':
                item['views'] = {}
        remember_setting_image(p, group, item, data['style'], 'generated')
        p['creative_draft'] = data
        store.save(p)
        store.finish(jid)
    except UserError as exc:
        store.finish(jid, str(exc))
    except Exception:
        store.finish(jid,'设定图生成失败，文字草稿已保留，请手动重试')
    finally:
        if crop_path is not None:
            crop_path.unlink(missing_ok=True)


@router.post('/projects/{pid}/generate-setting-image')
@serialized
def generate_setting_image(pid: str, body: SettingImageInput, user=Depends(identity)):
    p = access(pid,user,True)
    data = validate_settings(body.settings.model_dump())
    if not any(x['id']==body.asset_id for x in data[body.group]): raise HTTPException(422,'找不到该设定')
    item = next(x for x in data[body.group] if x['id'] == body.asset_id)
    if body.view in ('side', 'back') and (body.group != 'characters' or body.redesign or not item.get('image')):
        raise HTTPException(422, '请先选择正面角色图，再生成侧面或背面')
    remember_settings(p, p.get('creative_settings'))
    remember_settings(p, p.get('creative_draft'))
    remember_settings(p, data)
    p['creative_draft'] = data
    store.save(p)
    jid = store.enqueue(pid,user['id'],'asset-image')
    pool.submit(run_setting_image,jid,pid,user,data,body.group,body.asset_id,body.redesign,body.view)
    return public(store.load(pid))


def creative_refs(p, shot):
    settings = p.get('creative_settings')
    if not settings: return []
    items = [x for x in settings['characters'] if x['id'] in shot['character_ids']]
    items += [x for x in settings['scenes'] if x['id']==shot.get('scene_id')]
    items += [x for x in settings['props'] if x['id'] in shot.get('prop_ids',[])]
    from scenarios.heritage_study.visit_route import compatible_reference
    items = [item for item in items if compatible_reference(p,shot,item)]
    check_material_styles(p, items)
    text = shot.get('camera', '') + ' ' + shot.get('content', '')
    angle = 'back' if '背面' in text or '背对' in text else 'side' if '侧面' in text or '侧身' in text else 'front'
    refs = []
    for item in items:
        name = item.get('image')
        view = item.get('views', {}).get(angle)
        if view and view['source'] == name and view['style'] == settings['style'] and view['description'] == item['desc']:
            name = view['image']
        if name:
            from scenarios.heritage_study.material_views import material_reference
            refs.append(material_reference(p,shot,{**item,'image':name},store))
    return refs[:6]


class BackgroundInput(BaseModel):
    era: str = Field(default='', max_length=80)


@router.put('/projects/{pid}/background')
@serialized
def save_background(pid: str, body: BackgroundInput, user=Depends(identity)):
    p = access(pid, user, True)
    era = body.era.strip()
    previous = (p.get('background') or {}).get('era', '')
    p['background'] = {'era': era, 'source': 'user' if era else 'unspecified'}
    if era != previous:
        for shot in p['shots']:
            invalidate(p, shot, reason='时代背景已调整，请核对人物、场景和道具')
        p['storyboard_confirmed'] = False
    store.save(p)
    return public(p)


@router.get('/reference-library')
def local_reference_library(user=Depends(identity)):
    from .reference_library import ERA_CHOICES, reference_info
    return {'choices': [reference_info(era) for era in ERA_CHOICES]}


@router.get('/projects/{pid}/setting-history/{group}/{asset_id}')
def setting_history(pid: str, group: Literal['characters','scenes','props'], asset_id: str, include_deleted: bool = False, user=Depends(identity)):
    p = access(pid, user)
    return {'items': [{**item, 'image_url': f'/api/ink/projects/{pid}/assets/{item["image"]}'}
                      for item in setting_versions(p, group, asset_id, include_deleted)
                      if store.asset(pid, item['image']).is_file()]}


class SelectSettingImage(SettingImageInput):
    image: str
    source: Literal['history', 'upload'] = 'history'


@router.post('/projects/{pid}/select-setting-image')
@serialized
def select_setting_image(pid: str, body: SelectSettingImage, user=Depends(identity)):
    p = access(pid, user, True)
    data = validate_settings(body.settings.model_dump())
    item = next((x for x in data[body.group] if x['id'] == body.asset_id), None)
    if item is None:
        raise HTTPException(422, '找不到该设定')
    if not store.asset(pid, body.image).is_file():
        raise HTTPException(404, '图片不存在')
    if body.source == 'history' and body.image not in {x['image'] for x in setting_versions(p, body.group, body.asset_id)}:
        raise HTTPException(422, '图片不属于该设定的历史记录')
    remember_settings(p, p.get('creative_settings'))
    remember_settings(p, p.get('creative_draft'))
    remember_settings(p, data)
    item['image'] = body.image
    remember_setting_image(p, body.group, item, data['style'], body.source)
    p['creative_draft'] = data
    store.save(p)
    return public(p)


# Register scenario-local video editing after the API helpers are defined.
from .video_editing import install as install_video_editing
import sys as _sys
install_video_editing(_sys.modules[__name__])

from scenarios.heritage_study.api import install as install_heritage
install_heritage(_sys.modules[__name__])

from .history_retention import install as install_history_retention
install_history_retention(_sys.modules[__name__])
