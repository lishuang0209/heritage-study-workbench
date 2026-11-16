"""Scene geography shared by planning, stills and video; screen sides are shot-local."""
import copy
from pydantic import Field, model_validator
from .domain import Strict, UserError

SPATIAL_POLICY = 2
PLANNING_MARKER = '\n场景空间关系（规划、首帧和动作共用地标关系，画面左右随每镜机位变化）：'


class Placement(Strict):
    character_id: str = Field(min_length=1, max_length=64)
    anchor: str = Field(default='', max_length=400)


class SpatialReference(Strict):
    shot_id: str = Field(min_length=1, max_length=100)
    image: str = Field(min_length=1, max_length=255)


class SceneLayout(Strict):
    scene_id: str = Field(min_length=1, max_length=2000)
    enabled: bool = True
    placements: list[Placement] = Field(default_factory=list, max_length=2)
    relation: str = Field(default='', max_length=600)
    references: list[SpatialReference] = Field(default_factory=list, max_length=2)

    @model_validator(mode='before')
    @classmethod
    def migrate_screen_layout(cls, value):
        # Old left/right IDs only associate their physical anchor text with a
        # character. They must never become a new screen-side restriction.
        if not isinstance(value, dict) or 'left_id' not in value:
            return value
        old = copy.deepcopy(value)
        placements = [{'character_id': old.pop(side + '_id'), 'anchor': old.pop(side + '_anchor', '')} for side in ('left', 'right')]
        sid, image = old.pop('reference_shot_id', None), old.pop('reference_image', None)
        old.setdefault('placements', placements)
        old.setdefault('references', [{'shot_id': sid, 'image': image}] if sid and image else [])
        return old


def scene_key(shot):
    return shot.get('scene_id') or shot.get('scene') or ''


def layouts_for(p):
    chars = (p.get('creative_settings') or {}).get('characters', p.get('characters', []))
    if not chars:
        return []
    ids = {c['id'] for c in chars}
    scenes = (p.get('creative_settings') or {}).get('scenes', [])
    keys = list(dict.fromkeys([x['id'] for x in scenes if isinstance(x.get('id'), str) and x['id']] + [scene_key(s) for s in p.get('shots', []) if scene_key(s)]))
    stored = {x['scene_id']: x for x in p.get('scene_layouts', [])}
    result = []
    for key in keys:
        old = SceneLayout.model_validate(stored[key]).model_dump() if key in stored else SceneLayout(scene_id=key).model_dump()
        anchors = {x['character_id']: x['anchor'] for x in old['placements'] if x['character_id'] in ids}
        old['placements'] = [{'character_id': c['id'], 'anchor': anchors.get(c['id'], '')} for c in chars]
        result.append(old)
    return result


def layout_for(p, shot):
    return next((x for x in layouts_for(p) if x['scene_id'] == scene_key(shot) and x['enabled']), None)


def spatial_prompt(p, shot, *, video=False):
    # The scene-position editor is retired. Keep generic continuity guidance,
    # never inject archived placements or reference images into new generation.
    rules = [
        '本场空间连续性：固定人物与场景地标的关系，不固定人物在画面中的左、右。',
        '本镜首帧与构图决定拍摄位置、角度和画面左右。换机位或反打可以使画面左右变化，不把屏幕左右变化等同于人物在场景中换位；不把参考图左右顺序机械复制到本镜。',
        '人物位置按剧情阶段衔接；出发位置、经过的门槛或通道、到达位置必须合理。明确走动、进出门或转身时允许位置与朝向改变；没有这些动作时不凭空穿门、跨到对方位置或交换门内门外。',
        '对话视线按本镜机位及对方实际位置确定，可以是画外视线或正反打；只有相互注视的镜头才要求看向对方，不全场强制看左或看右，也不一律禁止面对镜头。',
        '出场名单只是身份引用。单人近景允许居中；明确画外、不入镜或只出现手部的角色保持画外或局部，不为展示空间关系拉远成双人全景。',
    ]
    if video:
        rules.append('本段从实际输入首帧继续动作；保持首帧中已有的场景位置，按明确的动作路径走动。镜头内不自行切镜、反打或镜像，不为纠正首帧而瞬移；需要换拍摄方向时在另一个镜头完成。')
    return '\n'.join(rules)


def planning_context(p):
    names = {x['id']: x['name'] for x in (p.get('creative_settings') or {}).get('scenes', [])}
    return '\n'.join('场景：' + names.get(x['scene_id'], x['scene_id']) + '（' + x['scene_id'] + '）\n' + spatial_prompt(p, {'scene_id': x['scene_id']}) for x in layouts_for(p) if x['enabled'])


def spatial_reference_paths(p, shot, store):
    """Archived scene-position references are no longer generation inputs."""
    return []


def with_spatial_reference(p, shot, prompt, refs, store):
    """Only user-confirmed frozen geography references, potentially opposite views."""
    paths = spatial_reference_paths(p, shot, store)
    if not paths:
        return prompt, list(refs)
    images = list(refs) + paths
    indexes = '、'.join(str(i) for i in range(len(refs)+1, len(images)+1))
    rule = (f'参考图分工补充：第{indexes}张为本场空间参考。它们可以是同一场景的不同拍摄方向或剧情阶段。'
            '只参考门、门槛、檐下等场景地标与人物的关系，不复制其画面左右、机位或景别；不把不同角度的图当成额外人物或额外建筑。'
            '不是本镜首帧，不复制其动作、道具开合或归属，人物当前状态按本镜剧情阶段；画风仍以项目画风样张为准。'
            '按本镜取近景或特写，画外角色不强行补入。')
    return prompt + '\n' + rule, images
