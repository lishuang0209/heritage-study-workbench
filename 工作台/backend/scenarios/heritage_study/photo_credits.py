"""Offline attribution for verified source images and explicit uploader choices."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    entries = json.loads(Path(__file__).with_name('photo_catalog.json').read_text())
    return {digest: {k: entry[k] for k in ('source', 'author', 'license', 'credit_kind')}
            for entry in entries for digest in entry['hashes']}


def recognize(data):
    credit = catalog().get(hashlib.sha256(data).hexdigest())
    return dict(credit) if credit else None


def selected_credits(kind):
    if kind == 'self':
        return dict(source='上传者本人拍摄', author='上传者本人',
                    license='上传者确认可用于本次研学短片与任务卡', credit_kind=kind)
    if kind == 'authorized':
        return dict(source='上传者提供的授权照片', author='照片提供方（上传者确认授权）',
                    license='上传者声明已获本次研学短片与任务卡的使用授权', credit_kind=kind)
    return None


def fill_existing(store, p):
    changed = False
    for photo in (p.get('heritage_station') or {}).values():
        if not isinstance(photo, dict) or not photo.get('image'):
            continue
        if all(photo.get(k, '').strip() for k in ('source', 'author', 'license')):
            continue
        path = store.asset(p['id'], photo['image'])
        credit = recognize(path.read_bytes()) if path.is_file() else None
        if credit:
            for key, value in credit.items():
                if key == 'credit_kind' or not photo.get(key, '').strip():
                    photo[key] = value
            changed = True
    station=p.get('heritage_station') or {}
    detail=station.get('detail');panorama=station.get('panorama')
    if detail and panorama and detail.get('derived_from')==panorama['image']:
        for key in ('source','author','license','credit_kind'):
            value=panorama.get(key,'manual' if key=='credit_kind' else '')
            if detail.get(key)!=value:
                detail[key]=value;changed=True
    return changed
