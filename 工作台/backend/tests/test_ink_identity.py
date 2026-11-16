import copy

import pytest

from scenarios.ink_drama.domain import Store, UserError
from scenarios.ink_drama.identity import detail_request


@pytest.fixture
def identity_project(tmp_path):
    store = Store(tmp_path)
    p = store.create('local', '身份回归', '测试用故事')
    p['creative_settings'] = {'style':'泼墨写意', 'characters':[
        {'id':'c1','name':'书生','desc':'黑布巾束发','image':'scholar.png'},
        {'id':'c2','name':'少女','desc':'左右各一个小发髻，共两个，暗红发绳，后发收束不披肩','image':'girl.png'}],
        'scenes':[{'id':'scene1','name':'寺门','image':'unused-scene.png'}],
        'props':[{'id':'prop1','name':'伞','image':'unused-prop.png'}]}
    for name in ('current.png','scholar.png','girl.png'):
        store.asset(p['id'],name).write_bytes(b'fixture')
    shot = {'image':'current.png','character_ids':['c2'],'scene_id':'scene1','prop_ids':['prop1']}
    return store, p, shot


def test_local_edit_anchors_only_present_character_and_keeps_current_frame_first(identity_project):
    store, p, shot = identity_project
    before = copy.deepcopy(p)
    prompt, refs = detail_request(p, shot, '少女面对镜头，张嘴说话，不拿伞', store)
    assert refs == [str(store.asset(p['id'],'current.png')),str(store.asset(p['id'],'girl.png'))]
    assert '少女：左右各一个小发髻，共两个' in prompt and '参考图2' in prompt
    assert '书生：黑布巾束发' not in prompt
    assert '图1决定本镜动作底稿、站位、场景、景别和构图' in prompt
    assert '后续角色图只提供' in prompt and '不把当前分镜已有的身份偏差当成新设定' in prompt
    assert '遮挡可以使某个发髻不可见' in prompt
    assert p == before


def test_local_edit_keeps_text_identity_without_role_image(identity_project):
    store, p, shot = identity_project
    p['creative_settings']['characters'][1]['image'] = None
    prompt, refs = detail_request(p, shot, '只抬右手', store)
    assert len(refs) == 1 and '左右各一个小发髻' in prompt
    assert '参考图2' not in prompt


def test_missing_role_image_stops_before_generation(identity_project):
    store, p, shot = identity_project
    store.asset(p['id'],'girl.png').unlink()
    with pytest.raises(UserError, match='角色参考图不存在'):
        detail_request(p, shot, '张嘴', store)


def test_landscape_local_edit_does_not_add_cast(identity_project):
    store, p, shot = identity_project
    shot['character_ids'] = []
    prompt, refs = detail_request(p, shot, '仅减少雨丝', store)
    assert len(refs) == 1 and '左右各一个小发髻' not in prompt
    assert '黑布巾束发' not in prompt


def test_explicit_identity_change_and_legacy_caption_remain_supported(identity_project):
    store, p, shot = identity_project
    p.pop('creative_settings')
    p['characters'] = [{'id':'c2','name':'少女','desc':'旧文字'}]
    p['baseline'] = {'characters':[{'character_id':'c2','desc':'左右各一个小发髻'}]}
    prompt, refs = detail_request(p, shot, '只把衣服改成浅青色', store)
    assert '左右各一个小发髻' in prompt and '旧文字' not in prompt
    assert '只把衣服改成浅青色' in prompt
    assert '用户明确要求修改发型或服饰时，仅对应特征按本次要求改变' in prompt
