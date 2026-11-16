from scenarios.ink_drama.styles import image_style, negative_style, video_prompt, caption_guidance
from scenarios.ink_drama.domain import frame_prompt


def project(style):
    return {'creative_settings': {'style':style,'characters':[],'scenes':[],'props':[]},
            'characters':[], 'baseline': {'characters':[], 'ink_style': {'techniques':['泼墨'], 'paper_texture':'可见'}}}


def test_selected_style_overrides_old_caption_and_material():
    p=project('水墨风格 · 工笔淡彩，宣纸质感')
    prompt=frame_prompt(p,{'character_ids':[],'content':'山寺','scene':'山寺','camera':'全景','motion':'细雨落下'})
    positive=prompt.split('避免：')[0]
    assert '绢本视觉质感' in positive
    assert '宣纸质感' not in positive
    assert '泼墨' not in positive
    assert '缓慢平移' not in prompt
    assert '宋' not in image_style(p) and '唐' not in image_style(p)


def test_video_uses_selected_profile_and_preserves_explicit_action():
    p=project('泼墨写意')
    prompt=video_prompt(p,'少女向书生递伞')
    assert '少女向书生递伞' in prompt
    assert '仅云雾、烟气和墨迹' not in prompt
    assert '不凭画风添加飘烟、蒸汽或雾带' in prompt
    assert '建筑、身体与关键道具保持结构稳定' in prompt
    assert '照片般精细五官' in negative_style(p)
    assert '全局低对比度' not in image_style(p)


def test_caption_observes_instead_of_inventing():
    prompt=caption_guidance(project('工笔淡彩'))
    assert 'uncertain' in prompt
    assert '不得为了符合预设而编造特征' in prompt
    assert '真实绢本' in prompt


def test_legacy_custom_and_explicit_reference_choice():
    assert image_style(project('清淡柔和')) == image_style(project('工笔淡彩'))
    p=project('工笔淡彩');p['_style_override']='bold'
    assert '大写意泼墨' in image_style(p)
    assert image_style(project('自定义青绿山水')) == '自定义青绿山水'


def test_actual_image_request_has_no_text_instruction(monkeypatch, tmp_path):
    from scenarios.ink_drama.providers import Providers
    from models.image_client import ImageClient
    captured = {}
    def generate(self, **kwargs):
        captured.update(kwargs)
        return [str(tmp_path / 'result.png')]
    monkeypatch.setattr(ImageClient, 'generate_image', generate)
    Providers().image('兼工带写，青年书生', [], tmp_path, 'test')
    assert '留白保持空白' in captured['prompt']
    assert captured['prompt'].endswith('无题字、无印章、无标签。')
    assert captured['image_paths'] is None


def test_style_reference_is_selected_without_replacing_identity():
    from pathlib import Path
    from scenarios.ink_drama.styles import with_style_reference
    for name, key in [('工笔淡彩', 'soft'), ('兼工带写', 'simple'), ('泼墨写意', 'bold')]:
        prompt, refs = with_style_reference(project(name), '只画一位书生', ['identity.png'])
        assert refs[0] == 'identity.png'
        assert Path(refs[1]).name == key + '.png'
        assert Path(refs[1]).is_file()
        assert '第2张' in prompt and '不要复制样张' in prompt
    assert with_style_reference(project('自定义'), 'custom', []) == ('custom', [])


def test_asset_groups_use_distinct_samples_and_keep_identity_references():
    from pathlib import Path
    from scenarios.ink_drama.styles import with_style_reference
    for key in ('soft', 'simple', 'bold'):
        context = project('')
        context['_style_override'] = key
        samples = []
        for group, filename in (
            ('characters', key + '.png'),
            ('scenes', key + '-empty.png'),
            ('props', key + '-props.png'),
        ):
            identity_refs = ['identity.png', 'second-identity.png']
            prompt, refs = with_style_reference(context, 'asset description', identity_refs, asset_group=group)
            assert refs[:-1] == identity_refs
            assert identity_refs == ['identity.png', 'second-identity.png']
            sample = Path(refs[-1])
            assert sample.name == filename
            assert sample.is_file()
            assert 'asset description' in prompt
            samples.append(sample.read_bytes())
        assert len(set(samples)) == 3


def test_video_environment_motion_is_explicit_not_implied_by_style():
    for style in ('工笔淡彩', '兼工带写', '泼墨写意'):
        prompt = video_prompt(project(style), '少女递伞，固定镜头')
        assert '背景默认保持稳定' in prompt
        assert '是静态绘画质感' in prompt
        explicit = video_prompt(project(style), '香炉升起一缕烟，树叶轻摇')
        assert '剧情动作：香炉升起一缕烟，树叶轻摇' in explicit
        assert '只有剧情动作明确要求时才表现' in explicit


def test_video_style_lock_preserves_shot_sequence():
    motion = '分镜列表：\n分镜1：[2秒] 近景，书生问话\n分镜2：[3秒] 特写，少女指向伞柄刻字'
    prompt = video_prompt(project('泼墨写意'), motion)
    assert motion in prompt
    assert '用大片墨块组织形体' in prompt
    assert '摄影虚化' in prompt
    assert '用大片墨块组织形体' not in video_prompt(project('工笔淡彩'), motion)


def test_frames_restore_original_style_sample_without_excluding_cast():
    from pathlib import Path
    from scenarios.ink_drama.styles import with_style_reference
    for name, key in [('工笔淡彩', 'soft'), ('兼工带写', 'simple'), ('泼墨写意', 'bold')]:
        original = ['character.png', 'scene.png']
        prompt, refs = with_style_reference(project(name), '书生站在门前', original, asset_group='frames')
        assert refs[:-1] == original
        assert Path(refs[-1]).name == key + '.png'
        assert Path(refs[-1]).is_file()
        assert '主体数量、场景与动作严格依照本次文字设定' in prompt
        assert '本次是无人素材' not in prompt
        assert '第3张' in prompt


def test_frame_prompt_excludes_historical_character_style_metadata():
    p = project('泼墨写意')
    p['creative_settings']['characters'] = [{'id': 'c1', 'name': '书生', 'desc': '灰蓝长衫',
        'image': 'old.png', 'views': {'side': {'style': '旧工笔风格标记', 'image': 'side.png'}}}]
    prompt = frame_prompt(p, {'character_ids': ['c1'], 'content': '书生站立', 'scene': '门前', 'camera': '中景', 'motion': ''})
    assert '灰蓝长衫' in prompt
    assert '旧工笔风格标记' not in prompt
    assert 'side.png' not in prompt
    assert '外貌、服饰和画风' not in prompt
    assert '不继承其画风' in prompt


def test_material_style_checks_known_conflicts_but_not_unknown_uploads():
    import pytest
    from scenarios.ink_drama.styles import check_material_styles
    from scenarios.ink_drama.domain import UserError
    p = project('泼墨写意')
    p['setting_generation_records'] = {'a.png': {'style': '工笔淡彩'}}
    with pytest.raises(UserError, match='书生'):
        check_material_styles(p, [{'name': '书生', 'image': 'a.png'}])
    check_material_styles(p, [{'name': '上传图', 'image': 'unknown.png'}])
    p['setting_generation_records']['a.png']['style'] = '泼墨大写意'
    check_material_styles(p, [{'name': '书生', 'image': 'a.png'}])


def test_caption_check_is_advisory_and_detects_missing_bold_features():
    from scenarios.ink_drama.styles import style_observation
    observed = {'ink_style': {'techniques': ['工笔细线条']}, 'uncertainties': ['人物太小']}
    result = style_observation(project('泼墨写意'), observed)
    assert '可能偏离' in result['message']
    assert result['uncertainties'] == ['人物太小']
    observed['ink_style']['techniques'] = ['泼墨']
    assert '不代表画风已达标' in style_observation(project('泼墨写意'), observed)['message']


def test_bold_scene_requires_main_building_not_only_background():
    from scenarios.ink_drama.styles import with_style_reference
    prompt, _ = with_style_reference(project('泼墨写意'), '寺门', [], asset_group='scenes')
    assert '禁止前景建筑工笔描线' in prompt
    assert '不额外新增第二座建筑' in prompt
    other, _ = with_style_reference(project('工笔淡彩'), '寺门', [], asset_group='scenes')
    assert '禁止前景建筑工笔描线' not in other


def test_region_review_does_not_hide_building_failure_behind_background():
    from scenarios.ink_drama.style_review import StyleReview, review_result
    review = StyleReview.model_validate({
        'main_building': {'status': 'deviates', 'evidence': '逐片瓦片硬勾线'},
        'characters': {'status': 'uncertain', 'evidence': '人物较小'},
        'background': {'status': 'consistent', 'evidence': '远山破墨'},
        'extra_building': {'status': 'absent', 'evidence': '未见额外建筑'},
        'framing': {'status': 'consistent', 'evidence': '腰部以上'},
    })
    result = review_result(review)
    assert result['message'] == '需要核对：主建筑'
    assert any('人物 · 无法确定' in x for x in result['uncertainties'])


def test_framing_failure_is_reported_even_when_all_style_regions_match():
    from scenarios.ink_drama.style_review import StyleReview, review_result
    data = {k: {'status': 'consistent', 'evidence': '符合目标笔墨'} for k in ('main_building', 'characters', 'background', 'extra_building')}
    data['framing'] = {'status': 'deviates', 'evidence': '要求腰部以上，实际露出脚部，为全景'}
    result = review_result(StyleReview.model_validate(data))
    assert result['message'] == '需要核对：景别'
    assert any('实际露出脚部' in line for line in result['uncertainties'])


def test_redesign_inherits_only_matching_current_style(tmp_path):
    from scenarios.ink_drama.styles import current_style_matches, with_style_reference, image_style
    current = {'image': 'accepted.png', 'used_prompt': image_style(project('泼墨写意'))}
    assert current_style_matches(project('泼墨写意'), current)
    assert not current_style_matches(project('工笔淡彩'), current)
    assert not current_style_matches(project('泼墨写意'), {'image': 'upload.png', 'used_prompt': None})
    sample = tmp_path / 'accepted.png'
    sample.write_bytes(b'test')
    prompt, refs = with_style_reference(project('泼墨写意'), '新构图', ['character.png', 'scene.png'],
        asset_group='frames', current_style_reference=sample)
    assert refs == ['character.png', 'scene.png', str(sample)]
    assert '不要复制样张中的人物身份' in prompt
    assert '-empty.png' not in str(refs)


def test_independent_video_is_one_continuous_shot_without_style_camera_preferences():
    for style in ['工笔淡彩', '兼工带写', '泼墨写意']:
        prompt = video_prompt(project(style), '食指轻点伞柄刻字后停留')
        assert '只生成一个连续镜头' in prompt
        assert '运镜未明确指定时机位固定' in prompt
        assert '动作完成后保持末态' in prompt
        assert '优先远景' not in prompt
        assert '意境转场' not in prompt
        assert '切近景、特写或反打时' not in prompt
        assert prompt.count('画法参考（仅保持笔墨') == 1
        assert '用户指定时代背景' not in prompt
