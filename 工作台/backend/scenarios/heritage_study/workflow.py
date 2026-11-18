"""Storyboard first; visual materials are reviewed afterwards without extra model calls."""
import copy
import hashlib
import json
import uuid

from scenarios.ink_drama.creative import apply_settings, check_references, validate_settings
from scenarios.ink_drama.domain import UserError


def planning_research(project):
    station = project.get('heritage_station') or {}
    return {
        'building': station.get('building', ''),
        'component': station.get('component', ''),
        'material': station.get('checked_description', ''),
        'instruction': station.get('instruction', ''),
        'question': station.get('question', ''),
        **({'guide':copy.deepcopy(project['heritage_guide'])} if project.get('heritage_guide') else {}),
        'photos': [{
            'slot': slot, 'uploaded': True, 'mark': copy.deepcopy(photo.get('mark')),
            'note': '已关联实拍，文本分镜阶段未识别照片内容，不据此推断未提供的外观或环境。',
        } for slot in ('panorama', 'detail') if (photo := station.get(slot)) and photo.get('image')],
    }


def planning_fingerprint(project):
    from .timing import timing_for
    data=dict(research=planning_research(project),version=project.get('heritage_version',0),
              narration=project['script'],duration=timing_for(project)['intro'],settings=planning_settings(project))
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def refresh_draft_images(project, draft):
    """Rebase a staged manifest only when its reference files alone changed."""
    previous = draft.get('creative_draft')
    if not previous or planning_fingerprint({**project, 'creative_settings': previous}) != draft.get('heritage_story_research_stamp'):
        return False
    current = planning_settings(project)
    comparable = copy.deepcopy(current)
    for group in ('characters', 'scenes', 'props'):
        for old, new in zip(previous[group], comparable[group]):
            for key in ('image', 'views'):
                if key in old:
                    new[key] = old[key]
                else:
                    new.pop(key, None)
    if comparable != previous:
        return False
    draft.update(creative_draft=current, heritage_story_research_stamp=planning_fingerprint(project))
    return True


def planning_settings(project):
    existing = project.get('creative_settings') or project.get('creative_draft')
    if existing:
        from .guide import manifest
        return manifest(project,existing)
    station = project.get('heritage_station') or {}
    building = station.get('building', '').strip()
    if not building:
        raise UserError('请先在讲解站资料中填写建筑名称，再生成分镜')
    component = station.get('component', '').strip()
    result=validate_settings(dict(
        characters=copy.deepcopy(project.get('characters') or []),
        scenes=[dict(id='heritage_building', name=building, desc='依据研学资料呈现'+building+'的完整外观、建筑体量与整体布局。')],
        props=[dict(id='heritage_component', name=component, desc='依据研学资料呈现'+component+'的完整形制、层叠与连接关系。')] if component else [],
        style='水墨风格 · 工笔淡彩，细线薄染，清雅淡彩，低饱和配色，留白与自然笔触',
    ))
    from .guide import manifest
    return manifest(project,result)


def check_board_references(project, shot):
    materials = planning_settings(project)
    candidate = copy.deepcopy(shot)
    # Legacy/manual shots may have a scene name before a material ID is assigned.
    # The final binding is made atomically when the storyboard is confirmed.
    if not candidate.get('scene_id'):
        candidate['scene_id'] = materials['scenes'][0]['id']
    check_references(materials, candidate)


def confirm_board(project):
    if project.get('heritage_story_stale'):
        raise UserError('历史旁白已更新，请重新生成分镜并采用新草稿，再确认分镜')
    materials = planning_settings(project)
    shots = copy.deepcopy(project['shots'])
    for shot in shots:
        if not shot.get('scene_id'):
            scene = next((item for item in materials['scenes'] if item['name'] == shot['scene']), None)
            if scene is None:
                scene = dict(id='scene_'+uuid.uuid4().hex[:12], name=shot['scene'], desc=shot['scene'])
                materials['scenes'].append(scene)
            shot['scene_id'] = scene['id']
        check_references(materials, shot)
    materials = validate_settings(materials)
    # Publish the manifest and bindings together, only after validating all shots.
    project.update(shots=shots, creative_draft=materials, storyboard_confirmed=True)


def apply_materials(project, data):
    guide=project.get('heritage_guide') or {}
    cid=guide.get('character_id')
    if cid and any(cid in s['character_ids'] for s in project['shots']):
        actor=next((c for c in data['characters'] if c['id']==cid),None)
        if not actor or not actor.get('image'):raise UserError('请先为小向导生成或上传角色参考图，再确认素材与画风')
    reviewed = bool(project.get('storyboard_confirmed'))
    for shot in project['shots']:
        candidate = copy.deepcopy(shot)
        if not candidate.get('scene_id'):
            scene = next((item for item in data['scenes'] if item['name'] == shot['scene']), None)
            if scene:
                candidate['scene_id'] = scene['id']
        check_references(data, candidate)
    apply_settings(project, data)
    actor=next((c for c in data['characters'] if c['id']==cid),None)
    if guide and actor and (guide['name']!=actor['name'] or guide['desc']!=actor['desc']):
        project['heritage_guide']={**guide,'name':actor['name'],'desc':actor['desc']}
        project['heritage_guide_version']=project.get('heritage_guide_version',0)+1
    # Changing a reference image/style invalidates media, not the reviewed shot plan.
    project['storyboard_confirmed'] = reviewed
