import pytest
from scenarios.ink_drama.spatial import SceneLayout, layouts_for, spatial_prompt, planning_context
from scenarios.ink_drama.domain import frame_prompt


def pair():
    return {'characters': [{'id':'c1','name':'年轻书生','desc':'灰衣'}, {'id':'c2','name':'守寺少女','desc':'长裙'}],
            'shots': [{'scene_id':'scene1'}]}


def test_geography_does_not_assign_screen_sides_or_inherit_previous_frame():
    p = pair()
    first = layouts_for(p)
    p['shots'].append({'scene_id':'scene1', 'character_ids':['c2','c1'], 'image':'previous.png'})
    assert layouts_for(p) == first
    assert not {'left_id','right_id'} & set(first[0])
    first[0]['placements'][0]['anchor'] = '门外檐下'
    first[0]['placements'][1]['anchor'] = '从门内跨过门槛到檐下，结尾回到门内'
    p['scene_layouts'] = first
    prompt = spatial_prompt(p, {'scene_id':'scene1','character_ids':['c2']})
    assert '年轻书生：门外檐下' not in prompt and '结尾回到门内' not in prompt
    assert '不固定人物在画面中的左、右' in prompt
    assert '年轻书生在画面左侧' not in prompt and '守寺少女在画面右侧' not in prompt
    assert 'previous.png' not in prompt


def test_legacy_screen_ids_only_migrate_physical_anchor_text():
    old = {'scene_id':'scene1','left_id':'c2','right_id':'c1','left_anchor':'门内','right_anchor':'门外',
           'reference_shot_id':'s2','reference_image':'saved.png','enabled':True}
    migrated = SceneLayout.model_validate(old).model_dump()
    assert migrated['placements'] == [{'character_id':'c2','anchor':'门内'}, {'character_id':'c1','anchor':'门外'}]
    assert migrated['references'] == [{'shot_id':'s2','image':'saved.png'}]
    assert 'left_id' not in migrated
    p = pair(); p['scene_layouts'] = [old]
    prompt = spatial_prompt(p, {'scene_id':'scene1'})
    assert '年轻书生：门外' not in prompt and '守寺少女：门内' not in prompt
    assert '守寺少女在画面左侧' not in prompt


@pytest.mark.parametrize('camera', ['从门外朝门内拍，书生在左、少女在右','从侧面朝檐外拍，少女在左、书生在右','近景，少女面对镜头'])
def test_each_shot_camera_may_change_sides_or_face_camera(camera):
    p = pair()
    shot = {'scene_id':'scene1','content':'少女立在门内，书生在檐下','camera':camera,'scene':'山寺','character_ids':['c1','c2'],'prop_ids':[]}
    prompt = frame_prompt(p, shot)
    assert camera in prompt
    assert '换机位或反打可以使画面左右变化' in prompt
    assert '面对镜头' in spatial_prompt(p, shot)
    assert '双人同框保持相对左右顺序' not in prompt


def test_movement_and_offscreen_detail_remain_allowed():
    p = pair()
    shot = {'scene_id':'scene1','content':'手部和闭合伞的局部','camera':'特写','scene':'寺门',
            'motion':'少女完成递伞并转身走入屋内','character_ids':['c2'],'prop_ids':[]}
    prompt = frame_prompt(p, shot)
    assert '完成递伞' not in prompt
    assert '画外角色' not in prompt or '保持画外或局部' in prompt
    video = spatial_prompt(p, shot, video=True)
    assert '明确走动、进出门或转身时允许位置与朝向改变' in video
    assert '镜头内不自行切镜、反打或镜像' in video
    assert '按明确的动作路径走动' in video


def test_separate_scene_geography_and_disabled_layout():
    p = pair(); p['shots'].append({'scene_id':'scene2'})
    p['scene_layouts'] = layouts_for(p)
    p['scene_layouts'][0]['relation'] = '门槛连接门内和檐下'
    p['scene_layouts'][1]['relation'] = '茶桌连接两人座位'
    assert '门槛连接门内和檐下' not in spatial_prompt(p, p['shots'][0])
    assert '茶桌连接两人座位' not in spatial_prompt(p, p['shots'][1])
    assert 'scene1' in planning_context(p) and 'scene2' in planning_context(p)
    p['scene_layouts'][0]['enabled'] = False
    assert '不固定人物在画面中的左、右' in spatial_prompt(p, p['shots'][0])


def test_geography_review_is_independent_of_style():
    from scenarios.ink_drama.style_review import StyleReview, review_result
    data = {k: {'status':'consistent','evidence':'符合'} for k in ('main_building','characters','background','extra_building','framing')}
    data['staging'] = {'status':'deviates','evidence':'没有走动却把门内外位置交换'}
    result = review_result(StyleReview.model_validate(data))
    assert result['message'] == '需要核对：场景空间关系' and result['spatial_policy'] == 2


def test_spatial_vl_review_receives_opposite_views_without_screen_side_rule(monkeypatch):
    import json
    from models.vlm_client import VLM
    from scenarios.ink_drama.providers import Providers
    response = {k:{'status':'consistent','evidence':'地标和人物关系一致，机位不同'} for k in ('main_building','characters','background','extra_building','framing','staging')}
    def query(self, **kwargs):
        assert kwargs['image_paths'] == ['candidate.png','view-a.png','view-b.png']
        assert '换机位或正反打导致画面左右变化不算错误' in kwargs['prompt']
        assert '证据不足用uncertain' in kwargs['prompt']
        return json.dumps(response,ensure_ascii=False)
    monkeypatch.setattr(VLM,'query',query)
    p = pair()
    result = Providers().review_style('candidate.png',p,{'scene_id':'scene1','content':'少女门内书生门外','scene':'门口','camera':'中景'},spatial_references=['view-a.png','view-b.png'])
    assert result['regions']['staging']['status'] == 'consistent'


def test_legacy_missing_scene_id_does_not_break_project_read():
    p = pair()
    p['creative_settings'] = {'characters':p['characters'],'scenes':[{'id':None}]}
    assert [x['scene_id'] for x in layouts_for(p)] == ['scene1']


def test_retired_scene_references_are_not_read_or_added_to_new_generation():
    from scenarios.ink_drama.spatial import spatial_reference_paths, with_spatial_reference
    p = pair()
    p['scene_layouts'] = layouts_for(p)
    p['scene_layouts'][0]['references'] = [{'shot_id':'old-shot', 'image':'missing.png'}]
    # No file access: missing archived references cannot block future generation.
    assert spatial_reference_paths(p, p['shots'][0], None) == []
    assert with_spatial_reference(p, p['shots'][0], 'current prompt', ['character.png'], None) == ('current prompt', ['character.png'])
    assert p['scene_layouts'][0]['references'][0]['image'] == 'missing.png'
