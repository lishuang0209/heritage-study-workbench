"""Confirmed production assets and explicit shot references."""
import copy
from pydantic import Field
from .domain import Strict, Cast, UserError, invalidate, parse_json


class Asset(Strict):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=80)
    desc: str = Field(min_length=1, max_length=2000)
    image: str | None = None


class CharacterView(Strict):
    image: str
    source: str
    style: str
    description: str


class Character(Cast):
    image: str | None = None
    views: dict[str, CharacterView] = Field(default_factory=dict)



class CreativeSettings(Strict):
    characters: list[Character] = Field(max_length=2)
    scenes: list[Asset] = Field(min_length=1, max_length=12)
    props: list[Asset] = Field(max_length=20)
    style: str = Field(min_length=1, max_length=1000)


def validate_settings(raw):
    value = CreativeSettings.model_validate(parse_json(raw) if isinstance(raw, str) else raw).model_dump()
    for group in ('characters', 'scenes', 'props'):
        if group == 'characters':
            for item in value[group]:
                if set(item['views']) - {'side', 'back'}:
                    raise UserError('角色视角无效')
        ids = [x['id'] for x in value[group]]
        if len(ids) != len(set(ids)):
            raise UserError('设定编号不能重复')
    return value


def check_references(settings, shot):
    if not set(shot['character_ids']) <= {x['id'] for x in settings['characters']}:
        raise UserError('请先在创作设定中确认出场角色')
    if shot.get('scene_id') not in {x['id'] for x in settings['scenes']}:
        raise UserError('请为每个分镜选择已确认的场景')
    if not set((shot.get('prop_ids') or [])) <= {x['id'] for x in settings['props']}:
        raise UserError('镜头引用了未确认的道具')


def apply_settings(p, data):
    previous = p.get('creative_settings')
    if previous == data:
        p['creative_draft'] = None
        return
    old = previous or {'characters': p['characters'], 'scenes': [], 'props': [], 'style': data['style']}
    changed = {}
    for group in ('characters', 'scenes', 'props'):
        before = {x['id']: {k:x.get(k) for k in ('name','desc','image')} for x in old[group]}
        after = {x['id']: {k:x.get(k) for k in ('name','desc','image')} for x in data[group]}
        changed[group] = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    for s in p['shots']:
        if not s.get('scene_id'):
            match = next((x for x in data['scenes'] if x['name'] == s['scene']), None)
            if match: s['scene_id'] = match['id']
        s['prop_ids'] = s.get('prop_ids') or []
        affected = (bool(set(s['character_ids']) & changed['characters']) or
                    (previous is not None and (s.get('scene_id') in changed['scenes'] or bool(set(s['prop_ids']) & changed['props']) or old['style'] != data['style'])))
        if affected and previous is not None:
            invalidate(p, s, reason='本镜引用的人物、场景、道具或画风设定已调整，请重新确认')
    p['creative_settings'] = copy.deepcopy(data)
    p['creative_draft'] = None
    p['characters'] = copy.deepcopy(data['characters'])
    p['story_confirmed'] = True
    p['storyboard_confirmed'] = False
    baseline = p.get('baseline') or {}
    p['baseline'] = {**baseline, 'version': baseline.get('version',0)+1,
        'characters': [{'character_id':x['id'],'desc':x['desc'],'visibility':'clear','match_status':'consistent'} for x in data['characters']],
        'ink_style': baseline.get('ink_style', {}), 'reference_images': []}


def settings_context(p, shot):
    from .styles import image_style
    settings = p.get('creative_settings')
    if not settings:
        return ''
    scene = next((x for x in settings['scenes'] if x['id'] == shot.get('scene_id')), None)
    props = [x for x in settings['props'] if x['id'] in (shot.get('prop_ids') or [])]
    characters = [x for x in settings['characters'] if x['id'] in shot['character_ids']]
    refs = [x['name'] for x in characters + ([scene] if scene else []) + props if x.get('image')]
    return '\n'.join(['参考设定图顺序：' + '、'.join(refs[:6]), '统一画风：'+image_style(p),
        '已确认场景：'+(scene['name']+'；'+scene['desc'] if scene else shot['scene']),
        '关键道具：'+'；'.join(x['name']+'：'+x['desc'] for x in props)])


def check_visible_characters(p, shot):
    """Conservative local check; dialogue text is not evidence of on-screen presence."""
    import re
    characters = (p.get('creative_settings') or {}).get('characters', p.get('characters', []))
    text = shot.get('content', '')
    aliases = {}
    for character in characters:
        name = character['name']
        terms = {name}
        # Only strip common descriptive prefixes, never arbitrary personal-name characters.
        short = re.sub(r'^(?:年轻|青年|年老|老年|中年|守寺)', '', name)
        if len(short) >= 2:
            terms.add(short)
        for term in terms:
            aliases.setdefault(term, set()).add(character['id'])
    missing = []
    for character in characters:
        if character['id'] in shot['character_ids']:
            continue
        terms = [term for term, ids in aliases.items() if len(ids) == 1 and character['id'] in ids]
        names = '(?:' + '|'.join(re.escape(term) for term in terms) + ')' if terms else r'(?!)'
        # Explicit off-screen declarations also cover later relational mentions.
        offscreen = re.search(
            r'(?:画外|画面外|镜头外|镜外)(?:的)?' + names +
            '|' + names + r'(?:始终|仍然|仍|仅|只)?(?:在画外|在画面外|在镜头外|不在画面(?:内|中)|不入镜|不出镜|未出镜|未入镜|未出现)', text)
        if offscreen:
            continue
        if any(term in text for term in terms):
            missing.append(character['name'])
    if missing:
        raise UserError('首帧画面提到了“' + '、'.join(missing) + '”，但未勾选出场人物。请在编辑中补选；如果人物在画外，请在首帧描述中注明“画外”或“不入镜”。')
