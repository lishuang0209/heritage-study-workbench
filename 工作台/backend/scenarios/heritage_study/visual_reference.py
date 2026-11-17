"""Use the station's real subject, independently of ink-style sample subjects."""
import copy
import re
import uuid

from PIL import Image, UnidentifiedImageError

from scenarios.ink_drama.domain import UserError
from .detail_crop import crop_detail


def reference_plan(p, group, item):
    if p.get('project_type') != 'heritage' or group not in ('props', 'scenes'):
        return None
    station = p.get('heritage_station') or {}
    normalize = lambda value: re.sub(r'\s+', '', value or '').casefold()
    target = normalize(station.get('component' if group == 'props' else 'building'))
    name = normalize(item['name'])
    # Associate the actual observation target, never every unrelated story prop.
    if min(len(target), len(name)) < 2 or not (target in name or name in target):
        return None
    photo = station.get('panorama') or {}
    mark = photo.get('mark')
    mode = 'crop' if group == 'props' and mark and mark['kind'] == 'rectangle' else 'arrow' if group == 'props' else 'full'
    error = ''
    if not photo.get('image'):
        error = '请先在第2步上传现场定位图，再根据实拍生成设定图'
    elif group == 'props' and not mark:
        error = '请先在第2步标注目标构件并保存，再根据实拍生成设定图'
    return dict(group=group, asset_id=item['id'], asset_name=item['name'],
                source_image=photo.get('image'), mode=mode, error=error)


def prepare_reference(p, store, plan):
    """Validate and retain the exact photographic input for generation provenance."""
    if plan['error']:
        raise UserError(plan['error'])
    photo = p['heritage_station']['panorama']
    source = store.asset(p['id'], photo['image'])
    if not source.is_file():
        raise UserError('现场定位图文件不存在，请在第2步重新上传并标注')
    path = source
    geometry = None
    try:
        # Validate before reserving a paid call, including the uncropped scene path.
        with Image.open(source) as image:
            image.verify()
        if plan['mode'] in ('crop', 'arrow'):
            path = store.folder(p['id']) / (uuid.uuid4().hex + '-heritage-reference.jpg')
            if plan['mode'] == 'crop':
                geometry = crop_detail(source, photo['mark'], path)
            else:
                from .media import annotated_photo
                # An arrow identifies its tip, not a rectangular crop boundary.
                annotated_photo(store, p['id'], {**photo, 'mode': 'contain'}).save(path, 'JPEG', quality=94)
    except (OSError, UnidentifiedImageError) as exc:
        raise UserError('现场定位图无法读取，请在第2步重新上传') from exc
    subject = ('仅转绘框选区域内的目标构件，保留可见构件的层叠、连接、相对位置、比例和固有色；周围梁柱只保留理解连接所需的部分，不拆成手持器物。'
               if plan['mode'] == 'crop' else
               '仅转绘箭头尖端所指的目标构件，不把箭头的起点和终点当作构件边界；不画出红白标注线。'
               if plan['mode'] == 'arrow' else
               '按实拍中可见的建筑部位、视角和空间关系绘制，不凭局部照片补造完整外观。')
    instruction = ('第1张是本讲解站上传的真实照片，是本次主体形制的依据。' + subject +
                   '只将真实主体转绘为指定水墨画风，不保留摄影质感；不推测照片遮挡或不可见的结构，不画照片标注、文字、水印或其他物体。')
    record = {**plan, 'image': path.name, 'station_version': p.get('heritage_version', 0),
              'mark': copy.deepcopy(photo.get('mark')),
              'credits': {key: photo.get(key, '') for key in ('source', 'author', 'license')}}
    if geometry:
        record['crop'] = geometry['crop']
    return instruction, [str(path)], record


def decorate_references(p):
    settings = p.get('creative_draft') or p.get('creative_settings') or {}
    plans = []
    for group in ('scenes', 'props'):
        for item in settings.get(group, []):
            plan = reference_plan(p, group, item)
            if plan:
                if plan['source_image']:
                    plan['preview_url'] = f'/api/ink/projects/{p["id"]}/heritage/photos/panorama/preview?v={p.get("heritage_version", 0)}'
                plans.append(plan)
    p['heritage_setting_references'] = plans
    return p
