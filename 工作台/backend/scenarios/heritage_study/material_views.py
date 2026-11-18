"""Select one independently framed material view before asking a model for a shot."""
import hashlib
import json
import math
import re
import uuid
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps, UnidentifiedImageError

from scenarios.ink_drama.domain import UserError

RECIPE='material-single-view-v1'
LAYOUTS={'panoramic-three-view','component-three-view'}
VIEWS=('front','side','oblique')


def frame_style_references(project,prompt,refs,style_reference,*,shot=None):
    from .visit_route import interior_view
    from .guide import guide_shot
    if project.get('project_type')=='heritage' and shot and guide_shot(project,shot):
        return prompt+'\n使用所附同一向导与建筑素材保持身份、形制及当前笔墨，不附加其他人物或建筑样张。',list(refs)
    if project.get('project_type')=='heritage' and shot and interior_view(shot):
        return prompt+'\n本镜取景在内部，笔墨以当前文字画风为准，不附加外立面或其他建筑样张。',list(refs)
    records=project.get('setting_generation_records',{})
    if project.get('project_type')=='heritage' and any(
        Path(path).name.startswith(('material-view-','frame-focus-')) or
        (records.get(Path(path).name,{}).get('heritage_reference') or {}).get('layout') in
        {'panoramic-single-view','component-single-view'} for path in refs):
        # Confirmed material views already carry the checked current style. An
        # extra example depicting another temple introduces a second subject.
        return prompt+'\n所附素材均为本镜主体参考；沿用当前选定笔墨，仅按本镜画面与景别重绘，不将参考中的建筑复制或融合为多座。',list(refs)
    return style_reference(project,prompt,refs,asset_group='frames')


def shot_view(shot):
    for text in (shot.get('camera',''),shot.get('content','')):
        if re.search(r'斜|45[°度]|四分之三|侧前|侧后',text):return 'oblique'
        if re.search(r'正面|正视|正前',text):return 'front'
        if re.search(r'侧面|侧视|侧向|90[°度]',text):return 'side'
    return 'front'


def sheet_boxes(image):
    """Find blank separators, never assume three equal-width crops.

    Ink/edge projection ignores gradual paper shading. A sheet without two
    unambiguous empty separators is rejected instead of sent as a composite.
    """
    width,height=image.size
    if width<120 or height<60 or width<height:
        raise UserError('素材三视图没有清晰分开的三个视角，请重新生成素材或上传单视角图片；本次未调用生成模型')
    scale=min(1,1024/width)
    gray=ImageOps.grayscale(image).resize((round(width*scale),round(height*scale)),Image.Resampling.LANCZOS)
    w,h=gray.size
    smooth=gray.filter(ImageFilter.GaussianBlur(.65))
    edges=ImageChops.difference(smooth,smooth.filter(ImageFilter.GaussianBlur(3)))
    # Paper texture is low contrast; only persistent strokes count as a subject.
    mask=edges.point(lambda value:255 if value>=9 else 0)
    pixels=mask.load()
    top,bottom=max(2,int(h*.03)),min(h-2,int(h*.97))
    counts=[sum(pixels[x,y]>0 for y in range(top,bottom)) for x in range(w)]
    active=[count>=max(3,round(h*.006)) for count in counts]
    occupied=[x for x,present in enumerate(active) if present]
    if not occupied:
        raise UserError('素材三视图没有可辨识的主体，请重新生成素材；本次未调用生成模型')
    left,right=occupied[0],occupied[-1]+1
    span=right-left
    gaps=[];start=None
    for x in range(left,right+1):
        blank=x<right and not active[x]
        if blank and start is None:start=x
        if not blank and start is not None:
            if x-start>=max(3,round(w*.003)):gaps.append((start,x))
            start=None
    candidates=[]
    for a in gaps:
        for b in gaps:
            if a[1]>=b[0]:continue
            if not (left+.18*span<sum(a)/2<left+.48*span and left+.52*span<sum(b)/2<left+.82*span):continue
            cuts=(0,round(sum(a)/2),round(sum(b)/2),w)
            if min(cuts[i+1]-cuts[i] for i in range(3))<span*.15:continue
            candidates.append((a[1]-a[0]+b[1]-b[0],cuts))
    if not candidates:
        raise UserError('素材三视图未检测到两个清晰的视角间隔，已停止以免混合建筑；请重新生成素材或上传单视角图片')
    _,cuts=max(candidates)
    for index in range(3):
        start,end=cuts[index:index+2]
        if any(start+(end-start)*.28<(a+b)/2<end-(end-start)*.28
               and a>start and b<end and min(a-start,end-b)>w*.08 for a,b in gaps):
            raise UserError('素材视角数量或分隔不清晰，无法安全选择单一视角；请换用单视角素材')
    boxes=[]
    for index in range(3):
        pane=(cuts[index],top,cuts[index+1],bottom)
        bbox=mask.crop(pane).getbbox()
        if not bbox:
            raise UserError('素材三视图有空白视角，请重新生成素材；本次未调用生成模型')
        x,y,x2,y2=bbox
        margin=max(5,round(max(x2-x,y2-y)*.035))
        box=(max(pane[0],x+pane[0]-margin),max(0,y+top-margin),
             min(pane[2],x2+pane[0]+margin),min(h,y2+top+margin))
        boxes.append((math.floor(box[0]/scale),math.floor(box[1]/scale),
                      min(width,math.ceil(box[2]/scale)),min(height,math.ceil(box[3]/scale))))
    return dict(zip(VIEWS,boxes))


def material_reference(project,shot,item,store):
    name=item.get('image')
    if not name:return None
    source=store.asset(project['id'],name)
    record=project.get('setting_generation_records',{}).get(name,{})
    layout=(record.get('heritage_reference') or {}).get('layout')
    if project.get('project_type')!='heritage':
        return str(source)
    if layout not in LAYOUTS:
        if layout=='panoramic-single-view':
            from .frame_design import scene_focus_reference
            return scene_focus_reference(project,shot,item,store,source)
        return str(source)
    view=shot_view(shot)
    try:
        digest=hashlib.sha256(source.read_bytes()+RECIPE.encode()).hexdigest()[:20]
        target=store.folder(project['id'])/f'material-view-{digest}-{view}.png'
        if not target.is_file():
            with Image.open(source) as original:
                image=ImageOps.exif_transpose(original).convert('RGB')
                boxes=sheet_boxes(image);box=boxes[view]
                cropped=image.crop(box)
                reference=Image.new('RGB',(1280,720),image.getpixel((0,0)))
                fitted=ImageOps.contain(cropped,(1200,640),Image.Resampling.LANCZOS)
                reference.paste(fitted,((1280-fitted.width)//2,(720-fitted.height)//2))
                temporary=target.with_name(f'{target.stem}-{uuid.uuid4().hex}.tmp.png')
                reference.save(temporary,'PNG');temporary.replace(target)
            target.with_suffix('.json').write_text(json.dumps(dict(recipe=RECIPE,source_image=name,
                source_digest=digest,layout=layout,view=view,box=box),ensure_ascii=False))
        if layout=='panoramic-three-view':
            from .frame_design import scene_focus_reference
            return scene_focus_reference(project,shot,item,store,target)
        return str(target)
    except (OSError,UnidentifiedImageError) as exc:
        raise UserError('素材三视图无法读取，请重新上传或生成素材；原分镜已保留') from exc
