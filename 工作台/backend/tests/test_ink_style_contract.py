import pytest
from scenarios.ink_drama.styles import PROFILES, image_style, video_prompt, check_frame_style, check_material_styles
from scenarios.ink_drama.domain import UserError

@pytest.mark.parametrize('key', list(PROFILES))
def test_asset_and_video_share_project_style(key):
    profile = PROFILES[key]
    p = {'creative_settings': {'style': profile['names'][0]}}
    image = image_style(p)
    video = video_prompt(p, '人物抬手')
    assert profile['positive'] in video
    assert '用户指定时代背景' not in video
    assert '角色、场景、道具、分镜画面及视频' in image
    assert profile['positive'] in image

@pytest.mark.parametrize('source', ['soft', 'simple'])
def test_old_frame_cannot_enter_bold_video_or_detail_edit(source):
    p = {'creative_settings': {'style': '泼墨写意'}}
    with pytest.raises(UserError, match='其他画风'):
        check_frame_style(p, {'used_prompt': PROFILES[source]['positive']})
    check_frame_style(p, {'used_prompt': PROFILES['bold']['positive']})
    check_frame_style(p, {'used_prompt': ''})  # Unknown uploads are not falsely certified.

def test_mismatched_material_is_rejected():
    p = {'creative_settings': {'style': '泼墨写意'}, 'setting_generation_records': {'scene.png': {'style': '工笔淡彩'}}}
    with pytest.raises(UserError, match='画风不一致'):
        check_material_styles(p, [{'name': '山寺', 'image': 'scene.png'}])

@pytest.mark.parametrize('key', ['soft', 'simple', 'bold'])
def test_restyle_uses_style_first_and_content_second(key):
    from scenarios.ink_drama.styles import restyle_request
    p = {'creative_settings': {'style': PROFILES[key]['names'][0]}}
    prompt, refs = restyle_request(p, '/current.png')
    assert refs[0].endswith('/' + key + '.png')
    assert refs[1] == '/current.png'
    assert PROFILES[key]['positive'] in prompt
    assert '原图的线条、材质、明暗与细部必须重新画' in prompt


def test_restyle_warns_about_near_copy_without_claiming_style_pass(tmp_path):
    from PIL import Image
    from scenarios.ink_drama.styles import restyle_change_warning
    a, b = tmp_path/'a.png', tmp_path/'b.png'
    Image.new('RGB', (32, 48), 'white').save(a)
    Image.new('RGB', (32, 48), (250, 250, 250)).save(b)
    assert '变化较小' in restyle_change_warning(a, b)
    Image.new('RGB', (32, 48), 'black').save(b)
    assert restyle_change_warning(a, b) is None


@pytest.mark.parametrize('key', list(PROFILES))
def test_video_keeps_framing_and_painterly_detail_at_close_range(key):
    p = {'creative_settings': {'style': PROFILES[key]['names'][0]}}
    prompt = video_prompt(p, '书生接过油纸伞')
    assert '禁止自行快速拉近、推镜、变焦、裁切放大' in prompt
    assert '焦距、取景范围与人物画面占比保持首帧状态' in prompt
    assert '人物面部、手部、衣料和伞等道具' in prompt
    assert '即使明确要求拉近或近景' in prompt
    explicit = video_prompt(p, '运镜与构图：缓慢推近手部')
    assert '运镜与构图：缓慢推近手部' in explicit
    assert '按指定速度平滑完成' in explicit
