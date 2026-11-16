import json
import pytest
from core.agents.storyboard_agent import StoryboardAgent
from scenarios.ink_drama.storyboard import split_storyboard, _named_assets
from scenarios.ink_drama.domain import UserError


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("separate", [False, True])
@pytest.mark.parametrize("geography", [False, True])
def test_pipeline_reuses_planning_and_returns_ink_board(repair, separate, geography):
    source = {"characters": [{"id": "c1", "name": "书生", "desc": "青衫"}],
              "settings": [{"name": "寺门"}], "script": "<action>书生静立。</action>\n<action>书生伸手。</action>"}
    agent = StoryboardAgent()
    _, units = agent._annotate_episode_script(source['script'], source['characters'], source['settings'])
    plan = agent._validate_segment_plan(1, [{"unit_ids": ["U001", "U002"]}], units)[0]
    design = agent._fallback_design_segment(1, plan)
    shot = {"content": "书生在门内", "scene": "寺门", "camera": "中景", "motion": "缓步走出", "character_ids": ["c1"], "dialogues": []}
    raw_plans = [{'unit_ids': ['U001']}, {'unit_ids': ['U002']}] if separate else [{'unit_ids': ['U001', 'U002']}]
    plans = agent._validate_segment_plan(1, raw_plans, units)
    designs = [agent._fallback_design_segment(1, plan) for plan in plans]
    replies = iter([source, raw_plans, *designs, {'patches': []},
                    *[shot.copy() for d in designs for _ in d["shots"]], {"patches": [{"index": 0, "content": "书生尚未伸手", "camera": "中景平视"}] if repair else []}])
    prompts = []
    def query(prompt):
        prompts.append(prompt)
        return json.dumps(next(replies), ensure_ascii=False)
    from scenarios.ink_drama.spatial import PLANNING_MARKER
    context = '人物按门内门外关系衔接，画面左右随镜头机位变化'
    result = split_storyboard('书生静立。' + (PLANNING_MARKER + context if geography else ''), query)
    if geography:
        assert all(context in prompt for prompt in prompts)
    assert len(prompts) == 4 + len(plans) + sum(len(d["shots"]) for d in designs)
    assert result['shots'][0]['id'] == 's1'
    assert '首帧' in prompts[-1]
    assert result['shots'][0]['duration'] == designs[0]['shots'][0]['duration']
    assert not result['shots'][0]['motion'].startswith('分镜列表：')
    assert len(result['storyboard_plan']) == len(plans)
    assert len(result['shots']) == sum(len(d['shots']) for d in designs)
    expected = [shot for segment in result['storyboard_plan'] for shot in segment['shots']]
    for shot, planned in zip(result['shots'], expected):
        assert shot['motion'] == planned['content']
        assert shot['duration'] == planned['duration']
        assert shot['generation_unit'] == 'shot'
    assert result['storyboard_episodes'][0]['segments'] == result['storyboard_plan']
    if repair:
        assert result['shots'][0]['content'] == '书生尚未伸手'


def test_invalid_plan_uses_base_retry_then_fallback():
    source = {"characters": [], "settings": [], "script": "<action>下雨。</action>"}
    agent = StoryboardAgent()
    _, units = agent._annotate_episode_script(source['script'], [], [])
    plan = agent._fallback_segment_plan(1, units)[0]
    design = agent._fallback_design_segment(1, plan)
    shot = {"content": "雨中的寺门", "scene": "寺门", "camera": "中景", "motion": "",
            "character_ids": [], "dialogues": []}
    replies = iter([source, [], [], [], design, {'patches': []}, shot, {'patches': []}])
    calls = []
    def query(prompt):
        calls.append(prompt)
        return json.dumps(next(replies))
    result = split_storyboard('下雨。', query)
    assert len(calls) == 8
    assert result['storyboard_engine'] == 'base-storyboard-atomic-v2'
    assert result['storyboard_episodes'][0]['segments'] == result['storyboard_plan']
    assert result['shots'][0]['duration'] == result['storyboard_plan'][0]['total_duration']


def test_provider_error_is_not_retried():
    calls = []
    def query(prompt):
        calls.append(prompt)
        raise RuntimeError('offline')
    with pytest.raises(UserError, match='整理剧本'):
        split_storyboard('剧本', query)
    assert len(calls) == 1


def test_frame_keeps_start_state_instead_of_motion_end():
    from scenarios.ink_drama.domain import frame_prompt
    p = {'characters': [], 'baseline': None}
    shot = {'content': '少女在门内，伞仍在少女手中', 'scene': '寺门', 'camera': '中景',
            'motion': '少女走到书生身旁，递出伞', 'character_ids': []}
    prompt = frame_prompt(p, shot)
    assert '静态首帧（最高优先级）：' + shot['content'] in prompt
    assert '不提前完成' in prompt
    assert '动作与姿势以本项为准' not in prompt
    assert '本镜最高优先级动作与姿势' not in prompt


def test_named_asset_strings_are_normalized():
    assert _named_assets(['寺门'], '场景') == [{'name': '寺门'}]
    assert _named_assets(['书生'], '角色') == [{'name': '书生'}]
    with pytest.raises(UserError, match='缺少名称'):
        _named_assets([None], '场景')


@pytest.mark.parametrize('value', ['寺门', {'name': '寺门'}, {'scene1': {'name': '寺门'}}, {'scenes': [{'name': '寺门'}]}])
def test_scene_shapes_normalize_without_model_retry(value):
    assert _named_assets(value, '场景') == [{'name': '寺门'}]


def test_empty_scene_and_ambiguous_object():
    assert _named_assets(None, '场景') == []
    with pytest.raises(UserError, match='明确名称'):
        _named_assets({'description': '雨夜'}, '场景')
