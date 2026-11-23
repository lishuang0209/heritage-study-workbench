"""History deletion is reversible and cannot remove live media or another list's entry."""
import copy

import pytest

from test_ink_demo import api, project, setup
from scenarios.ink_drama.domain import ShotInput
from scenarios.heritage_study.domain import snapshot


def image_history(setup):
    store, client = setup
    p = project(store)
    shot = p['shots'][0]
    shot.update(image='current.png', image_versions=['old.png','current.png'], rendered='ready.mp4')
    p.update(project_type='heritage', final='final.mp4', final_stale=False)
    for name in ('old.png','current.png','ready.mp4','final.mp4','unrelated.png'):
        store.asset(p['id'],name).write_bytes(name.encode())
    data = {key:copy.deepcopy(shot[key]) for key in ShotInput.model_fields}
    api.remember_image(shot,'old.png',data,'old prompt')
    store.save(p)
    base = f'/api/ink/projects/{p["id"]}'
    history = f'{base}/shots/{shot["id"]}/history'
    deletion = f'{base}/history/image/{shot["id"]}/old.png'
    return store,client,p,shot,history,deletion


def test_delete_restore_image_keeps_files_story_snapshots_and_current_outputs(setup):
    store,client,p,shot,history,deletion = image_history(setup)
    before = copy.deepcopy(shot)
    stamp = snapshot(p)
    assert client.delete(deletion).status_code == 200
    assert client.delete(deletion).status_code == 200  # Retrying a successful delete is safe.
    assert 'old.png' not in {x['image'] for x in client.get(history).json()['images']}
    assert store.asset(p['id'],'old.png').read_bytes() == b'old.png'
    saved = store.load(p['id'])
    assert saved['shots'][0] == before and snapshot(saved) == stamp
    assert saved['final'] == 'final.mp4' and not saved['final_stale']
    removed = next(x for x in client.get(history,params={'include_deleted':True}).json()['images'] if x['image']=='old.png')
    assert removed['deleted_at'] and not removed['can_delete'] and removed['has_snapshot']
    # Writing another history snapshot must not silently resurrect a removed entry.
    api.remember_image(saved['shots'][0],'old.png');store.save(saved)
    assert all(x['image']!='old.png' for x in client.get(history).json()['images'])
    adoption=f'/api/ink/projects/{p["id"]}/shots/{shot["id"]}/restore-image'
    body={'image':'old.png','revision':shot['revision'],'current_image':'current.png'}
    assert client.post(adoption,json=body).status_code == 404
    assert client.post(deletion+'/restore').status_code == 200
    assert store.load(p['id'])['shots'][0]['image'] == 'current.png'
    assert 'old.png' in {x['image'] for x in client.get(history).json()['images']}
    assert client.post(adoption,json=body).status_code == 200
    assert store.load(p['id'])['shots'][0]['image'] == 'old.png'


def test_current_candidate_and_wrong_shot_image_deletions_are_rejected(setup):
    store,client,p,shot,history,deletion=image_history(setup)
    assert client.delete(deletion.replace('old.png','current.png')).status_code == 409
    shot['image_proposal']={'image':'candidate.png','shot':{},'prompt':'candidate'}
    store.asset(p['id'],'candidate.png').write_bytes(b'candidate');store.save(p)
    assert client.delete(deletion.replace('old.png','candidate.png')).status_code == 409
    assert client.delete(deletion.replace('old.png','unrelated.png')).status_code == 404
    assert client.delete(deletion.replace(shot['id'],p['shots'][1]['id'])).status_code == 404
    assert client.delete(deletion.replace('old.png','..%2Fink.sqlite3')).status_code == 404
    assert not store.load(p['id']).get('history_trash')


@pytest.mark.parametrize('block',['owner','ended','busy'])
def test_history_delete_and_restore_enforce_write_access_and_idle_state(setup,block, monkeypatch):
    store,client,p,shot,history,deletion=image_history(setup)
    assert client.delete(deletion).status_code == 200
    if block=='owner':
        monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
        assert client.post('/api/ink/login',json={'token':'bob-test'}).status_code == 200
    elif block=='ended':
        assert client.post('/api/ink/end-trial').status_code == 200
    else:
        store.enqueue(p['id'],'alice','image')
    expected=409 if block=='busy' else 403
    assert client.post(deletion+'/restore').status_code == expected
    assert client.delete(deletion.replace('old.png','current.png')).status_code == expected


def test_video_history_delete_is_scoped_and_preserves_current_original_and_sound_version(setup):
    store,client=setup;p=project(store);shot=p['shots'][0]
    shot.update(clip='source.mp4',rendered='dub.mp4',clip_versions=['old.mp4','source.mp4'],rendered_versions=['dub.mp4'])
    for name in ('old.mp4','source.mp4','dub.mp4','unrelated.mp4'):store.asset(p['id'],name).write_bytes(name.encode())
    store.save(p);base=f'/api/ink/projects/{p["id"]}';history=f'{base}/shots/{shot["id"]}/video-history'
    deletion=f'{base}/history/video/{shot["id"]}/old.mp4'
    assert client.delete(deletion.replace('old.mp4','source.mp4')).status_code == 409
    assert client.delete(deletion.replace('old.mp4','dub.mp4')).status_code == 409
    assert client.delete(deletion.replace('old.mp4','unrelated.mp4')).status_code == 404
    before=copy.deepcopy(shot)
    assert client.delete(deletion).status_code == 200
    assert {v['video'] for v in client.get(history).json()['videos']} == {'source.mp4','dub.mp4'}
    assert client.post(f'{base}/shots/{shot["id"]}/adopt-video',json={
        'video':'old.mp4','revision':shot['revision'],'current_clip':'source.mp4'}).status_code == 422
    assert client.post(deletion+'/restore').status_code == 200
    assert store.load(p['id'])['shots'][0] == before
    assert store.asset(p['id'],'old.mp4').read_bytes() == b'old.mp4'


def test_video_edit_draft_source_is_protected_even_when_not_current(setup):
    store,client=setup;p=project(store);shot=p['shots'][0]
    shot.update(clip='current.mp4',clip_versions=['old.mp4'],video_edit_draft={'video':'old.mp4','instruction':'慢一点'})
    for name in ('current.mp4','old.mp4'):store.asset(p['id'],name).write_bytes(b'video')
    store.save(p)
    response=client.delete(f'/api/ink/projects/{p["id"]}/history/video/{shot["id"]}/old.mp4')
    assert response.status_code == 409 and '调整' in response.json()['detail']


def test_setting_history_delete_restore_protects_confirmed_draft_and_other_asset(setup):
    store,client=setup;p=project(store)
    data=dict(characters=[],scenes=[dict(id='scene1',name='山寺',desc='殿前',image='confirmed.png')],props=[],style='工笔淡彩')
    p['creative_settings']=copy.deepcopy(data)
    p['creative_draft']=copy.deepcopy(data);p['creative_draft']['scenes'][0]['image']='draft.png'
    p['setting_image_history']={'scenes:scene1':[dict(image='old.png',created=1,source='generated')],
                                'scenes:other':[dict(image='other.png',created=1,source='upload')]}
    for name in ('confirmed.png','draft.png','old.png','other.png'):store.asset(p['id'],name).write_bytes(name.encode())
    store.save(p);base=f'/api/ink/projects/{p["id"]}';history=base+'/setting-history/scenes/scene1'
    deletion=base+'/history/setting/scenes:scene1/old.png'
    for name in ('confirmed.png','draft.png'):
        assert client.delete(deletion.replace('old.png',name)).status_code == 409
    assert client.delete(deletion.replace('old.png','other.png')).status_code == 404
    assert client.delete(deletion).status_code == 200
    assert {v['image'] for v in client.get(history).json()['items']} == {'confirmed.png','draft.png'}
    assert client.post(base+'/select-setting-image',json={'settings':data,'group':'scenes','asset_id':'scene1','image':'old.png'}).status_code == 422
    assert client.post(deletion+'/restore').status_code == 200
    assert store.load(p['id'])['creative_draft']['scenes'][0]['image'] == 'draft.png'
    assert client.post(base+'/select-setting-image',json={'settings':data,'group':'scenes','asset_id':'scene1','image':'old.png'}).status_code == 200
    assert store.load(p['id'])['creative_draft']['scenes'][0]['image'] == 'old.png'
