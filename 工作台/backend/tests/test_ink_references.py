from scenarios.ink_drama.reference_library import reference_info, reference_context, ERA_CHOICES
from scenarios.ink_drama.background import background_context


def test_every_offered_era_has_sourced_evidence():
    for era in ERA_CHOICES:
        if not era:
            continue
        info = reference_info(era)
        assert info['entries'], era
        assert all(e['url'].startswith('https://') and e['limits'] for e in info['entries'])


def test_unset_unknown_and_subperiod_isolation():
    assert reference_context('') == ''
    assert reference_info('架空')['entries'] == []
    assert '暂无匹配资料' in reference_context('元代')
    assert reference_info('唐')['entries'] == reference_info('唐代')['entries']
    assert 'southern-song-gauze' not in {e['id'] for e in reference_info('北宋')['entries']}
    assert 'northern-song-figures' not in {e['id'] for e in reference_info('南宋')['entries']}


def test_context_reaches_generation_without_changing_script():
    project = {'script': '书生在古寺避雨', 'background': {'era': '明代'}}
    result = background_context(project, include_references=True)
    assert 'ming-dress' in result
    assert 'tang-figure' not in result
    assert project['script'] == '书生在古寺避雨'
    assert '本地参考资料' not in background_context({'script': '宋代书生'})


def test_image_and_video_context_never_contains_library_titles():
    p = {'background': {'era': '宋代'}}
    image_context = background_context(p)
    assert '宋代' in image_context
    for word in ('素罗单衣', '抱印', 'http', '酒注'):
        assert word not in image_context
    assert '素罗单衣' in background_context(p, include_references=True)
