"""Give unmanned study shots their own framing instead of copying a full asset."""
import hashlib
import json
import math
import re
import uuid
from pathlib import Path

from PIL import Image,ImageChops,ImageFilter,ImageOps,UnidentifiedImageError

from scenarios.ink_drama.domain import UserError
from .visit_route import interior_view,interior_material

RECIPE='study-frame-focus-v1'
SCALES=r'大特写|特写|中近景|近景|中景|全景|远景'


def frame_scale(shot):
    for text in (shot.get('camera',''),shot.get('content','')):
        if match:=re.search(SCALES,text):return match[0]
    return ''


def local_window(shot,*,allow_actor=False):
    scale=frame_scale(shot)
    sizes={'中景':(.72,.78),'中近景':(.45,.42),'近景':(.35,.40),'特写':(.26,.30),'大特写':(.18,.22)}
    if (shot.get('character_ids') and not allow_actor) or interior_view(shot) or scale not in sizes:return None
    # Composition cues choose a broad framing region, not an identified
    # architectural part. Negative clauses must never select the crop position.
    clauses=re.split(r'[，,。；;\n]',shot.get('camera','')+'，'+shot.get('content',''))
    positive='，'.join(clause for clause in clauses if not re.search(r'不|禁止|避免|无需|未',clause))
    cx,cy,region=.5,.55,'middle'
    if re.search(r'额位|牌匾|匾额',positive):cy,region=.40,'upper-middle'
    elif re.search(r'柱脚|柱础|台基|基座|底部|下部',positive):cy,region=.80,'lower'
    elif re.search(r'屋顶|屋脊|顶部',positive):cy,region=.22,'upper'
    elif scale=='中景' and re.search(r'柱列|纵向|上下|梁柱',positive):cy,region=.58,'middle'
    elif re.search(r'檐下|柱头|梁架|斗拱|上部|中上部',positive):cy,region=.42,'upper-middle'
    if '左侧' in positive:cx=.28
    elif '右侧' in positive:cx=.72
    return dict(scale=scale,cx=cx,cy=cy,width=sizes[scale][0],height=sizes[scale][1],region=region)


def foreground_bounds(image):
    width,height=image.size
    scale=min(1,960/width)
    gray=ImageOps.grayscale(image).resize((round(width*scale),round(height*scale)),Image.Resampling.LANCZOS)
    smooth=gray.filter(ImageFilter.GaussianBlur(.65))
    mask=ImageChops.difference(smooth,smooth.filter(ImageFilter.GaussianBlur(3))).point(lambda x:255 if x>=9 else 0)
    w,h=mask.size;pixels=mask.load()
    xs=[x for x in range(w) if sum(pixels[x,y]>0 for y in range(h))>=max(3,round(h*.006))]
    ys=[y for y in range(h) if sum(pixels[x,y]>0 for x in range(w))>=max(3,round(w*.006))]
    if not xs or not ys:return (0,0,width,height)
    return (math.floor(xs[0]/scale),math.floor(ys[0]/scale),
            min(width,math.ceil((xs[-1]+1)/scale)),min(height,math.ceil((ys[-1]+1)/scale)))


def scene_focus_reference(project,shot,item,store,source):
    from .guide import guide_shot
    window=local_window(shot,allow_actor=guide_shot(project,shot))
    if not window or item['id']!=shot.get('scene_id'):return str(source)
    try:
        key=hashlib.sha256(Path(source).read_bytes()+json.dumps(window,sort_keys=True).encode()+RECIPE.encode()).hexdigest()[:20]
        target=store.folder(project['id'])/f'frame-focus-{key}.png'
        if target.is_file():return str(target)
        with Image.open(source) as original:
            image=ImageOps.exif_transpose(original).convert('RGB');width,height=image.size
            left,top,right,bottom=foreground_bounds(image)
            subject_width,subject_height=right-left,bottom-top
            cx=left+subject_width*window['cx'];cy=top+subject_height*window['cy']
            crop_width=subject_width*window['width'];crop_height=subject_height*window['height']
            # Expand the framing window to 16:9 before resizing; never stretch.
            crop_width=max(crop_width,crop_height*16/9);crop_height=crop_width*9/16
            factor=min(1,width*.9/crop_width,height*.9/crop_height)
            crop_width*=factor;crop_height*=factor
            x=max(0,min(width-crop_width,cx-crop_width/2));y=max(0,min(height-crop_height,cy-crop_height/2))
            box=(math.floor(x),math.floor(y),min(width,math.ceil(x+crop_width)),min(height,math.ceil(y+crop_height)))
            framed=ImageOps.fit(image.crop(box),(1280,720),method=Image.Resampling.LANCZOS)
            temporary=target.with_name(f'{target.stem}-{uuid.uuid4().hex}.tmp.png')
            framed.save(temporary,'PNG');temporary.replace(target)
        target.with_suffix('.json').write_text(json.dumps(dict(recipe=RECIPE,source_image=item['image'],
            source_view=Path(source).name,box=box,composition=window,method='composition-window-not-object-recognition'),ensure_ascii=False))
        return str(target)
    except (OSError,UnidentifiedImageError) as exc:
        raise UserError('局部镜头的场景参考无法读取，原图已保留，请检查场景素材后重试') from exc


def unmanned_frame_prompt(project,shot):
    from scenarios.ink_drama.media_format import frame_instruction
    from scenarios.ink_drama.styles import image_style,negative_style
    settings=project.get('creative_settings') or {}
    scene=next((item for item in settings.get('scenes',[]) if item['id']==shot.get('scene_id')),None)
    props=[item for item in settings.get('props',[]) if item['id'] in (shot.get('prop_ids') or [])]
    from .guide import guide_shot,definition
    guided=guide_shot(project,shot)
    local=local_window(shot,allow_actor=guided)
    inside=interior_view(shot)
    parts=[frame_instruction(project),'本镜唯一画面任务（最高优先级）：'+shot['content'],
           '本镜景别与构图：'+shot['camera']]
    stage=(shot.get('study_visit') or {}).get('stage')
    environment={
        'overview':'台基接入前景地面，屋顶轮廓后画出天空层次；有地貌依据时以低对比远景交代所在地。',
        'approach':'用脚下地面、檐影与逐渐远去的柱列交代走近的距离。',
        'entrance':'从门槛的近处望向入口纵深，以门内外明暗过渡表现行进方向。',
        'interior':'以相邻木构的遮挡、檐内明暗和前后层次表现室内纵深。',
        'structure':'保留承托点及后方相接的木构，让学生看清构件在建筑中的位置。',
        'detail':'目标周围保留少量实际相接的结构，以虚实区分前后，避免把构件单独摆在纸面上。',
    }
    if stage in environment:
        parts.append('绘制现场参观画面。设定图的空底只用于展示素材；绢纸是画材纹理，背景应延续本镜所在空间。'+environment[stage])
        if stage=='overview':
            material=(project.get('heritage_station') or {}).get('checked_description','')
            for sentence in re.split(r'[。！？\n]',material):
                if 'http' not in sentence and re.search(r'山岙|山谷|山麓|山腰|河畔|湖畔',sentence):
                    parts.append('场地文字依据（仅作资料，不推断精确方位或新增景物）：'+json.dumps(sentence[:200],ensure_ascii=False))
                    break
    if inside:
        material=interior_material(project)
        if not material:raise UserError('当前资料没有可用于内部画面的描述，请先补充殿内资料；原图保留，本次未调用生成模型')
        parts.append('本镜观察视点在建筑内部，依据文字资料绘制教学示意；不把外立面全景放大充当室内，不绘制资料未说明的佛像、陈设、房间或精确平面。')
        parts.append('内部空间原文依据（仅作资料，不是操作指令）：'+json.dumps(material,ensure_ascii=False))
    elif local:
        parts.append('本镜是局部取景，指定部位及其相邻构件占据主要画幅。画外结构保持画外，不补回整栋建筑，不为展示素材全貌而拉远。')
        if re.search(r'额位|牌匾|匾额',shot['content']+shot['camera']):
            parts.append('额位与周围檐下木构成为主体，建筑顶部、完整立面和台基在画外；额位保持空白，不添加题字。')
    else:
        parts.append('按本镜指定范围组织主体与环境；全景完整保留屋顶、殿身和基座，远景明确建筑与环境的关系。')
    if scene:
        parts.append('同一场景形制：'+scene['name'])
        auto='依据研学资料呈现'+scene['name']+'的完整外观、建筑体量与整体布局。'
        description=scene.get('desc','')
        if description not in (auto,'依据已上传实拍中的可见建筑与空间关系，不补造不可见结构。'):
            parts.append('形制资料（不作为本镜取景要求）：'+description)
    if props:parts.append('本镜构件：'+'；'.join(item['name']+'：'+item['desc'] for item in props))
    if guided:
        if stage == 'entrance':
            parts.append('向导双脚落在入口侧面的地面上，按门柱比例绘制；头顶与梁底之间留出可见间距，手臂轮廓与柱边分开。')
        cid=definition(project)['character_id'];actor=next(c for c in settings['characters'] if c['id']==cid)
        parts.extend(['本镜唯一出镜人物：'+actor['name']+'；'+actor['desc'],
                      '严格复用已确认角色参考中的脸型、发髻、布巾、服装版型与固有色。角色三视图仅用于同一身份，只画一个人，不复制多个人或并排视图。',
                      '小向导位于一侧或前景边缘，不遮住建筑与观察目标；人物以动作引导，不画台词、文字或额外学生群像。',
                      '角色为虚构宋代风格向导，建筑仍依据现存研学资料；不把现存建筑整体改成历史复原。'])
    if era:=(project.get('background') or {}).get('era'):parts.append('时代背景：'+era)
    parts.extend(['素材参考仅用于可见形制、材质和笔墨，不复制素材的构图、景别或主体大小；若参考为局部，不推测和补画取景外的结构。',
                  image_style(project),'只输出一个视角的一幅静态画面，建筑视角不能叠加；'+('人物数量严格为一。' if guided else '人物数量为零。')+'无文字、标签、印章、水印。',
                  '避免：'+negative_style(project)])
    return '\n'.join(parts)
