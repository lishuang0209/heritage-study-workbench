import copy
import io
import json
import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field

from scenarios.ink_drama.domain import UserError, ShotInput, parse_json
from .domain import Strict, Station, Photo, empty_station, invalidate, validate_ready, snapshot, observation_guidance, validate_detail_link
from .media import photo_frame, task_card, export_video
from .templates import CASES, script_from_station, research_excerpt, HISTORY_PLACEHOLDER
from .photo_credits import recognize, selected_credits, fill_existing
from .detail_crop import crop_detail
from .timing import Timing, timing_for
from .material_import import extract_material, MAX_FILE_BYTES

LOCAL_BAOGUO_PROJECT_ID = '81ba6cf4f7f944ee80467852db0c6c71'

class SaveStation(Strict):
    version: int = Field(ge=0)
    station: Station


class CreditLookup(Strict):
    version: int = Field(ge=0)


class DetailFromMark(Strict):
    version: int = Field(ge=0)


class SaveTiming(Strict):
    version: int = Field(ge=0)
    timing: Timing


class Confirm(Strict):
    timing_version: int = Field(default=0,ge=0)
    version: int = Field(ge=0)
    teacher_verified: bool = False
    same_target_verified: bool = False


class Script(Strict):
    intro: str = Field(min_length=1,max_length=400)
    location: str = Field(min_length=1,max_length=600)
    task: str = Field(min_length=1,max_length=800)


class SaveScript(Script):
    timing_version: int = Field(default=0,ge=0)
    version: int = Field(ge=0)
    station_version: int = Field(ge=0)


class Reuse(Strict):
    source_project: str
    shot_ids: list[str] = Field(min_length=1,max_length=6)
    replace_confirmed: bool = False


class Export(Strict):
    timing_version: int = Field(default=0,ge=0)
    kind: Literal['video','card','both'] = 'both'
    version: int = Field(ge=0)
    narration: bool = False


class TrialRecord(Strict):
    participants: int = Field(ge=1,le=10000)
    found_without_hint: int = Field(ge=0,le=10000)
    preparation_minutes: float = Field(ge=0,le=100000)
    notes: str = Field(default='',max_length=1500)


class GuideChoice(Strict):
    enabled: bool
    version: int = Field(ge=0)


def install(api):
    def project(pid,user,write=False):
        p=api.access(pid,user,write)
        if p.get('project_type')!='heritage':raise HTTPException(422,'该功能仅用于古建研学项目，普通水墨项目保持原流程')
        return p

    def check_version(p, version):
        if p.get('heritage_version',0)!=version:raise HTTPException(409,'讲解站资料已变化，请重新打开后操作')

    def safe(fn):
        try:return fn()
        except UserError as exc:raise HTTPException(422,str(exc)) from exc

    @api.router.get('/heritage/templates')
    def templates(user=Depends(api.identity)):
        return {'templates':CASES}

    @api.router.post('/heritage/templates/{case_id}')
    @api.serialized
    def create_from_template(case_id: str, request: Request, user=Depends(api.identity)):
        case = next((case for case in CASES if case['id'] == case_id), None)
        if case is None:
            raise HTTPException(404, '案例模板不存在')
        if user.get('trial_mode', True) and api.store.ended(user['id']):
            raise HTTPException(403, '试用已结束')
        if case_id == 'baoguo':
            configured_id = os.environ.get('SFA_INK_HERITAGE_BAOGUO_PROJECT_ID', '').strip()
            source_id = configured_id or (LOCAL_BAOGUO_PROJECT_ID if api.local(request) else '')
            if source_id:
                try:
                    source = api.store.load(source_id) if configured_id else api.access(source_id, user)
                except UserError:
                    raise HTTPException(503, '完整保国寺案例暂不可用，请稍后重试') from None
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    source = None
                if source is not None:
                    shots = source.get('shots', [])
                    station = source.get('heritage_station') or {}
                    files = [source.get('final'), source.get('task_card'), (station.get('panorama') or {}).get('image')]
                    files += [shot.get(key) for shot in shots for key in ('image', 'rendered')]
                    if station.get('detail'):
                        files.append(station['detail'].get('image'))
                    try:
                        complete = source.get('project_type') == 'heritage' and bool(shots) and all(
                            name and api.store.asset(source_id, name).is_file() for name in files
                        )
                    except (OSError, UserError):
                        complete = False
                    if not complete:
                        raise HTTPException(503, '完整保国寺案例的资料不齐，请联系负责人')
                    try:
                        return api.public(api.store.clone(source_id, user['id']))
                    except UserError as exc:
                        raise HTTPException(409, str(exc)) from exc
                    except OSError:
                        raise HTTPException(503, '暂时无法复制保国寺案例，请稍后重试') from None
        station = Station.model_validate(case['station']).model_dump()
        p = api.store.create(user['id'], case['title'], '研学故事待老师编辑与确认。')
        p.update(project_type='heritage', heritage_station=station, heritage_version=1)
        api.store.save(p)
        return api.public(p)

    @api.router.put('/projects/{pid}/heritage/guide')
    @api.serialized
    def select_guide(pid:str,body:GuideChoice,user=Depends(api.identity)):
        p=project(pid,user,True)
        if body.version!=p.get('heritage_guide_version',0):raise HTTPException(409,'向导设置已变化，请重新打开后操作')
        from .guide import set_enabled
        changed=safe(lambda:set_enabled(p,body.enabled))
        if changed:
            api.store.save(p);api.store.event(pid,user['id'],'heritage_guide',{'enabled':body.enabled,'model_calls':0})
        return api.public(p)

    @api.router.post('/projects/{pid}/heritage/material/preview')
    async def preview_material(pid:str, version:int, file:UploadFile=File(...), user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,version)
        data=await file.read(MAX_FILE_BYTES+1)
        try:
            result=await run_in_threadpool(extract_material,data,file.filename)
        except UserError as exc:
            raise HTTPException(422,str(exc)) from exc
        # Extraction only prepares a preview; never saves or invalidates a project.
        with api.mutation_lock:
            current=project(pid,user,True);check_version(current,version)
        return result

    @api.router.put('/projects/{pid}/heritage/station')
    @api.serialized
    def save_station(pid:str,body:SaveStation,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.version)
        data=body.station.model_dump();old=p.get('heritage_station') or empty_station()
        for slot in ('panorama','detail'):
            photo=data.get(slot)
            if photo:
                upload=p.get('heritage_uploads',{}).get(photo['image'])
                if not upload or upload['slot']!=slot:raise HTTPException(422,'请先为此讲解站上传对应照片')
                photo['derived_from']=upload.get('derived_from')
                photo['derived_mark']=upload.get('derived_mark')
                if upload.get('derived_from'):
                    if photo['mark']!=upload['mark']:
                        raise HTTPException(422,'自动特写的标注随定位图生成，请修改定位图后重新生成')
                    photo.update(mode='contain',focus_x=.5,focus_y=.5)
                credit=selected_credits(photo['credit_kind'])
                if credit:photo.update(credit)
                if not old.get(slot) or old[slot]['image']!=photo['image']:
                    photo['mark']=upload['mark'] if upload.get('derived_from') else None
        detail=data.get('detail');panorama=data.get('panorama')
        if detail and panorama and detail.get('derived_from')==panorama['image']:
            for key in ('source','author','license','credit_kind'):detail[key]=panorama[key]
        if data!=old:
            p['heritage_station']=data;invalidate(p);api.store.save(p)
        return api.public(p)

    @api.router.post('/projects/{pid}/heritage/photos/{slot}')
    async def upload_photo(pid:str,slot:Literal['panorama','detail'],version:int,file:UploadFile=File(...),user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,version)
        data=await file.read(12*1024*1024+1)
        if len(data)>12*1024*1024:raise HTTPException(422,'请上传12MB以内的实拍照片')
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load();image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((3000,3000))
                if min(image.size)<240:raise HTTPException(422,'照片短边至少需要240像素')
                with api.mutation_lock:
                    p=project(pid,user,True);check_version(p,version)
                    name=uuid.uuid4().hex+'.jpg';image.save(api.store.asset(pid,name),quality=94)
                    p.setdefault('heritage_uploads',{})[name]={'slot':slot,'width':image.width,'height':image.height}
                    p.setdefault('heritage_station',empty_station())[slot]=Photo(image=name,**(recognize(data) or {'credit_kind':'unresolved'})).model_dump()
                    invalidate(p);api.store.save(p)
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
            raise HTTPException(422,'无法读取照片，请上传有效的JPG、PNG或WEBP') from exc
        return api.public(p)

    @api.router.post('/projects/{pid}/heritage/detail-from-mark')
    @api.serialized
    def detail_from_mark(pid:str,body:DetailFromMark,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.version)
        station=p.get('heritage_station') or empty_station();panorama=station.get('panorama')
        if not panorama or not panorama.get('mark'):raise HTTPException(422,'请先上传定位图并标注目标')
        source=api.store.asset(pid,panorama['image'])
        if not source.is_file():raise HTTPException(422,'定位图不存在，请重新上传')
        name=uuid.uuid4().hex+'.jpg';target=api.store.asset(pid,name)
        geometry=safe(lambda:crop_detail(source,panorama['mark'],target))
        credits={key:panorama.get(key,'manual' if key=='credit_kind' else '') for key in ('source','author','license','credit_kind')}
        station['detail']=Photo(image=name,mark=geometry['mark'],derived_from=panorama['image'],derived_mark=panorama['mark'],**credits).model_dump()
        p.setdefault('heritage_uploads',{})[name]={'slot':'detail',**geometry,'derived_from':panorama['image'],'derived_mark':copy.deepcopy(panorama['mark'])}
        p['heritage_station']=station;invalidate(p);api.store.save(p)
        return api.public(p)

    @api.router.post('/projects/{pid}/heritage/photo-credits')
    @api.serialized
    def recover_photo_credits(pid:str,body:CreditLookup,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.version)
        if fill_existing(api.store,p):
            invalidate(p);api.store.save(p)
        return api.public(p)

    @api.router.get('/projects/{pid}/heritage/photos/{slot}/preview')
    def preview_photo(pid:str,slot:Literal['panorama','detail'],user=Depends(api.identity)):
        p=project(pid,user);station=p.get('heritage_station') or empty_station()
        if not station.get(slot):raise HTTPException(404,'请先上传照片')
        def render():
            if slot=='detail':validate_detail_link(p)
            image=photo_frame(api.store,pid,station,slot,observation_guidance(station)+'\n'+station['question'])
            out=io.BytesIO();image.save(out,'PNG');return out.getvalue()
        return Response(safe(render),media_type='image/png',headers={'Cache-Control':'no-store'})

    @api.router.post('/projects/{pid}/heritage/confirm')
    @api.serialized
    def confirm(pid:str,body:Confirm,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.version)
        safe(lambda:validate_ready(p,api.store))
        if not body.teacher_verified:raise HTTPException(422,'请由老师核对研学资料、照片标注与观察指引，确认适合现场使用')
        if p['heritage_station'].get('detail') and not p['heritage_station']['detail'].get('derived_from') and not body.same_target_verified:raise HTTPException(422,'请确认全景和特写标注的是同一处构件')
        p['heritage_confirmed_version']=body.version
        p['heritage_confirmed_snapshot']=copy.deepcopy(p['heritage_station'])
        api.store.save(p);return api.public(p)

    @api.router.put('/projects/{pid}/heritage/timing')
    @api.serialized
    def save_timing(pid:str,body:SaveTiming,user=Depends(api.identity)):
        p=project(pid,user,True)
        if p.get('heritage_timing_version',0)!=body.version:raise HTTPException(409,'时长设置已变化，请重新打开')
        timing=body.timing.model_dump()
        if timing!=timing_for(p):
            p['heritage_timing']=timing;p['heritage_timing_version']=body.version+1
            if p.get('heritage_script'):
                p['heritage_script']['confirmed_version']=None
                p['heritage_script']['timing_version']=p['heritage_timing_version']
            p['final_stale']=bool(p.get('final'));p['task_card_stale']=bool(p.get('task_card'))
            api.store.save(p)
        return api.public(p)

    def update_script(p,script):
        previous=p.get('heritage_script') or {}
        if p.get('shots') and p.get('script') != script['intro']:
            p['heritage_story_stale']=True
            p['storyboard_confirmed']=False
        p['heritage_script']={**script,'version':previous.get('version',0)+1,
                             'station_version':p.get('heritage_version',0),'timing_version':p.get('heritage_timing_version',0),'confirmed_version':None}
        p['script']=script['intro'];p['story_confirmed']=False
        p['final_stale']=bool(p.get('final'));p['task_card_stale']=bool(p.get('task_card'))
        api.store.save(p)

    @api.router.post('/projects/{pid}/heritage/script-template')
    @api.serialized
    def apply_template(pid:str,user=Depends(api.identity)):
        p=project(pid,user,True)
        draft=safe(lambda:script_from_station(p.get('heritage_station') or empty_station(),timing_for(p)))
        try:Script.model_validate(draft)
        except ValueError:raise HTTPException(422,'研学资料或观察指引过长，请精简后起草研学脚本；原脚本已保留')
        update_script(p,draft)
        return api.public(p)

    @api.router.put('/projects/{pid}/heritage/script')
    @api.serialized
    def save_script(pid:str,body:SaveScript,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.station_version)
        if (p.get('heritage_script') or {}).get('version',0)!=body.version:raise HTTPException(409,'脚本已变化，请重新打开')
        if p.get('heritage_timing_version',0)!=body.timing_version:raise HTTPException(409,'时长设置已变化，请重新打开后保存脚本')
        update_script(p,body.model_dump(exclude={'version','station_version','timing_version'}));return api.public(p)

    @api.router.post('/projects/{pid}/heritage/confirm-script')
    @api.serialized
    def confirm_script(pid:str,body:Confirm,user=Depends(api.identity)):
        p=project(pid,user,True);script=p.get('heritage_script')
        if not script or script['version']!=body.version:raise HTTPException(409,'脚本不存在或已变化')
        if script['station_version']!=p.get('heritage_version',0):raise HTTPException(409,'资料已更新，请重新检查并保存脚本')
        if p.get('heritage_timing_version',0)!=body.timing_version:raise HTTPException(409,'时长已变化，请按新时长核对脚本')
        if script.get('timing_version',0)!=p.get('heritage_timing_version',0):raise HTTPException(409,'脚本对应的时长已过期，请保存脚本后重新核对')
        if HISTORY_PLACEHOLDER in script['intro']:raise HTTPException(422,'请补充地方历史资料并完善历史引入，再确认脚本')
        if not body.teacher_verified:raise HTTPException(422,'请老师审核三段台词后确认')
        script['confirmed_version']=script['version'];api.store.save(p);return api.public(p)

    def run_script(jid,pid,user):
        try:
            from models.llm_client import LLM
            p=api.store.load(pid);station=p.get('heritage_station') or empty_station()
            timing=timing_for(p);duration=sum(timing.values());station_version=p.get('heritage_version',0);timing_version=p.get('heritage_timing_version',0);script_version=(p.get('heritage_script') or {}).get('version',0)
            prompt=(f'你为古建研学老师起草{duration}秒短片脚本。只使用老师提供的事实，不补充年代、结构数量、方位或历史结论。'
                    f'根据适用年级，用易懂的中文，按历史引入{timing["intro"]}秒、实物观察{timing["location"]}秒、现场任务{timing["task"]}秒安排。'
                    '根据每段时间控制文字量，口播按每秒约3至4字估算。历史段是地方历史讲解，不是固定两句开场。'
                    'intro按资料已有内容讲清寺名沿革、重建年代、建筑价值、修缮与保护，再自然引出构件；没有资料的主题跳过。'
                    '历史段达到30秒且资料有多条事实时，应展开多个历史节点，不能只保留一句年代加一句寻找指令；时长较短时保留关键事实。'
                    '不虚构历史人物对话、传说或未提供的年代，不将后期修缮构件一概当作始建时原构。'
                    'location结合构件特点与观察指引，task给出一个可执行任务和观察问题。'
                    '资料来源链接、现场核对备注与待确认事项不写进学生台词；资料有缺口时明确留待老师补充。'
                    '禁止让AI画面代替实拍构件证据，最后必须指向老师标注的实拍。'
                    '输出JSON，只有intro、location、task三个字符串字段，分别最多400、240、380字。老师资料：'+json.dumps(station,ensure_ascii=False))
            from config import Config
            raw=api.call(user,'text',pid,lambda:LLM().query(prompt,model=Config.LLM_MODEL))
            script=Script.model_validate(parse_json(raw)).model_dump()
            with api.mutation_lock:
                current=api.store.load(pid)
                if (current.get('heritage_version',0)!=station_version or current.get('heritage_timing_version',0)!=timing_version or (current.get('heritage_script') or {}).get('version',0)!=script_version):raise UserError('起草期间资料、时长或脚本已变化，未覆盖当前内容，请核对后重新起草')
                update_script(current,script)
            api.store.finish(jid)
        except Exception as exc:
            api.store.finish(jid,str(exc)[:500] if isinstance(exc,UserError) else '脚本起草失败，原资料和已生成镜头保留，请检查模型设置后手动重试')

    @api.router.post('/projects/{pid}/heritage/script-ai')
    @api.serialized
    def ai_script(pid:str,user=Depends(api.identity)):
        p=project(pid,user,True)
        if not (p.get('heritage_station') or {}).get('checked_description','').strip():raise HTTPException(422,'请先填写研学资料')
        if not research_excerpt(p['heritage_station']['checked_description'])[0]:raise HTTPException(422,'研学资料还缺少地方历史背景，请先补充一条已核对事实；本次未调用模型')
        jid=api.store.enqueue(pid,user['id'],'heritage-script');api.pool.submit(run_script,jid,pid,user)
        return api.public(api.store.load(pid))

    @api.router.post('/projects/{pid}/heritage/reuse-story')
    @api.serialized
    def reuse(pid:str,body:Reuse,user=Depends(api.identity)):
        p=project(pid,user,True);source=api.access(body.source_project,user)
        if pid==source['id'] or len(body.shot_ids)!=len(set(body.shot_ids)):raise HTTPException(422,'请选择其他项目中不同的镜头')
        if p['shots'] and not body.replace_confirmed:raise HTTPException(409,'已有故事镜头，请确认替换；原文件仍保留')
        selected=[s for s in source['shots'] if s['id'] in body.shot_ids]
        if len(selected)!=len(body.shot_ids):raise HTTPException(422,'选择的源镜头不存在')
        intro_seconds=timing_for(p)['intro']
        if sum(s.get('duration',5) for s in selected)>intro_seconds:raise HTTPException(422,f'请选择总时长不超过{intro_seconds}秒的故事镜头')
        for s in selected:
            if not s.get('rendered') or any(s.get(k) for k in ('image_stale','clip_stale','rendered_stale')):
                raise HTTPException(422,'所选镜头尚未完成确认或视频处理')
        mapping={}
        import shutil
        def copy_asset(name):
            if not name:return None
            if name not in mapping:
                path=api.store.asset(source['id'],name)
                if not path.is_file():raise HTTPException(422,'源素材文件不存在，请选择其他镜头')
                mapping[name]=uuid.uuid4().hex+path.suffix;shutil.copy2(path,api.store.asset(pid,mapping[name]))
            return mapping[name]
        shots=[]
        for s in selected:
            shot={key:copy.deepcopy(s.get(key)) for key in ShotInput.model_fields}
            shot.update(id='s'+uuid.uuid4().hex,revision=1,image=copy_asset(s.get('image')),
                        clip=copy_asset(s.get('clip')),rendered=copy_asset(s['rendered']),
                        image_versions=[],clip_versions=[],image_stale=False,clip_stale=False,rendered_stale=False,
                        candidate=None,differences=[],audio_source=s.get('audio_source'),media_step='complete')
            shots.append(shot)
        settings=copy.deepcopy(source.get('creative_settings'))
        if settings:
            for group in ('characters','scenes','props'):
                for item in settings[group]:
                    item['image']=copy_asset(item.get('image'));item['views']={}
        p.update(shots=shots,characters=copy.deepcopy(source['characters']),creative_settings=settings,
                 baseline=None,storyboard_confirmed=True,story_confirmed=True)
        p.update(heritage_story_source=p['script'],heritage_story_stale=False)
        p['final_stale']=bool(p.get('final'));p['task_card_stale']=bool(p.get('task_card'))
        api.store.save(p);return api.public(p)

    def ready(p):
        station=validate_ready(p,api.store)
        if p.get('heritage_confirmed_version')!=p.get('heritage_version',0):raise UserError('请老师先确认当前照片、标注和任务资料')
        script=p.get('heritage_script')
        if not script or script.get('station_version')!=p.get('heritage_version',0) or script.get('confirmed_version')!=script['version'] or script.get('timing_version',0)!=p.get('heritage_timing_version',0):
            raise UserError('请老师先审核当前版本的研学脚本')
        return station,script

    def run_export(jid,pid,user,kind,narration=False):
        try:
            from .narration import profile
            p=api.store.load(pid);station,script=ready(p);stamp=snapshot(p);folder=api.store.folder(pid)
            voice_profile=profile(p)
            stem=uuid.uuid4().hex;updates={};chapters=None
            if kind in ('video','both'):
                target=folder/(stem+'-study.mp4');chapters=export_video(api,p,station,script,folder,target,**({'replace_narration':True} if narration else {}))
                if narration:
                    from .media import add_voiceover
                    add_voiceover(api,p,script,target,user)
                from scenarios.ink_drama.media_format import format_for
                updates.update(final=target.name,final_stale=False,final_media_format=format_for(p))
            if kind in ('card','both'):
                target=folder/(stem+'-task-card.pdf');task_card(api.store,pid,station,target)
                updates.update(task_card=target.name,task_card_stale=False)
            with api.mutation_lock:
                current=api.store.load(pid)
                if snapshot(current)!=stamp:raise UserError('导出期间资料变化，未替换旧导出，请重新确认后重试')
                if narration and profile(current)!=voice_profile:raise UserError('导出期间讲解音色变化，旧导出已保留，请重新导出')
                current.update(updates);current['heritage_export_stamp']=stamp
                if 'final' in updates:current['heritage_audio_policy']='narration' if narration else 'story_original_and_photo_captions'
                if 'final' in updates:current['heritage_export_voice']=voice_profile if narration else None
                if chapters:current['heritage_chapters']=chapters
                if 'final' in updates:current.setdefault('final_versions',[]).append(updates['final'])
                current.setdefault('heritage_exports',[]).append({'stamp':stamp,'station_version':current['heritage_version'],**updates})
                api.store.save(current)
            api.store.finish(jid)
        except Exception as exc:
            api.store.finish(jid,str(exc)[:500] if isinstance(exc,UserError) else '导出失败，已确认资料、镜头和旧导出均保留，可手动重试')
            api.LOG.warning('Heritage export failed: job=%s type=%s',jid,type(exc).__name__)

    @api.router.post('/projects/{pid}/heritage/export')
    @api.serialized
    def export(pid:str,body:Export,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.version)
        if body.timing_version!=p.get('heritage_timing_version',0):raise HTTPException(409,'时长已变化，请重新打开后导出')
        safe(lambda:ready(p))
        jid=api.store.enqueue(pid,user['id'],'heritage-export');api.pool.submit(run_export,jid,pid,user,body.kind,body.narration)
        return api.public(api.store.load(pid))

    @api.router.put('/projects/{pid}/heritage/trial')
    @api.serialized
    def trial(pid:str,body:TrialRecord,user=Depends(api.identity)):
        p=project(pid,user,True)
        if body.found_without_hint>body.participants:raise HTTPException(422,'独立找到人数不能大于参与人数')
        p['heritage_trial']=body.model_dump();api.store.save(p);return api.public(p)
