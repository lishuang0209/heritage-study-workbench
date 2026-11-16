import copy
import io
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field

from scenarios.ink_drama.domain import UserError, ShotInput, parse_json
from .domain import Strict, Station, Photo, empty_station, invalidate, validate_ready, snapshot
from .media import photo_frame, task_card, export_video
from .templates import CASES, script_from_station


class SaveStation(Strict):
    version: int = Field(ge=0)
    station: Station


class Confirm(Strict):
    version: int = Field(ge=0)
    teacher_verified: bool = False
    same_target_verified: bool = False


class Script(Strict):
    intro: str = Field(min_length=1,max_length=400)
    location: str = Field(min_length=1,max_length=240)
    task: str = Field(min_length=1,max_length=380)


class SaveScript(Script):
    version: int = Field(ge=0)
    station_version: int = Field(ge=0)


class Reuse(Strict):
    source_project: str
    shot_ids: list[str] = Field(min_length=1,max_length=6)
    replace_confirmed: bool = False


class Export(Strict):
    kind: Literal['video','card','both'] = 'both'
    version: int = Field(ge=0)
    narration: bool = False


class TrialRecord(Strict):
    participants: int = Field(ge=1,le=10000)
    found_without_hint: int = Field(ge=0,le=10000)
    preparation_minutes: float = Field(ge=0,le=100000)
    notes: str = Field(default='',max_length=1500)


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
                if not old.get(slot) or old[slot]['image']!=photo['image']:
                    photo['mark']=None
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
                    p.setdefault('heritage_station',empty_station())[slot]=Photo(image=name).model_dump()
                    invalidate(p);api.store.save(p)
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
            raise HTTPException(422,'无法读取照片，请上传有效的JPG、PNG或WEBP') from exc
        return api.public(p)

    @api.router.get('/projects/{pid}/heritage/photos/{slot}/preview')
    def preview_photo(pid:str,slot:Literal['panorama','detail'],user=Depends(api.identity)):
        p=project(pid,user);station=p.get('heritage_station') or empty_station()
        if not station.get(slot):raise HTTPException(404,'请先上传照片')
        def render():
            image=photo_frame(api.store,pid,station,slot,station['instruction']+'\n'+station['question'])
            out=io.BytesIO();image.save(out,'PNG');return out.getvalue()
        return Response(safe(render),media_type='image/png',headers={'Cache-Control':'no-store'})

    @api.router.post('/projects/{pid}/heritage/confirm')
    @api.serialized
    def confirm(pid:str,body:Confirm,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.version)
        safe(lambda:validate_ready(p,api.store))
        if not body.teacher_verified:raise HTTPException(422,'请由老师核对构件说明、实际站位、照片标注和寻找指令后确认')
        if p['heritage_station'].get('detail') and not body.same_target_verified:raise HTTPException(422,'请确认全景和特写标注的是同一处构件')
        p['heritage_confirmed_version']=body.version
        p['heritage_confirmed_snapshot']=copy.deepcopy(p['heritage_station'])
        api.store.save(p);return api.public(p)

    def update_script(p,script):
        previous=p.get('heritage_script') or {}
        p['heritage_script']={**script,'version':previous.get('version',0)+1,
                             'station_version':p.get('heritage_version',0),'confirmed_version':None}
        p['script']=script['intro'];p['story_confirmed']=False
        p['final_stale']=bool(p.get('final'));p['task_card_stale']=bool(p.get('task_card'))
        api.store.save(p)

    @api.router.post('/projects/{pid}/heritage/script-template')
    @api.serialized
    def apply_template(pid:str,user=Depends(api.identity)):
        p=project(pid,user,True)
        update_script(p,script_from_station(p.get('heritage_station') or empty_station()))
        return api.public(p)

    @api.router.put('/projects/{pid}/heritage/script')
    @api.serialized
    def save_script(pid:str,body:SaveScript,user=Depends(api.identity)):
        p=project(pid,user,True);check_version(p,body.station_version)
        if (p.get('heritage_script') or {}).get('version',0)!=body.version:raise HTTPException(409,'脚本已变化，请重新打开')
        update_script(p,body.model_dump(exclude={'version','station_version'}));return api.public(p)

    @api.router.post('/projects/{pid}/heritage/confirm-script')
    @api.serialized
    def confirm_script(pid:str,body:Confirm,user=Depends(api.identity)):
        p=project(pid,user,True);script=p.get('heritage_script')
        if not script or script['version']!=body.version:raise HTTPException(409,'脚本不存在或已变化')
        if script['station_version']!=p.get('heritage_version',0):raise HTTPException(409,'资料已更新，请重新检查并保存脚本')
        if not body.teacher_verified:raise HTTPException(422,'请老师审核三段台词后确认')
        script['confirmed_version']=script['version'];api.store.save(p);return api.public(p)

    def run_script(jid,pid,user):
        try:
            from models.llm_client import LLM
            p=api.store.load(pid);station=p.get('heritage_station') or empty_station()
            prompt=('你为古建研学老师起草30秒短片脚本。只使用老师提供的事实，不补充年代、结构数量、方位或历史结论。'
                    '根据适用年级，用易懂的中文，按故事引入12秒、实拍定位11秒、现场任务7秒安排。'
                    '禁止让AI画面代替实拍构件证据，最后必须指向老师标注的实拍。'
                    '输出JSON，只有intro、location、task三个字符串字段，分别最多400、240、380字。老师资料：'+json.dumps(station,ensure_ascii=False))
            from config import Config
            raw=api.call(user,'text',pid,lambda:LLM().query(prompt,model=Config.LLM_MODEL))
            script=Script.model_validate(parse_json(raw)).model_dump()
            update_script(p,script);api.store.finish(jid)
        except Exception as exc:
            api.store.finish(jid,str(exc)[:500] if isinstance(exc,UserError) else '脚本起草失败，原资料和已生成镜头保留，请检查模型设置后手动重试')

    @api.router.post('/projects/{pid}/heritage/script-ai')
    @api.serialized
    def ai_script(pid:str,user=Depends(api.identity)):
        p=project(pid,user,True)
        if not (p.get('heritage_station') or {}).get('checked_description','').strip():raise HTTPException(422,'请先填写已核对的构件说明')
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
        if sum(s.get('duration',5) for s in selected)>12:raise HTTPException(422,'请选择总时长不超过12秒的故事镜头')
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
        p['final_stale']=bool(p.get('final'));p['task_card_stale']=bool(p.get('task_card'))
        api.store.save(p);return api.public(p)

    def ready(p):
        station=validate_ready(p,api.store)
        if p.get('heritage_confirmed_version')!=p.get('heritage_version',0):raise UserError('请老师先确认当前照片、标注和任务资料')
        script=p.get('heritage_script')
        if not script or script.get('station_version')!=p.get('heritage_version',0) or script.get('confirmed_version')!=script['version']:
            raise UserError('请老师先审核当前版本的研学脚本')
        return station,script

    def run_export(jid,pid,user,kind,narration=False):
        try:
            p=api.store.load(pid);station,script=ready(p);stamp=snapshot(p);folder=api.store.folder(pid)
            stem=uuid.uuid4().hex;updates={};chapters=None
            if kind in ('video','both'):
                target=folder/(stem+'-study.mp4');chapters=export_video(api,p,station,script,folder,target)
                if narration:
                    from .media import add_voiceover
                    add_voiceover(api,p,script,target,user)
                updates.update(final=target.name,final_stale=False)
            if kind in ('card','both'):
                target=folder/(stem+'-task-card.pdf');task_card(api.store,pid,station,target)
                updates.update(task_card=target.name,task_card_stale=False)
            with api.mutation_lock:
                current=api.store.load(pid)
                if snapshot(current)!=stamp:raise UserError('导出期间资料变化，未替换旧导出，请重新确认后重试')
                current.update(updates);current['heritage_export_stamp']=stamp
                if 'final' in updates:current['heritage_audio_policy']='narration' if narration else 'story_original_and_photo_captions'
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
        p=project(pid,user,True);check_version(p,body.version);safe(lambda:ready(p))
        jid=api.store.enqueue(pid,user['id'],'heritage-export');api.pool.submit(run_export,jid,pid,user,body.kind,body.narration)
        return api.public(api.store.load(pid))

    @api.router.put('/projects/{pid}/heritage/trial')
    @api.serialized
    def trial(pid:str,body:TrialRecord,user=Depends(api.identity)):
        p=project(pid,user,True)
        if body.found_without_hint>body.participants:raise HTTPException(422,'独立找到人数不能大于参与人数')
        p['heritage_trial']=body.model_dump();api.store.save(p);return api.public(p)
