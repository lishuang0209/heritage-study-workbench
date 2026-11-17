import copy
from pathlib import Path

import pytest
from PIL import Image

from test_ink_demo import api, project, setup
from scenarios.heritage_study.domain import empty_station
from scenarios.heritage_study.visual_reference import reference_plan


def fixture(setup, monkeypatch, *, style='工笔淡彩', mark=True):
    store, client = setup
    p = project(store)
    station = empty_station()
    station.update(building='宁波保国寺大殿', component='斗拱', panorama={
        'image': 'real-photo.jpg', 'mode': 'contain', 'focus_x': .5, 'focus_y': .5,
        'source': '测试实拍', 'author': '测试作者', 'license': '测试授权',
        'mark': {'kind': 'rectangle', 'x': .3, 'y': .3, 'x2': .7, 'y2': .6} if mark else None})
    p.update(project_type='heritage', heritage_station=station, heritage_version=7)
    image = Image.new('RGB', (1000, 1200), 'blue')
    image.paste('red', (250, 300, 750, 800))
    image.save(store.folder(p['id']) / 'real-photo.jpg', quality=98)
    Image.new('RGB', (100, 200), 'white').save(store.folder(p['id']) / 'old-umbrella.png')
    data = dict(characters=[], scenes=[dict(id='scene1', name='保国寺大殿', desc='殿内梁架', image=None)],
                props=[dict(id='prop1', name='斗拱', desc='层叠交错的木构件', image='old-umbrella.png')], style=style)
    p['creative_draft'] = copy.deepcopy(data)
    store.save(p)
    class Immediate:
        def submit(self, fn, *args): fn(*args)
    monkeypatch.setattr(api, 'pool', Immediate())
    return store, client, p, data


def generate(client, p, data, group='props'):
    response = client.post(f'/api/ink/projects/{p["id"]}/generate-setting-image',
                           json={'settings': data, 'group': group, 'asset_id': 'prop1' if group == 'props' else 'scene1'})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('style', ['工笔淡彩', '兼工带写', '泼墨写意'])
def test_bracket_generation_passes_real_marked_crop_without_umbrella_sample(setup, monkeypatch, style):
    store, client, p, data = fixture(setup, monkeypatch, style=style)
    original = store.asset(p['id'], 'real-photo.jpg').read_bytes()
    before = copy.deepcopy(p['shots'])
    seen = []
    def image(prompt, refs, folder, pid, ratio='9:16'):
        assert ratio == '16:9' and '横屏16:9' in prompt
        assert '第1张是本讲解站上传的真实照片' in prompt and style in prompt
        assert '构件' in prompt and '单个道具设定图' not in prompt
        assert len(refs) == 1 and Path(refs[0]).name.endswith('-heritage-reference.jpg')
        assert 'soft-props.png' not in refs and 'old-umbrella.png' not in refs
        with Image.open(refs[0]) as crop:
            assert crop.size == (520, 468)
            red, green, blue = crop.getpixel((260, 234))
            assert red > 220 and blue < 30
        seen.extend(refs)
        result = folder / 'mock-generated.png'
        Image.new('RGB', (90, 160), 'white').save(result)
        return result
    monkeypatch.setattr(api.providers, 'image', image)
    result = generate(client, p, data)
    assert result['jobs'][0]['state'] == 'completed', result['jobs'][0]
    saved = store.load(p['id'])
    generated = saved['creative_draft']['props'][0]['image']
    record = saved['setting_generation_records'][generated]
    assert record['reference_mode'] == 'heritage-photo'
    assert record['references'] == [Path(seen[0]).name]
    assert Path(seen[0]).is_file()  # The exact request input remains inspectable.
    source = record['heritage_reference']
    assert source['source_image'] == 'real-photo.jpg' and source['station_version'] == 7
    assert source['mark'] == p['heritage_station']['panorama']['mark']
    assert source['credits']['author'] == '测试作者'
    assert store.asset(p['id'], 'real-photo.jpg').read_bytes() == original
    assert store.asset(p['id'], 'old-umbrella.png').is_file()
    assert any(v['image'] == 'old-umbrella.png' for v in saved['setting_image_history']['props:prop1'])
    assert saved['shots'] == before
    plan = result['heritage_setting_references'][-1]
    assert plan['mode'] == 'crop' and plan['asset_name'] == '斗拱' and plan['preview_url']


@pytest.mark.parametrize('failure,expected', [('mark', '标注目标构件'), ('photo', '上传现场定位图'), ('file', '文件不存在')])
def test_missing_subject_reference_fails_before_paid_call_and_keeps_old_image(setup, monkeypatch, failure, expected):
    store, client, p, data = fixture(setup, monkeypatch, mark=failure != 'mark')
    if failure == 'photo':
        p['heritage_station']['panorama'] = None
        store.save(p)
    if failure == 'file':
        store.asset(p['id'], 'real-photo.jpg').unlink()
    def unexpected(*args, **kwargs):
        pytest.fail('Incomplete subject reference must not reach a paid provider')
    monkeypatch.setattr(api.providers, 'image', unexpected)
    result = generate(client, p, data)
    assert result['jobs'][0]['state'] == 'failed'
    assert expected in result['jobs'][0]['error']
    assert result['creative_draft']['props'][0]['image'] == 'old-umbrella.png'
    assert store.usage('alice').get('image', 0) == 0


def test_arrow_reference_keeps_full_photo_and_targets_tip_instead_of_narrow_crop(setup, monkeypatch):
    store, client, p, data = fixture(setup, monkeypatch)
    p['heritage_station']['panorama']['mark'] = dict(kind='arrow', x=.4, y=.5, x2=.4, y2=.3)
    store.save(p)
    def image(prompt, refs, folder, pid, ratio='9:16'):
        assert ratio == '16:9' and '横屏16:9' in prompt
        assert '箭头尖端' in prompt and '不画出红白标注线' in prompt
        with Image.open(refs[0]) as reference:
            assert reference.size == (1280, 720)
        return folder / 'old-umbrella.png'
    monkeypatch.setattr(api.providers, 'image', image)
    result = generate(client, p, data)
    assert result['jobs'][0]['state'] == 'completed'


def test_building_reference_uses_original_visible_architecture_without_style_sample(setup, monkeypatch):
    store, client, p, data = fixture(setup, monkeypatch)
    def image(prompt, refs, folder, pid, ratio='9:16'):
        assert ratio == '16:9' and '横屏16:9' in prompt
        assert refs == [str(folder / 'real-photo.jpg')]
        assert '不凭局部照片补造完整外观' in prompt
        return folder / 'old-umbrella.png'
    monkeypatch.setattr(api.providers, 'image', image)
    result = generate(client, p, data, 'scenes')
    assert result['jobs'][0]['state'] == 'completed'


def test_unrelated_props_and_characters_are_not_bound_to_building_photos(setup, monkeypatch):
    store, client, p, data = fixture(setup, monkeypatch)
    assert reference_plan(p, 'props', dict(id='umbrella', name='油纸伞')) is None
    assert reference_plan(p, 'characters', dict(id='c1', name='斗拱')) is None
    assert reference_plan({**p, 'project_type': 'ink'}, 'props', data['props'][0]) is None
    data['props'][0]['name'] = '油纸伞'
    def image(prompt, refs, folder, pid, ratio='9:16'):
        assert ratio == '16:9' and '横屏16:9' in prompt
        assert len(refs) == 1 and Path(refs[0]).name == 'soft-props.png'
        return folder / 'old-umbrella.png'
    monkeypatch.setattr(api.providers, 'image', image)
    result = generate(client, p, data)
    assert result['jobs'][0]['state'] == 'completed'
    assert all(plan['group'] != 'props' for plan in result['heritage_setting_references'])
