"""One photo transform is shared by portrait previews, movie tails and A4 cards."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from scenarios.ink_drama.domain import UserError
from scenarios.ink_drama.providers import checked_ffmpeg
from .domain import crop_bounds, observation_guidance
from .timing import timing_for, observation_slots

FONT_PATHS = ['/System/Library/Fonts/Supplemental/Songti.ttc',
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', 'C:/Windows/Fonts/msyh.ttc']


def font(size):
    for path in FONT_PATHS:
        if Path(path).is_file(): return ImageFont.truetype(path,size)
    raise UserError('缺少中文字体，请安装思源黑体或Noto Sans CJK后再导出')


def lines(text, face, width):
    result = []
    for paragraph in text.split('\n'):
        line = ''
        for char in paragraph:
            if face.getlength(line+char) > width and line:
                result.append(line); line = ''
            line += char
        result.append(line)
    return result


def block(draw, text, box, size=26, fill='#25231f'):
    x,y,w,h = box
    for candidate in range(size,13,-1):
        face = font(candidate); wrapped = lines(text,face,w); leading=math.ceil(candidate*1.35)
        if len(wrapped)*leading <= h: break
    else: raise UserError('导出文字过长，请缩短讲解站名称、任务或署名')
    for line in wrapped:
        draw.text((x,y),line,font=face,fill=fill); y += leading
    return y


def annotated_photo(store, pid, photo):
    with Image.open(store.asset(pid,photo['image'])) as source:
        original = ImageOps.exif_transpose(source).convert('RGB')
    width,height = original.size
    canvas = Image.new('RGB',(720,960),'#f1eee7')
    x,y,w,h = crop_bounds(width,height,photo)
    if photo['mode']=='cover':
        crop=original.crop((round(x*width),round(y*height),round((x+w)*width),round((y+h)*height)))
        resized=crop.resize((720,960),Image.Resampling.LANCZOS)
        canvas.paste(resized,(0,0)); ox=oy=0; sx=720/w;sy=960/h
    else:
        factor=min(720/width,960/height); rw,rh=round(width*factor),round(height*factor)
        ox,oy=(720-rw)/2,(960-rh)/2;sx,sy=rw,rh
        canvas.paste(original.resize((rw,rh),Image.Resampling.LANCZOS),(round(ox),round(oy)))
    mark=photo.get('mark')
    if mark:
        pts=[(ox+(mark[a]-x)*sx,oy+(mark[b]-y)*sy) for a,b in (('x','y'),('x2','y2'))]
        draw=ImageDraw.Draw(canvas)
        if mark['kind']=='rectangle':
            bounds=(min(pts[0][0],pts[1][0]),min(pts[0][1],pts[1][1]),max(pts[0][0],pts[1][0]),max(pts[0][1],pts[1][1]))
            draw.rectangle(bounds,outline='white',width=12);draw.rectangle(bounds,outline='#af2424',width=6)
        else:
            angle=math.atan2(pts[1][1]-pts[0][1],pts[1][0]-pts[0][0])
            head=[(pts[1][0]-28*math.cos(angle-d),pts[1][1]-28*math.sin(angle-d)) for d in (-.5,.5)]
            for color,stroke in (('white',13),('#af2424',7)):
                draw.line(pts,fill=color,width=stroke)
                draw.line([head[0],pts[1],head[1]],fill=color,width=stroke)
    return canvas


def credit(photo):
    return f'照片：{photo["author"]} | {photo["license"]} | 已裁切/标注\n来源：{photo["source"]}'


def photo_frame(store,pid,station,slot,text):
    photo=station[slot]
    canvas=Image.new('RGB',(720,1280),'#faf8f2');draw=ImageDraw.Draw(canvas)
    block(draw,station['building']+' · '+station['name'],(26,14,668,94),32)
    canvas.paste(annotated_photo(store,pid,photo).resize((630,840)),(45,110))
    block(draw,text,(30,962,660,222),28)
    block(draw,credit(photo),(30,1190,660,80),15)
    return canvas


def task_card(store,pid,station,target):
    page=Image.new('RGB',(1240,1754),'white');draw=ImageDraw.Draw(page)
    block(draw,'古建观察任务卡',(65,42,1110,70),50)
    block(draw,station['building']+' · '+station['name'],(65,120,1110,100),42)
    block(draw,'适用年级：'+station['grade']+'    目标构件：'+station['component'],(65,218,1110,66),27)
    page.paste(annotated_photo(store,pid,station['panorama']).resize((645,860)),(297,292))
    block(draw,'观察指引\n'+observation_guidance(station),(65,1172,1110,280),32)
    block(draw,'观察问题\n'+station['question'],(65,1462,1110,128),32)
    credits=credit(station['panorama'])
    if station.get('detail'):credits+='\n特写'+credit(station['detail'])
    block(draw,credits,(65,1600,1110,137),18)
    # 1240 x 1754 pixels at 150 dpi -> one printable A4 page (within 0.4 mm).
    page.save(target,'PDF',resolution=150)


def export_video(api,p,station,script,folder,target):
    timing=timing_for(p);intro_seconds=timing['intro'];total=sum(timing.values())
    ready=[]
    for shot in p['shots']:
        if not shot.get('rendered') or any(shot.get(k) for k in ('image_stale','clip_stale','rendered_stale')):
            raise UserError('请先在水墨故事中完成并确认各个故事片段')
        ready.append(api.store.asset(p['id'],shot['rendered']))
    if not ready: raise UserError('请先制作水墨故事片段，或导入已有水墨镜头')
    lengths=[api.providers.duration(path) for path in ready]
    if sum(lengths)>intro_seconds+.05: raise UserError(f'历史引入镜头需不超过{intro_seconds}秒，请减少镜头或调整时长；不会自动截掉对白')
    storybase=folder/(target.stem+'-story-base.mp4')
    api.providers.assemble(ready,None,folder,storybase)
    overlay=Image.new('RGBA',(720,1280),(0,0,0,0));draw=ImageDraw.Draw(overlay)
    draw.rectangle((0,1000,720,1280),fill=(250,248,242,245))
    block(draw,script['intro'],(30,1020,660,240),29)
    overlay_path=folder/(target.stem+'-story-text.png');overlay.save(overlay_path)
    story=folder/(target.stem+'-story.mp4')
    checked_ffmpeg(['-i',str(storybase),'-i',str(overlay_path),'-filter_complex',
        f'[0:v]tpad=stop_mode=clone:stop_duration={intro_seconds},trim=duration={intro_seconds},setpts=PTS-STARTPTS[v];[v][1:v]overlay=0:0[out]',
        '-map','[out]','-map','0:a:0','-af',f'apad,atrim=duration={intro_seconds}','-t',str(intro_seconds),
        '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-r','30','-c:a','aac',str(story)])
    chapters=[dict(kind='story',duration=intro_seconds,video=story.name)]
    slots=observation_slots(timing['location'],bool(station.get('detail')))
    segments=[story]
    for slot,duration in slots+[('task',timing['task'])]:
        key='detail' if slot=='task' and station.get('detail') else 'panorama' if slot=='task' else slot
        text=observation_guidance(station)+'\n'+station['question'] if slot=='task' else script['location']
        frame=folder/(target.stem+'-'+slot+'.png')
        photo_frame(api.store,p['id'],station,key,text).save(frame)
        clip=frame.with_suffix('.mp4')
        checked_ffmpeg(['-loop','1','-i',str(frame),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
            '-t',str(duration),'-c:v','libx264','-preset','veryfast','-tune','stillimage',
            '-pix_fmt','yuv420p','-r','30','-c:a','aac','-shortest',str(clip)])
        segments.append(clip);chapters.append(dict(kind=slot,duration=duration,video=clip.name))
    api.providers.assemble(segments,None,folder,target)
    if abs(api.providers.duration(target)-total)>.15:raise UserError('研学成片时长校验失败，旧导出已保留')
    return chapters


def add_voiceover(api,p,script,target,user):
    """Explicit optional online TTS; never truncates a teacher's spoken text."""
    timing=timing_for(p);total=sum(timing.values())
    inputs,filters=[],[]
    for i,(key,duration) in enumerate(timing.items()):
        voice=target.with_name(target.stem+f'-voice-{key}.mp3')
        api.call(user,'speech',p['id'],lambda key=key,voice=voice:api.providers.speak(script[key],'zh-CN-XiaoxiaoNeural',voice))
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
