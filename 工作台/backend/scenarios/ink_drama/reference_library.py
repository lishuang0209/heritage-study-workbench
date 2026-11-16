"""Curated local evidence; no runtime web search or automatic era inference."""
import json
from pathlib import Path
from functools import lru_cache

ERA_CHOICES = ('', '汉代', '唐代', '宋代', '北宋', '南宋', '明代', '清代')
ALIASES = {'汉': '汉代', '唐': '唐代', '宋': '宋代', '明': '明代', '清': '清代'}

@lru_cache(maxsize=1)
def library():
    return json.loads((Path(__file__).parent / 'references/eras.json').read_text())

def reference_info(era):
    era = ALIASES.get(era.strip(), era.strip())
    entries = [entry for entry in library()['entries'] if era in entry['eras']]
    return {'era': era, 'version': library()['version'], 'entries': entries,
            'status': 'partial' if entries else 'unavailable' if era else 'unspecified'}

def reference_context(era):
    info = reference_info(era)
    if not era.strip():
        return ''
    if not info['entries']:
        return '\n本地参考资料：此时代暂无匹配资料。按用户指定时代和模型已有知识生成，不借用唐宋模板，不声称已考据；不确定形制需人工核对。'
    return ('\n本地参考资料（局部证据，不是整朝通用模板）：\n'
            '先核对年代、地域、身份与场合，仅使用适用事实，不将北宋和南宋样本自动混搭。'
            '没有证据的服饰、男性头巾、油纸伞结构等不得声称已核实。'
            '资料不改变剧情、人物动作或山门/佛殿等场景类型；不把资料中的颜色强加为画风。\n'
            + json.dumps(info['entries'], ensure_ascii=False))
