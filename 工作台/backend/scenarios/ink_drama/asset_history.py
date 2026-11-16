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

def versions(p, group, asset_id):
    import copy
    snapshot = copy.deepcopy(p)
    remember_settings(snapshot, p.get('creative_settings'))
    remember_settings(snapshot, p.get('creative_draft'))
    return list(reversed(snapshot.get('setting_image_history', {}).get(group + ':' + asset_id, [])))
