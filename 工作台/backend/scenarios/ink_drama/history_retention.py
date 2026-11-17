"""Recoverable, list-scoped history removal. Never remove an underlying asset file."""
import time
from typing import Literal

from fastapi import Depends, HTTPException


def annotated_versions(p, kind, scope, items, file_key, protected, include_deleted=False):
    removed = p.get('history_trash', {}).get(kind + ':' + scope, {})
    result = []
    for item in items:
        name = item[file_key]
        reason = protected.get(name, '')
        deleted_at = removed.get(name) if not reason else None
        if deleted_at and not include_deleted:
            continue
        result.append({**item, 'deleted_at': deleted_at,
                       'can_delete': not reason and not deleted_at, 'delete_block_reason': reason})
    return result


def install(api):
    def collection(p, kind, scope):
        if kind == 'setting':
            group, separator, asset_id = scope.partition(':')
            if not separator or group not in ('characters', 'scenes', 'props') or not asset_id:
                raise HTTPException(404, '设定历史不存在')
            return api.setting_versions(p, group, asset_id, include_deleted=True), 'image'
        shot = next((shot for shot in p['shots'] if shot['id'] == scope), None)
        if shot is None:
            raise HTTPException(404, '镜头不存在')
        if kind == 'image':
            return api.image_history(p, shot, include_deleted=True), 'image'
        return api.video_history(p, shot, include_deleted=True), 'video'

    def change(pid, kind, scope, name, user, restore):
        p = api.access(pid, user, True)
        items, file_key = collection(p, kind, scope)
        item = next((item for item in items if item[file_key] == name), None)
        if not item or not api.store.asset(pid, name).is_file():
            raise HTTPException(404, '该版本不属于此历史列表或文件已不存在')
        bucket = kind + ':' + scope
        if restore:
            if not item.get('deleted_at'):
                raise HTTPException(409, '该版本不在已删除列表，请刷新后重试')
            p['history_trash'][bucket].pop(name)
        else:
            if item.get('delete_block_reason'):
                raise HTTPException(409, item['delete_block_reason'])
            if item.get('deleted_at'):
                return {'ok': True}
            p.setdefault('history_trash', {}).setdefault(bucket, {})[name] = time.time()
        api.store.save(p)
        api.store.event(pid, user['id'], 'restore_history' if restore else 'delete_history',
                        {'kind':kind, 'scope':scope, 'file':name})
        return {'ok': True}

    @api.router.delete('/projects/{pid}/history/{kind}/{scope}/{name}')
    @api.serialized
    def delete_version(pid:str, kind:Literal['image','video','setting'], scope:str, name:str, user=Depends(api.identity)):
        return change(pid, kind, scope, name, user, False)

    @api.router.post('/projects/{pid}/history/{kind}/{scope}/{name}/restore')
    @api.serialized
    def restore_version(pid:str, kind:Literal['image','video','setting'], scope:str, name:str, user=Depends(api.identity)):
        return change(pid, kind, scope, name, user, True)
