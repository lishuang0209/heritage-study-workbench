import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from scenarios.ink_drama.domain import UserError
from .material_import import MAX_MATERIAL_CHARACTERS


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Mark(Strict):
    kind: Literal['rectangle', 'arrow'] = 'rectangle'
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def visible(self):
        if abs(self.x2-self.x) + abs(self.y2-self.y) < .02:
            raise ValueError('标注太小，请重新框选或画箭头')
        if self.kind == 'rectangle' and min(abs(self.x2-self.x), abs(self.y2-self.y)) < .01:
            raise ValueError('矩形需要有宽度和高度')
        return self


class Photo(Strict):
    image: str = Field(min_length=1, max_length=100)
    source: str = Field(default='', max_length=240)
    author: str = Field(default='', max_length=80)
    license: str = Field(default='', max_length=200)
    credit_kind: Literal['manual', 'unresolved', 'catalog', 'self', 'authorized'] = 'manual'
    mark: Mark | None = None
    derived_from: str | None = Field(default=None, max_length=100)
    derived_mark: Mark | None = None
    mode: Literal['contain', 'cover'] = 'contain'
    focus_x: float = Field(default=.5, ge=0, le=1)
    focus_y: float = Field(default=.5, ge=0, le=1)


class Station(Strict):
    building: str = Field(default='', max_length=80)
    name: str = Field(default='', max_length=80)
    component: str = Field(default='', max_length=80)
    grade: str = Field(default='', max_length=40)
    standing_position: str = Field(default='', max_length=300)
    checked_description: str = Field(default='', max_length=MAX_MATERIAL_CHARACTERS)
    objective: str = Field(default='', max_length=300)
    instruction: str = Field(default='', max_length=600)
    question: str = Field(default='', max_length=160)
    panorama: Photo | None = None
    detail: Photo | None = None


def empty_station():
    return Station().model_dump()


def invalidate(p):
    p['heritage_version'] = p.get('heritage_version', 0) + 1
    p['heritage_confirmed_version'] = None
    p['final_stale'] = bool(p.get('final'))
    p['task_card_stale'] = bool(p.get('task_card'))


def crop_bounds(width, height, photo):
    if photo['mode'] == 'contain':
        return (0., 0., 1., 1.)
    desired = 16/9
    ratio = width/height
    cw, ch = (desired/ratio, 1.) if ratio > desired else (1., ratio/desired)
    return ((1-cw)*photo['focus_x'], (1-ch)*photo['focus_y'], cw, ch)


def observation_guidance(station):
    """Keep saved legacy positions visible in the unified instruction, without writes."""
    position = station.get('standing_position', '').strip()
    instruction = station.get('instruction', '').strip()
    if not position or position in instruction: return instruction
    if not instruction or instruction in position: return position
    return position + ('' if position.endswith(('。','！','？','!','?','；',';')) else '。') + instruction


def derived_detail_stale(station):
    detail = station.get('detail') or {}
    if not detail.get('derived_from'): return False
    panorama = station.get('panorama') or {}
    return detail['derived_from'] != panorama.get('image') or detail.get('derived_mark') != panorama.get('mark')


def validate_detail_link(p):
    station = p.get('heritage_station') or {}
    detail = station.get('detail') or {}
    record = p.get('heritage_uploads', {}).get(detail.get('image'), {})
    if record.get('derived_from'):
        if (detail.get('derived_from') != record['derived_from'] or
                detail.get('derived_mark') != record['derived_mark'] or detail.get('mark') != record['mark']):
            raise UserError('自动特写的关联信息或标注已变化，请从定位图重新生成特写')
    elif detail.get('derived_from') or detail.get('derived_mark'):
        raise UserError('特写关联信息无效，请重新生成或另传实拍照片')
    if derived_detail_stale(station):
        raise UserError('定位图或标注已变化，请更新特写，或移除特写后继续')


def validate_ready(p, store):
    station = Station.model_validate(p.get('heritage_station') or {}).model_dump()
    labels = {'building':'建筑名称','name':'讲解站名称','component':'目标构件','grade':'适用年级',
              'checked_description':'研学资料',
              'objective':'教学目标','instruction':'观察指引','question':'观察问题'}
    missing = [label for key,label in labels.items() if not (observation_guidance(station) if key == 'instruction' else station[key].strip())]
    if not station['panorama']: missing.append('现场定位图')
    if missing: raise UserError('请补齐：'+'、'.join(missing))
    validate_detail_link(p)
    from PIL import Image
    for slot, label in (('panorama','定位图'),('detail','构件特写')):
        photo = station[slot]
        if not photo: continue
        if not photo['mark']: raise UserError(label+'还没有有效标注')
        if not all(photo[k].strip() for k in ('source','author','license')):
            raise UserError('请为'+label+'选择照片来源，或使用已识别的素材')
        path = store.asset(p['id'], photo['image'])
        if not path.is_file(): raise UserError(label+'文件不存在，请重新上传')
        with Image.open(path) as image: bounds = crop_bounds(*image.size, photo)
        x,y,w,h = bounds; mark = photo['mark']
        # Leave room for the stroke and arrow head, not only its center line.
        pad = .012
        if not all(x+pad <= mark[k] <= x+w-pad for k in ('x','x2')) or not all(y+pad <= mark[k] <= y+h-pad for k in ('y','y2')):
            raise UserError(label+'的标注靠近边缘或在横屏裁切之外，请调整标注或使用完整保留')
    return station


def snapshot(p):
    timing = {'timing':p['heritage_timing'],'timing_version':p.get('heritage_timing_version',0)} if p.get('heritage_timing') else {}
    return hashlib.sha256(json.dumps({'layout':'landscape-v1','version':p.get('heritage_version',0),
        'station':p.get('heritage_station'), 'script':p.get('heritage_script'), **timing,
        'shots':[(s['id'],s.get('revision'),s.get('rendered')) for s in p['shots']]},
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def decorate(p):
    p['project_type'] = p.get('project_type', 'ink')
    if p['project_type'] != 'heritage': return p
    current_stamp = snapshot(p)
    from .timing import timing_for
    p['heritage_timing']=timing_for(p)
    p['heritage_timing_version']=p.get('heritage_timing_version',0)
    pid = p['id']; version = p.get('heritage_version',0)
    p['heritage_station'] = p.get('heritage_station') or empty_station()
    p['heritage_version'] = version
    for slot in ('panorama','detail'):
        photo = p['heritage_station'].get(slot)
        if photo:
            photo['url'] = f'/api/ink/projects/{pid}/assets/{photo["image"]}'
            photo['preview_url'] = f'/api/ink/projects/{pid}/heritage/photos/{slot}/preview?v={version}&layout=landscape-v1'
    p['heritage_ready'] = p.get('heritage_confirmed_version') == version
    p['task_card_url'] = f'/api/ink/projects/{pid}/assets/{p["task_card"]}' if p.get('task_card') else None
    if p.get('heritage_export_stamp') != current_stamp:
        if p.get('final'): p['final_stale'] = True
        if p.get('task_card'): p['task_card_stale'] = True
    if p.get('final') and p.get('final_media_format', {}).get('ratio') != '16:9':
        p['final_stale'] = True
    from .visual_reference import decorate_references
    return decorate_references(p)
