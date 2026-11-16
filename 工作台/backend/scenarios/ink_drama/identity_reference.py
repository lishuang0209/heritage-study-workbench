"""Stable identity references for character restyling (no model calls)."""
from PIL import Image, ImageOps
from .domain import UserError


def identity_source(project, item):
    # Follow provenance back to the identity anchor, not the last generated face.
    name = item.get('image')
    seen = set()
    records = project.get('setting_generation_records', {})
    while name and name not in seen:
        seen.add(name)
        source = records.get(name, {}).get('identity_source')
        if not source:
            break
        name = source
    return name


def portrait_reference(source, target):
    """Upper portrait region for the platform's centered full-body character sheets.

    Landscape/multi-view sheets are not silently cropped to an arbitrary person.
    """
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        width, height = image.size
        if width >= height:
            raise UserError('换画风需要单人竖版角色图；请先上传单人角色图，避免从多人设定图中截错人物。')
        image.crop((int(width * .15), 0, int(width * .85), int(height * .43))).save(target)
    return str(target)
