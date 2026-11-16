"""User-supplied era, independent of script and painting style."""
from .reference_library import reference_context

def background_context(project, *, include_references=False):
    era = (project.get('background') or {}).get('era', '').strip()
    if era:
        return ('用户指定时代背景：' + era + '。这是用户补充设定，不是从剧本推断。'
                '结合人物身份、年龄、活动场合和地域选择服饰、发式、建筑与器物，不给所有人物套同一种服装。'
                '旧参考图或旧描述中的朝代若与本项冲突，以本项为准；画风独立决定笔墨。' + (reference_context(era) if include_references else ''))
    return ('未补充时代背景：仅遵循剧本中明确写出的时代；剧本未说明时保持朝代未指定，'
            '不得从书生、古寺、油纸伞或水墨画风推断唐宋等具体朝代。旧参考素材的朝代标签不构成时代指定。')
