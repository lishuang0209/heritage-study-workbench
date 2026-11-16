from scenarios.ink_drama.domain import framing_constraint


def test_close_shot_does_not_inherit_full_scene():
    text = framing_constraint({'camera': '近景，平视略仰', 'content': '书生上半身，少女手臂虚焦前景'})
    assert '胸部或腰部以上' in text
    assert '不升级为双人全景' in text


def test_camera_scale_wins_over_background_description():
    text = framing_constraint({'camera': '特写', 'content': '远景山寺，伞柄上的刻字'})
    assert '局部占据画面主体' in text
    assert '人物在画面中占比较小' not in text


def test_medium_close_is_not_parsed_as_close():
    assert '以指定主体腰部以上' in framing_constraint({'camera': '中近景'})


def test_image_prompt_is_independent_of_video_motion():
    from scenarios.ink_drama.domain import frame_prompt
    from scenarios.ink_drama.styles import video_prompt
    project = {'characters': []}
    shot = {'content': '空寺门，木门半开', 'scene': '山寺', 'camera': '中景', 'character_ids': [], 'motion': '木门随后缓缓关闭'}
    original = frame_prompt(project, shot)
    assert shot['motion'] not in original
    assert shot['motion'] in video_prompt(project, shot['motion'])
    shot['motion'] = '木门随后完全敞开'
    assert frame_prompt(project, shot) == original


def test_medium_defaults_to_waist_crop_and_excludes_feet():
    prompt = framing_constraint({'camera': '中景，平视', 'content': '书生持书卷'})
    assert '腰部以上' in prompt
    assert '脚部在画框外' in prompt
    assert '手部和所持道具安排在取景范围内' in prompt
