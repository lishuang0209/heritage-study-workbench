"""Derive a real photographic detail and transform its original annotation."""
import math

from PIL import Image

from scenarios.ink_drama.domain import UserError


def crop_detail(source, mark, target):
    with Image.open(source) as original:
        original.load()
        width, height = original.size
        left, right = sorted((mark['x'] * width, mark['x2'] * width))
        top, bottom = sorted((mark['y'] * height, mark['y2'] * height))
        # Leave context and enough room for the inherited annotation stroke.
        pad_x = max(width * .025, (right-left) * .15, 12)
        pad_y = max(height * .025, (bottom-top) * .15, 12)
        box = (max(0, math.floor(left-pad_x)), max(0, math.floor(top-pad_y)),
               min(width, math.ceil(right+pad_x)), min(height, math.ceil(bottom+pad_y)))
        x, y, x2, y2 = box
        if x2 <= x or y2 <= y:
            raise UserError('框选区域无效，请重新标注定位图')
        image = original.crop(box).convert('RGB')
        mapped = dict(kind=mark['kind'], x=(mark['x']*width-x)/(x2-x),
                      y=(mark['y']*height-y)/(y2-y), x2=(mark['x2']*width-x)/(x2-x),
                      y2=(mark['y2']*height-y)/(y2-y))
        if not all(.012 <= mapped[key] <= .988 for key in ('x', 'y', 'x2', 'y2')):
            raise UserError('标注太靠近照片边缘，请向内调整后生成特写')
        image.save(target, 'JPEG', quality=94)
    return dict(width=x2-x, height=y2-y, crop=list(box), mark=mapped)
