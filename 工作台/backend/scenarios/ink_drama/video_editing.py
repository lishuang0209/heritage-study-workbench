"""Video-to-video candidates. One submission, retained source audio, explicit adoption."""
import json
import time
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .domain import UserError
from .styles import video_style_lock
from .media_format import generation_options, fit_filter, format_for

MODEL = 'wan2.7-videoedit'


def ensure_available():
    from config import Config
    if not Config.DASHSCOPE_API_KEY:
        raise UserError('请先在“模型与 API”中配置阿里云百炼密钥，再生成视频调整候选')


def edit_video(source, instruction, target, project):
    # Keep this scenario-specific integration separate from the shared video facade:
    # video editing needs audio_setting=origin and must never retry task submission.
    import requests
    from dashscope import VideoSynthesis
    from models.video_dashscope import DashscopeVideoClient
    from config import Config
    from .providers import Providers, checked_ffmpeg

    client = DashscopeVideoClient()
    if not client.api_key:
        raise UserError('请先在“模型与 API”中配置阿里云百炼密钥，再生成视频调整候选')
    prompt = ('编辑输入视频，只修改用户明确指定的局部动作：' + instruction +
              '\n本次局部修改优先于原视频中对应动作；其余动作、人物身份、服饰、场景、时长、运镜、构图和节奏尽量保持原样。'
              '不额外切镜，不添加人物或道具。不重新演绎整段剧情。保留原有声音，不新增配音或音乐。\n' +
              video_style_lock(project) + '\n沿用输入视频的二维笔墨与平面色块；手部、面部、衣料及道具不补出摄影写实细节。')
    record = target.with_suffix('.request.json')
    snapshot = dict(model=MODEL, source=source.name, instruction=instruction, prompt=prompt,
                    audio_policy='source_track', state='submitting')
    def save():
        record.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    save()
    # file:// is handled by the installed DashScope SDK's media upload support.
    response = VideoSynthesis.async_call(
        api_key=client.api_key, model=MODEL, prompt=prompt,
        media=[{'type': 'video', 'url': client._to_media_url(str(source))}],
        resolution='720P', prompt_extend=False, watermark=False, audio_setting='origin')
    if response.status_code != 200:
        raise UserError('视频编辑提交失败，请检查百炼模型权限、接口区域与额度；原视频已保留')
    task_id = client._extract_task_id(response)
    if not task_id:
        raise UserError('视频编辑未返回任务编号，结果未知；请先核查服务商任务，勿重复提交')
    snapshot.update(task_id=task_id, state='submitted'); save()
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        result = VideoSynthesis.fetch(task=task_id, api_key=client.api_key)
        if result.status_code != 200:
            raise UserError('视频编辑查询失败，任务可能仍在运行；请先核查服务商任务，勿重复提交')
        state = client._extract_task_status(result)
        if state == 'SUCCEEDED':
            url = client._extract_video_url(result)
            if not url:
                raise UserError('视频编辑已结束但未返回视频，请核查服务商任务')
            break
        if state not in {'PENDING', 'RUNNING'}:
            snapshot.update(state='failed'); save()
            raise UserError('视频编辑任务失败，原视频和调整要求已保留，请核查服务商任务')
        time.sleep(10)
    else:
        raise UserError('视频编辑等待超时，任务结果未知；请核查服务商任务后再操作')
    raw = target.with_name(target.stem + '-edit-raw.mp4')
    with requests.get(url, stream=True, timeout=120, proxies=Config.requests_proxies('dashscope')) as response:
        response.raise_for_status()
        with raw.open('wb') as output:
            for chunk in response.iter_content(1024 * 1024):
                output.write(chunk)
    media = Providers()
    if abs(media.duration(raw) - media.duration(source)) > .3:
        raise UserError('编辑结果时长与底稿不一致，未采用候选；原视频已保留')
    # Preserve the exact selected source's audio independently of model compliance.
    args = ['-i', str(raw), '-i', str(source), '-map', '0:v:0', '-c:v', 'copy']
    if generation_options(project):
        args = ['-i', str(raw), '-i', str(source), '-map', '0:v:0', '-vf', fit_filter('16:9'),
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p']
    args += ['-map', '1:a:0', '-c:a', 'copy'] if media.has_audio(source) else ['-an']
    checked_ffmpeg([*args, '-movflags', '+faststart', str(target)])
    snapshot.update(state='completed', media_format=format_for(project)); save()


def install(api):
    class EditInput(BaseModel):
        video: str
        revision: int
        instruction: str = Field(min_length=1, max_length=1000)

    class Choice(BaseModel):
        candidate_id: str

    def stamp(p, shot):
        return [shot['revision'], shot.get('clip'), shot.get('rendered'), shot.get('image'),
                shot.get('image_stale'), p.get('spatial_version'),
                (p.get('baseline') or {}).get('version'), p.get('creative_settings')]

    def archive(shot, name):
        for key in ('clip_versions', 'video_edit_versions'):
            if name and name not in shot.setdefault(key, []):
                shot[key].append(name)

    def run(jid, pid, user, sid, request, source_stamp):
        try:
            p = api.store.load(pid); shot = api.shot_at(p, sid)
            target = api.store.folder(pid) / (uuid.uuid4().hex + '.mp4')
            source = api.store.asset(pid, request['video'])
            api.call(user, 'video', pid, lambda: edit_video(source, request['instruction'], target, p))
            if not target.is_file():
                raise UserError('视频编辑未保存候选文件，原视频已保留')
            if abs(api.providers.duration(target) - api.providers.duration(source)) > .3:
                raise UserError('候选时长与底稿不一致，原视频已保留')
            with api.mutation_lock:
                p = api.store.load(pid); shot = api.shot_at(p, sid)
                previous = shot.get('video_proposal')
                if previous: archive(shot, previous['video'])
                shot['video_proposal'] = dict(id=uuid.uuid4().hex, video=target.name,
                    source=request['video'], instruction=request['instruction'], stamp=source_stamp)
                api.store.save(p)
            api.store.finish(jid)
        except Exception as exc:
            api.store.finish(jid, str(exc)[:600] if isinstance(exc, UserError) else
                '视频调整失败，原视频与要求已保留。请核查服务商任务后再手动重试')
            api.LOG.warning('Video edit failed: job=%s type=%s', jid, type(exc).__name__)

    @api.router.post('/projects/{pid}/shots/{sid}/preview-video')
    @api.serialized
    def preview(pid: str, sid: str, body: EditInput, user=Depends(api.identity)):
        p = api.access(pid, user, True); shot = api.shot_at(p, sid)
        if body.revision != shot['revision']:
            raise HTTPException(409, '镜头已变化，请刷新后重新调整')
        request = body.model_dump(); request['instruction'] = body.instruction.strip()
        if not request['instruction']:
            raise HTTPException(422, '请填写需要调整的局部动作')
        if not any(x['video'] == body.video for x in api.video_history(p, shot)):
            raise HTTPException(422, '请选择本镜头已有的视频')
        source = api.store.asset(pid, body.video)
        if source.stat().st_size > 100 * 1024 * 1024 or not 2 <= api.providers.duration(source) <= 10.3:
            raise HTTPException(422, '视频编辑需要2至10秒、100MB以内的底稿')
        try:
            ensure_available()
        except UserError as exc:
            raise HTTPException(422, str(exc)) from exc
        shot['video_edit_draft'] = request
        api.store.save(p)
        jid = api.store.enqueue(pid, user['id'], 'video-preview')
        api.pool.submit(run, jid, pid, user, sid, request, stamp(p, shot))
        return api.public(api.store.load(pid))

    @api.router.post('/projects/{pid}/shots/{sid}/adopt-video-candidate')
    @api.serialized
    def adopt(pid: str, sid: str, body: Choice, user=Depends(api.identity)):
        p = api.access(pid, user, True); shot = api.shot_at(p, sid)
        proposal = shot.get('video_proposal')
        if not proposal or proposal['id'] != body.candidate_id or proposal['stamp'] != stamp(p, shot):
            raise HTTPException(409, '候选或镜头已变化，请重新生成候选')
        if shot.get('image_stale'):
            raise HTTPException(409, '请先确认当前分镜图片，再采用视频候选')
        if not api.store.asset(pid, proposal['video']).is_file():
            raise HTTPException(422, '候选文件不存在，请重新生成')
        duration = api.providers.duration(api.store.asset(pid, proposal['video']))
        if not 2 <= round(duration) <= 10 or abs(duration - round(duration)) > .3:
            raise HTTPException(422, '候选时长无效，请重新生成')
        for name in (shot.get('clip'),):
            if name and name not in shot.setdefault('clip_versions', []): shot['clip_versions'].append(name)
        if shot.get('rendered') and shot['rendered'] not in shot.setdefault('rendered_versions', []):
            shot['rendered_versions'].append(shot['rendered'])
        archive(shot, proposal['video'])
        shot.update(clip=proposal['video'], rendered=proposal['video'], clip_stale=False,
                    rendered_stale=False, audio_source='historical', media_step='complete',
                    revision=shot['revision'] + 1, duration=round(duration), video_proposal=None, video_edit_draft=None)
        p['final_stale'] = bool(p.get('final'))
        api.store.save(p)
        api.store.event(pid, user['id'], 'adopt_video_candidate', {'shot': sid, 'video': shot['clip']})
        return api.public(p)

    @api.router.post('/projects/{pid}/shots/{sid}/discard-video-candidate')
    @api.serialized
    def discard(pid: str, sid: str, body: Choice, user=Depends(api.identity)):
        p = api.access(pid, user, True); shot = api.shot_at(p, sid)
        proposal = shot.get('video_proposal')
        if not proposal or proposal['id'] != body.candidate_id:
            raise HTTPException(409, '候选已变化，请刷新后重试')
        archive(shot, proposal['video']); shot['video_proposal'] = None
        api.store.save(p)
        return api.public(p)
