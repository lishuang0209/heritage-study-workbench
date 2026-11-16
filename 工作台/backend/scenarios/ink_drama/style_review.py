"""Region-specific visual review, independent of identity caption snapshots."""
from typing import Literal
from pydantic import Field
from .domain import Strict

class Region(Strict):
    status: Literal['consistent', 'deviates', 'uncertain', 'absent']
    evidence: str = Field(min_length=1, max_length=500)

class StyleReview(Strict):
    main_building: Region
    characters: Region
    background: Region
    extra_building: Region
    framing: Region
    staging: Region = Field(default_factory=lambda: Region(status='uncertain', evidence='本次未检查站位'))


def review_result(review):
    labels = {'main_building': '主建筑', 'characters': '人物', 'background': '背景', 'extra_building': '额外建筑', 'framing': '景别', 'staging': '场景空间关系'}
    statuses = {'consistent': '未见明显偏差', 'deviates': '可能偏离', 'uncertain': '无法确定', 'absent': '未出现'}
    regions = review.model_dump()
    deviates = [labels[k] for k, v in regions.items() if v['status'] == 'deviates']
    return {'message': ('需要核对：' + '、'.join(deviates)) if deviates else '分区检查完成，仍需对照样张人工确认。',
            'techniques': [], 'regions': regions, 'spatial_policy': 2,
            'uncertainties': [labels[k] + ' · ' + statuses[v['status']] + '：' + v['evidence'] for k, v in regions.items()]}
