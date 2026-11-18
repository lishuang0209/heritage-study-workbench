"""One landscape photo transform is shared by previews, movie tails and A4 cards."""
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from scenarios.ink_drama.domain import UserError
from scenarios.ink_drama.providers import checked_ffmpeg
from .domain import crop_bounds, observation_guidance
from .timing import timing_for, observation_slots

SIZE = (1280, 720)

FONT_PATHS = [('/System/Library/Fonts/STHeiti Light.ttc',1),
              ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',2),
              ('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',0),
              ('C:/Windows/Fonts/msyh.ttc',0),
              ('/System/Library/Fonts/Supplemental/Songti.ttc',3)]


@lru_cache(maxsize=128)
def font(size,weight='regular'):
    candidates=([('/System/Library/Fonts/STHeiti Medium.ttc',1),
                 ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',2)] if weight=='medium' else [])+FONT_PATHS
    for path,index in candidates:
        if Path(path).is_file(): return ImageFont.truetype(path,size,index=index)
    raise UserError('缺少中文字体，请安装思源黑体或Noto Sans CJK后再导出')


def lines(text, face, width):
    result = []
    for paragraph in text.split('\n'):
        line = ''
        for char in paragraph:
            if face.getlength(line+char) > width and line:
                # Keep Chinese closing punctuation off the start of a line,
                # and opening brackets off the end, without dropping text.
                carry=''
                if char in '，。！？；：、）》】」』”’…' or line[-1] in '（《【「『“‘':
                    carry=line[-1];line=line[:-1]
                if line: result.append(line)
                line=carry
            line += char
        result.append(line)
    return result


def block(draw, text, box, size=26, fill='#25231f',weight='regular',line_height=1.35):
    x,y,w,h = box
    for candidate in range(size,13,-1):
        face = font(candidate,weight); wrapped = lines(text,face,w); leading=math.ceil(candidate*line_height)
        if len(wrapped)*leading <= h: break
    else: raise UserError('导出文字过长，请缩短讲解站名称、任务或署名')
    for line in wrapped:
        draw.text((x,y),line,font=face,fill=fill,anchor='lt'); y += leading
    return y


def annotated_photo(store, pid, photo, size=SIZE):
    with Image.open(store.asset(pid,photo['image'])) as source:
        original = ImageOps.exif_transpose(source).convert('RGB')
    width,height = original.size
    canvas = Image.new('RGB',size,'#f1eee7')
    output_width,output_height=size
    x,y,w,h = crop_bounds(width,height,photo)
    if photo['mode']=='cover':
        crop=original.crop((round(x*width),round(y*height),round((x+w)*width),round((y+h)*height)))
        factor=min(output_width/crop.width,output_height/crop.height)
        rw,rh=round(crop.width*factor),round(crop.height*factor)
        ox,oy=(output_width-rw)/2,(output_height-rh)/2;sx,sy=rw/w,rh/h
        canvas.paste(crop.resize((rw,rh),Image.Resampling.LANCZOS),(round(ox),round(oy)))
    else:
        factor=min(output_width/width,output_height/height); rw,rh=round(width*factor),round(height*factor)
        ox,oy=(output_width-rw)/2,(output_height-rh)/2;sx,sy=rw,rh
        canvas.paste(original.resize((rw,rh),Image.Resampling.LANCZOS),(round(ox),round(oy)))
    mark=photo.get('mark')
    if mark:
        pts=[(ox+(mark[a]-x)*sx,oy+(mark[b]-y)*sy) for a,b in (('x','y'),('x2','y2'))]
        draw=ImageDraw.Draw(canvas)
        stroke_scale=min(size)/720
        outer=max(3,round(12*stroke_scale));inner=max(2,round(6*stroke_scale))
        if mark['kind']=='rectangle':
            bounds=(min(pts[0][0],pts[1][0]),min(pts[0][1],pts[1][1]),max(pts[0][0],pts[1][0]),max(pts[0][1],pts[1][1]))
            draw.rectangle(bounds,outline='white',width=outer);draw.rectangle(bounds,outline='#af2424',width=inner)
        else:
            angle=math.atan2(pts[1][1]-pts[0][1],pts[1][0]-pts[0][0])
            head=[(pts[1][0]-28*stroke_scale*math.cos(angle-d),pts[1][1]-28*stroke_scale*math.sin(angle-d)) for d in (-.5,.5)]
            for color,stroke in (('white',outer),('#af2424',inner)):
                draw.line(pts,fill=color,width=stroke)
                draw.line([head[0],pts[1],head[1]],fill=color,width=stroke)
    return canvas


def credit(photo):
    return f'照片：{photo["author"]} | {photo["license"]} | 已裁切/标注\n来源：{photo["source"]}'


def photo_frame(store,pid,station,slot,text,phase='observation'):
    photo=station[slot]
    canvas=Image.new('RGB',SIZE,'#faf8f2');draw=ImageDraw.Draw(canvas)
    block(draw,station['building'],(48,30,1184,46),32,weight='medium')
    block(draw,station['name'],(48,83,1184,30),21,fill='#73756f')
    draw.line((48,122,1232,122),fill='#deded7',width=1)
    image=annotated_photo(store,pid,photo,size=(704,464))
    mask=Image.new('L',image.size,0);ImageDraw.Draw(mask).rounded_rectangle((0,0,703,463),radius=12,fill=255)
    canvas.paste(image,(48,144),mask)
    question=station.get('question','').strip()
    guidance=text.strip()
    if question and guidance.endswith(question):
        guidance=guidance[:-len(question)].rstrip()
    else:
        question=''
    x,width=800,432
    block(draw,'现场任务' if phase=='task' else '观察指引',(x,148,width,26),18,fill='#74776f',weight='medium')
    body_bottom=608
    if question:
        # Reserve a separate question card before laying out the instructions.
        for question_size in range(27,17,-1):
            question_lines=lines(question,font(question_size,'medium'),width-40)
            question_height=len(question_lines)*math.ceil(question_size*1.55)
            if question_height<=142:break
        else:raise UserError('观察问题过长，请精简后再导出；原内容已保留')
        card_height=question_height+78;top=608-card_height
        draw.rounded_rectangle((x,top,x+width,608),radius=12,fill='#eeeee7')
        block(draw,'想一想',(x+20,top+18,width-40,24),17,fill='#74776f')
        block(draw,question,(x+20,top+54,width-40,question_height+2),question_size,weight='medium',line_height=1.55)
        body_bottom=top-28
    # Short directions read as complete clauses instead of splitting words
    # such as 柱子/指出 across arbitrary character-count lines.
    phrased=re.sub(r'([，；。！？])(?=\S)',r'\1\n',guidance)
    if len(lines(phrased,font(28),width))*math.ceil(28*1.65)<=body_bottom-194:
        guidance=phrased
    block(draw,guidance,(x,194,width,body_bottom-194),28,fill='#3b3e38',line_height=1.65)
    draw.line((48,632,1232,632),fill='#deded7',width=1)
    block(draw,credit(photo),(48,650,1184,56),14,fill='#6e7169',line_height=1.5)
    return canvas


def task_card(store,pid,station,target):
    page=Image.new('RGB',(1240,1754),'white');draw=ImageDraw.Draw(page)
    block(draw,'古建观察任务卡',(65,42,1110,70),50)
    block(draw,station['building']+' · '+station['name'],(65,120,1110,100),42)
    block(draw,'适用年级：'+station['grade']+'    目标构件：'+station['component'],(65,218,1110,66),27)
    page.paste(annotated_photo(store,pid,station['panorama']).resize((1110,624)),(65,292))
    block(draw,'观察指引\n'+observation_guidance(station),(65,952,1110,350),36)
    block(draw,'观察问题\n'+station['question'],(65,1340,1110,210),36)
    credits=credit(station['panorama'])
    if station.get('detail'):credits+='\n特写'+credit(station['detail'])
    block(draw,credits,(65,1600,1110,137),18)
    # 1240 x 1754 pixels at 150 dpi -> one printable A4 page (within 0.4 mm).
    page.save(target,'PDF',resolution=150)


def story_clips(api,p,replace_narration=False):
    from .narration import narrated_shot
    ready=[]
    for shot in p['shots']:
        # Full-film narration is dubbed once at chapter level. Reuse the video
        # source directly so a voice change doesn't require dubbing every shot.
        raw=replace_narration and narrated_shot(p,shot) and shot.get('clip')
        video=raw or shot.get('rendered')
        if not video or any(shot.get(k) for k in ('image_stale','clip_stale')) or (not raw and shot.get('rendered_stale')):
            raise UserError('请先在水墨故事中完成并确认各个故事片段')
        ready.append(api.store.asset(p['id'],video))
    if not ready: raise UserError('请先制作水墨故事片段，或导入已有水墨镜头')
    return ready


def export_video(api,p,station,script,folder,target,replace_narration=False):
    if p.get('heritage_story_stale'):
        raise UserError('历史旁白已更新，旧镜头已保留；请重新生成并采用分镜后再导出短片')
    timing=timing_for(p);intro_seconds=timing['intro'];total=sum(timing.values())
    ready=story_clips(api,p,replace_narration)
    lengths=[api.providers.duration(path) for path in ready]
    if sum(lengths)>intro_seconds+.05: raise UserError(f'历史引入镜头需不超过{intro_seconds}秒，请减少镜头或调整时长；不会自动截掉对白')
    storybase=folder/(target.stem+'-story-base.mp4')
    api.providers.assemble(ready,None,folder,storybase,ratio='16:9')
    story=folder/(target.stem+'-story.mp4')
    checked_ffmpeg(['-i',str(storybase),'-filter_complex',
        f'[0:v]tpad=stop_mode=clone:stop_duration={intro_seconds},trim=duration={intro_seconds},setpts=PTS-STARTPTS[out]',
        '-map','[out]','-map','0:a:0','-af',f'apad,atrim=duration={intro_seconds}','-t',str(intro_seconds),
        '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-r','30','-c:a','aac',str(story)])
    chapters=[dict(kind='story',duration=intro_seconds,video=story.name)]
    slots=observation_slots(timing['location'],bool(station.get('detail')))
    segments=[story]
    for slot,duration in slots+[('task',timing['task'])]:
        key='detail' if slot=='task' and station.get('detail') else 'panorama' if slot=='task' else slot
        text=observation_guidance(station)+'\n'+station['question'] if slot=='task' else script['location']
        frame=folder/(target.stem+'-'+slot+'.png')
        photo_frame(api.store,p['id'],station,key,text,phase='task' if slot=='task' else 'observation').save(frame)
        clip=frame.with_suffix('.mp4')
        checked_ffmpeg(['-loop','1','-i',str(frame),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
            '-t',str(duration),'-c:v','libx264','-preset','veryfast','-tune','stillimage',
            '-pix_fmt','yuv420p','-r','30','-c:a','aac','-shortest',str(clip)])
        segments.append(clip);chapters.append(dict(kind=slot,duration=duration,video=clip.name))
    api.providers.assemble(segments,None,folder,target,ratio='16:9')
    if abs(api.providers.duration(target)-total)>.15:raise UserError('研学成片时长校验失败，旧导出已保留')
    return chapters


def add_voiceover(api,p,script,target,user):
    """Explicit optional online TTS; never truncates a teacher's spoken text."""
    timing=timing_for(p);total=sum(timing.values())
    from .narration import speak
    inputs,filters=[],[]
    for i,(key,duration) in enumerate(timing.items()):
        voice=target.with_name(target.stem+f'-voice-{key}.mp3')
        api.call(user,'speech',p['id'],lambda key=key,voice=voice:speak(api.providers,p,script[key],voice))
        if api.providers.duration(voice)>duration+.05:
            raise UserError(f'{ {"intro":"历史引入","location":"实物观察","task":"现场任务"}[key]}配音超过{duration}秒，请延长该段时长或缩短台词后重试；原导出保留')
        inputs+=['-i',str(voice)]
        filters.append(f'[{i}:a:0]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]')
    audio=target.with_name(target.stem+'-narration.m4a')
    filters.append('[a0][a1][a2]concat=n=3:v=0:a=1[out]')
    checked_ffmpeg([*inputs,'-filter_complex',';'.join(filters),'-map','[out]','-c:a','aac',str(audio)])
    mux=target.with_name(target.stem+'-narrated.mp4')
    checked_ffmpeg(['-i',str(target),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-t',str(total),'-movflags','+faststart',str(mux)])
    mux.replace(target)
