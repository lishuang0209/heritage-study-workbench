"""Per-project setting image versions, separate from editable asset schema."""
import time

GROUPS = ('characters', 'scenes', 'props')

def remember(p, group, item, style='', source='saved'):
    image = item.get('image')
    if not image:
        return
    items = p.setdefault('setting_image_history', {}).setdefault(group + ':' + item['id'], [])
    if not any(x['image'] == image for x in items):
        items.append({'image': image, 'created': time.time(), 'source': source,
                      'name': item['name'], 'desc': item['desc'], 'style': style})

def remember_settings(p, settings):
    if settings:
        for group in GROUPS:
            for item in settings[group]:
                remember(p, group, item, settings.get('style', ''))

def versions(p, group, asset_id, include_deleted=False):
    import copy
    snapshot = copy.deepcopy(p)
    remember_settings(snapshot, p.get('creative_settings'))
    remember_settings(snapshot, p.get('creative_draft'))
    protected = {}
    for key, label in (('creative_settings','已确认设定正在使用此图'), ('creative_draft','当前设定草稿正在使用此图')):
        for item in (p.get(key) or {}).get(group, []):
            if item['id'] != asset_id: continue
            for name in [item.get('image')] + [view.get('image') for view in item.get('views', {}).values()]:
                if name: protected[name] = label
    from .history_retention import annotated_versions
    items = list(reversed(snapshot.get('setting_image_history', {}).get(group + ':' + asset_id, [])))
    return annotated_versions(p, 'setting', group + ':' + asset_id, items, 'image', protected, include_deleted)
