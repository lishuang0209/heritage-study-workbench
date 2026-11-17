"""Output policy for the two workbench project types; old ink stories stay portrait."""

WIDE = '16:9'
PORTRAIT = '9:16'


def ratio_for(project):
    return WIDE if project.get('project_type') == 'heritage' else PORTRAIT


def dimensions(ratio):
    return (1280, 720) if ratio == WIDE else (720, 1280)


def format_for(project):
    ratio = ratio_for(project)
    width, height = dimensions(ratio)
    return dict(ratio=ratio, width=width, height=height)


def generation_options(project):
    # Preserve the existing adapter contract for ordinary ink projects.
    return {'ratio': WIDE} if ratio_for(project) == WIDE else {}


def frame_instruction(project):
    return ('只输出一张横屏16:9画面，按宽屏重新安排主体与环境，不把竖图拉伸或拼贴。'
            if ratio_for(project) == WIDE else '只输出一张竖屏9:16画面。')


def fit_filter(ratio):
    width, height = dimensions(ratio)
    return (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')


def video_frame(path, project, folder):
    """I2V services may follow the first frame's shape instead of the ratio option."""
    if ratio_for(project) != WIDE or not path:
        return path
    from PIL import Image, ImageOps
    from pathlib import Path
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
        if abs(image.width / image.height - 16 / 9) < .01:
            return path
        canvas = Image.new('RGB', dimensions(WIDE), '#faf8f2')
        fitted = ImageOps.contain(image, canvas.size, Image.Resampling.LANCZOS)
        canvas.paste(fitted, ((canvas.width-fitted.width)//2, (canvas.height-fitted.height)//2))
        target = Path(folder) / (Path(path).stem + '-wide-input.png')
        canvas.save(target)
    return target
