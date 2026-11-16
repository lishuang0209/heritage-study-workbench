"""Ink demo domain. Files remain private; no provider calls in this module."""
from __future__ import annotations

import copy
import json
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STYLE = '淡彩水墨，低饱和配色，留白，保留自然笔触与宣纸质感'
NEGATIVE = '厚涂油画、磨皮、照片写实、高饱和、3D CG、Q版、赛璐璐平涂、强烈轮廓黑边、文字、水印'
TAGS = {'泼墨', '枯笔飞白', '工笔细线条', '淡墨晕染', '焦墨重墨', '水墨速写', '简笔写意'}
ALIASES = {'枯笔': '枯笔飞白', '飞白': '枯笔飞白', '浅墨晕染': '淡墨晕染', '工笔线条': '工笔细线条', '速写水墨': '水墨速写'}


class UserError(ValueError):
    """Safe, user-facing domain error; never include provider responses."""


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Character(Strict):
    character_id: str | None = None
    desc: str = Field(min_length=1, max_length=1200)
    visibility: Literal['clear', 'partial', 'unclear']
    match_status: Literal['consistent', 'conflict', 'uncertain']


class Scene(Strict):
    description: str = Field(max_length=2000)
    light_direction: str = Field(max_length=100)


class Camera(Strict):
    shot_size: Literal['特写', '近景', '中景', '全景', '远景', 'uncertain']
    angle: Literal['平视', '俯拍', '仰拍', 'uncertain']
    composition: str = Field(max_length=1000)


class InkStyle(Strict):
    techniques: list[str] = Field(max_length=7)
    whitespace: Literal['少', '中', '多', 'uncertain']
    bleed_strength: Literal['无', '弱', '中', '强', 'uncertain']
    paper_texture: Literal['可见', '未见', 'uncertain']
    palette: list[Literal['低饱和赭石', '青灰冷调', '素墨黑白', '其他', 'uncertain']] = Field(max_length=5)


class Caption(Strict):
    characters: list[Character] = Field(max_length=2)
    scene: Scene
    camera: Camera
    ink_style: InkStyle
    uncertainties: list[str] = Field(max_length=20)


def parse_json(raw):
    if not isinstance(raw, str):
        raise UserError('模型未返回文本 JSON，请更换描述或手动重试')
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip()).strip()
    return json.loads(text)


def caption(raw, allowed_ids=()):
    value = Caption.model_validate(parse_json(raw) if isinstance(raw, str) else raw).model_dump()
    normalized = []
    for tag in value['ink_style']['techniques']:
        standard = ALIASES.get(tag, tag)
        if standard in TAGS:
            if standard not in normalized:
                normalized.append(standard)
        else:
            value['uncertainties'].append('未采用词表外技法：' + tag[:80])
    value['ink_style']['techniques'] = normalized
    seen = set()
    for char in value['characters']:
        cid = char['character_id']
        if cid not in allowed_ids or cid in seen or char['visibility'] == 'unclear':
            char['character_id'] = None
            char['match_status'] = 'uncertain'
        else:
            seen.add(cid)
    return value


class Dialogue(Strict):
    character_id: str
    text: str = Field(min_length=1, max_length=300)


class ShotInput(Strict):
    duration: int = Field(default=5, ge=2, le=15, strict=True)
    content: str = Field(min_length=1, max_length=3000)
    scene: str = Field(max_length=2000)
    camera: str = Field(max_length=1000)
    motion: str = Field(max_length=6000)
    scene_id: str | None = None
    prop_ids: list[str] = Field(default_factory=list, max_length=20)
    character_ids: list[str] = Field(max_length=2)
    dialogues: list[Dialogue] = Field(max_length=8)


class Cast(Strict):
    id: str = Field(pattern=r'^c[12]$')
    name: str = Field(min_length=1, max_length=40)
    desc: str = Field(min_length=1, max_length=1500)


class Board(Strict):
    characters: list[Cast] = Field(max_length=2)
    shots: list[ShotInput] = Field(min_length=1, max_length=30)


def board(raw):
    data = Board.model_validate(parse_json(raw)).model_dump()
    ids = [c['id'] for c in data['characters']]
    if len(ids) != len(set(ids)):
        raise UserError('角色 ID 重复')
    for i, shot in enumerate(data['shots']):
        if len(set(shot['character_ids'])) != len(shot['character_ids']):
            raise UserError('镜头角色 ID 重复')
        if not set(shot['character_ids']) <= set(ids):
            raise UserError('镜头包含未定义角色')
        if any(d['character_id'] not in shot['character_ids'] for d in shot['dialogues']):
            raise UserError('台词角色必须出现在镜头中')
        shot.update(id=f's{i+1}', revision=1, image=None, image_versions=[], image_stale=False,
                    clip=None, clip_versions=[], clip_stale=False, rendered=None,
                    rendered_stale=False, candidate=None, candidate_image=None, differences=[])
    return data


def invalidate(p, shot, image=True, reason="镜头内容已调整，请检查图片是否仍适用"):
    if image:
        shot['image_stale'] = bool(shot.get('image'))
        shot['image_stale_reason'] = reason if shot['image_stale'] else None
        shot['candidate'] = None
        shot['candidate_image'] = None
    shot['clip_stale'] = bool(shot.get('clip'))
    shot['rendered_stale'] = bool(shot.get('rendered'))
    p['final_stale'] = bool(p.get('final'))


def framing_constraint(shot):
    """Translate the requested camera scale into explicit cropping, not asset layout."""
    import re
    camera = shot.get('camera', '')
    match = re.search(r'大特写|特写|近景|中近景|中景|全景|远景', camera)
    if not match:
        match = re.search(r'大特写|特写|近景|中近景|中景|全景|远景', shot.get('content', ''))
    scale = match.group() if match else ''
    rules = {
        '大特写': '只展示指定主体的局部细节，局部占据画面主体，不退回人物全身或完整场景。',
        '特写': '按画面内容指定的人脸、手部或道具局部取景，局部占据画面主体；不得为展示完整人物或建筑而拉远。',
        '近景': '聚焦指定主体的上半身，以胸部或腰部以上取景，主体占据主要画幅；不出现主体全身、脚部或完整台阶。',
        '中近景': '以指定主体腰部以上取景，不展示全身；环境仅作局部背景。',
        '中景': '默认以指定人物腰部以上取景，头部与上身占据主要画幅；明确要求膝部以上时按该要求。脚部在画框外，不展示全身。手部和所持道具安排在取景范围内，不为完整建筑扩大取景。',
        '全景': '完整展示人物与必要的周围空间，保持人物可辨。',
        '远景': '以环境空间为主，人物在画面中占比较小。',
    }
    return ('取景范围硬约束：' + scale + '。' + rules.get(scale, '严格按本镜构图取景。')
        + '本镜明确构图优先于景别通用范围：' + camera + '。若指定腰部以上或胸部以上，严格在该处裁切，不扩大到膝部或全身。'
        + '以本镜画面内容确定主体。出场人物列表只是身份索引，不要求每个人完整入镜；'
          '明确写为手臂、背影、虚焦前景的配角只展示对应局部，不升级为双人全景。'
          '人物三视图、场景全景图和画风样张仅提供身份、环境与笔墨依据，不继承其景别、人物大小或布局。'
          '场景和道具允许在画框外，不为展示全部素材而拉远镜头。中景或近景仅展示主体附近局部门柱、门框或环境；场景素材中的完整屋顶、台阶不要求入镜。')


def frame_prompt(p, shot):
    from .background import background_context
    from .creative import settings_context
    from .styles import image_style, negative_style, profile_for
    from .spatial import spatial_prompt
    context = settings_context(p, shot)
    if p.get('creative_settings'):
        chars = [c for c in p['creative_settings']['characters'] if c['id'] in shot['character_ids']]
        style = image_style(p)
    elif not p.get('baseline'):
        chars = [c for c in p.get('characters', []) if c['id'] in shot['character_ids']]
        style = image_style(p)
    else:
        chars = [c for c in p['baseline']['characters'] if c['character_id'] in shot['character_ids']]
        style = image_style(p)
        if not profile_for(p):
            style += '\n已确认水墨特征：' + json.dumps(p['baseline']['ink_style'], ensure_ascii=False)
    # Do not serialize image history/views: those contain previous style descriptions.
    chars = [{k: c[k] for k in ('id', 'character_id', 'name', 'desc') if k in c} for c in chars]
    return '\n'.join([spatial_prompt(p, shot), framing_constraint(shot), background_context(p), context, '静态首帧（最高优先级）：' + shot['content'],
                      '严格绘制动作开始前的站位和姿势，不提前完成后续走动、递接或转身。参考人物图只用于外貌和服饰，不继承其画风、笔触、明暗塑形或姿势。',
                      style, '首帧画面内容：' + shot['content'], '场景：' + shot['scene'],
                      '镜头构图：' + shot['camera'],
                      '只绘制首帧描述指定的一幅静态起始画面，不推演后续动作，不绘制连续多格。',
                      '人物：' + (json.dumps(chars, ensure_ascii=False) if chars else '无人景物，不要添加人物'),
                      '保持已确认角色的面容、服饰、发饰。发型属于固定身份特征：发髻数量、位置、轮廓、头发收束或披散方式、发绳配饰与角色设定一致。侧身、背身和远景只改变可见角度，不重新设计发型；画风可简化笔触，但不能改变发髻结构。不将参考图的构图复制到本镜头。',
                      '参考图只提供身份、服饰和场景依据；笔墨材质以当前选定画风为准。',
                      '避免：' + negative_style(p), framing_constraint(shot), spatial_prompt(p, shot)])


def image_edit_prompt(p, shot):
    # Always include the full current form; changed fields only indicate edit priority.
    labels = {'content': '画面内容', 'scene': '场景', 'camera': '构图', 'motion': '动作与姿势'}
    keys = shot.get('pending_image_edits') or ['motion', 'scene', 'camera']
    instructions = [f'{label}：{shot.get(key, "")}' for key, label in labels.items()]
    focus = '、'.join(label for key, label in labels.items() if key in keys)
    if 'character_ids' in keys:
        names = [c['name'] for c in p['characters'] if c['id'] in shot['character_ids']]
        instructions.append('出场人物：' + ('、'.join(names) if names else '无人；移除画中人物'))
    return '\n'.join([
        '编辑所附的当前分镜图，按以下要求实际改变画面，不要返回原图或只微调颜色。',
        '本次重点调整：' + focus,
        *instructions,
        '以上是当前完整要求，均需满足；如描述有冲突，本次重点调整项优先。',
        '动作修改时重画相关身体朝向、手臂、手指和道具位置，让动作在单幅图片中清楚可见。',
        '新要求优先于原图的动作与构图。保持未要求修改的人物面容、服装、画风和其他区域。',
        '只输出一张竖屏9:16画面，不添加文字、水印或多格分镜。',
        '避免：' + NEGATIVE,
    ])


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, owner TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project TEXT, owner TEXT,
                    action TEXT, state TEXT, error TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, owner TEXT, kind TEXT,
                    project TEXT, state TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, project TEXT,
                    owner TEXT, kind TEXT, payload TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS trials(owner TEXT PRIMARY KEY, ended REAL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'ink.sqlite3', timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET state='interrupted',error='服务已重启；先核对服务商记录，再手动重试，避免重复计费' WHERE state='running'")

    def load(self, pid):
        with self.db() as db:
            row = db.execute('SELECT data FROM projects WHERE id=?', (pid,)).fetchone()
        if not row:
            raise UserError('项目不存在')
        return json.loads(row['data'])

    def list(self):
        with self.db() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM projects ORDER BY rowid DESC')]

    def save(self, p):
        p['updated_at'] = time.time()
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO projects VALUES(?,?,?)',
                       (p['id'], p['owner'], json.dumps(p, ensure_ascii=False)))

    def create(self, owner, title, script):
        p = dict(id=uuid.uuid4().hex, owner=owner, title=title, script=script,
                 created_at=time.time(), characters=[], shots=[], baseline=None,
                 baseline_history=[], final=None, final_versions=[], final_stale=False,
                 feedback=None, music=None, music_credit=None)
        self.save(p)
        self.event(p['id'], owner, 'create')
        return p

    def folder(self, pid):
        if not re.fullmatch(r'[a-f0-9]{32}', pid):
            raise UserError('项目 ID 无效')
        folder = self.root / 'assets' / pid
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def asset(self, pid, filename):
        folder = self.folder(pid).resolve()
        path = (folder / filename).resolve()
        if not path.is_relative_to(folder) or path == folder:
            raise UserError('素材路径无效')
        return path

    def busy(self, pid):
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM jobs WHERE project=? AND state='running'", (pid,)).fetchone())

    def enqueue(self, pid, owner, action):
        jid = uuid.uuid4().hex
        with self.db() as db:
            if db.execute("SELECT 1 FROM jobs WHERE project=? AND state='running'", (pid,)).fetchone():
                raise UserError('该项目正在处理，请等待完成')
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', (jid, pid, owner, action, 'running', '', time.time()))
        return jid

    def finish(self, jid, error=None):
        with self.db() as db:
            db.execute('UPDATE jobs SET state=?,error=? WHERE id=?', ('failed' if error else 'completed', error or '', jid))

    def jobs(self, pid):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM jobs WHERE project=? ORDER BY created DESC LIMIT 12', (pid,))]

    def event(self, pid, owner, kind, payload=None):
        with self.db() as db:
            db.execute('INSERT INTO events(project,owner,kind,payload,created) VALUES(?,?,?,?,?)',
                       (pid, owner, kind, json.dumps(payload or {}, ensure_ascii=False), time.time()))

    def reserve(self, owner, kind, pid, limits):
        limit = limits.get(kind, 0)
        if type(limit) is not int or not 0 <= limit <= 1000:
            raise UserError('调用额度配置无效')
        with self.db() as db:
            count = db.execute('SELECT COUNT(*) FROM calls WHERE owner=? AND kind=?', (owner, kind)).fetchone()[0]
            if count >= limit:
                raise UserError(f'{kind} 调用额度不足，请联系负责人；失败请求也保留在用量中')
            cid = uuid.uuid4().hex
            db.execute('INSERT INTO calls VALUES(?,?,?,?,?,?)', (cid, owner, kind, pid, 'reserved', time.time()))
        return cid

    def record_call(self, owner, kind, pid):
        """Record manually initiated local calls without enforcing trial quotas."""
        cid = uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO calls VALUES(?,?,?,?,?,?)',
                       (cid, owner, kind, pid, 'reserved', time.time()))
        return cid

    def settle(self, cid, state):
        with self.db() as db:
            db.execute('UPDATE calls SET state=? WHERE id=?', (state, cid))

    def usage(self, owner):
        with self.db() as db:
            return {r['kind']: r['n'] for r in db.execute('SELECT kind,COUNT(*) AS n FROM calls WHERE owner=? GROUP BY kind', (owner,))}

    def clone(self, pid, owner):
        source = self.load(pid)
        if self.busy(pid):
            raise UserError('源项目正在处理，请稍后复制')
        p = copy.deepcopy(source)
        p.update(id=uuid.uuid4().hex, owner=owner, source_project=pid,
                 title=source['title'] + ' · 副本', created_at=time.time(), feedback=None)
        shutil.copytree(self.folder(pid), self.folder(p['id']), dirs_exist_ok=True)
        self.save(p)
        self.event(p['id'], owner, 'clone', {'source': pid})
        return p

    def end_trial(self, owner):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO trials VALUES(?,?)', (owner, time.time()))

    def ended(self, owner):
        with self.db() as db:
            row = db.execute('SELECT ended FROM trials WHERE owner=?', (owner,)).fetchone()
            return row['ended'] if row else None

    def purge(self, apply=False, now=None):
        now = time.time() if now is None else now
        with self.db() as db:
            owners = [r['owner'] for r in db.execute('SELECT owner FROM trials WHERE ended<=?', (now - 7 * 86400,))]
            ids = [r['id'] for r in db.execute('SELECT id FROM projects') if self.load_owner(db, r['id']) in owners]
            if apply:
                for pid in ids:
                    if db.execute("SELECT 1 FROM jobs WHERE project=? AND state='running'", (pid,)).fetchone():
                        raise UserError('到期项目仍有任务，停止后再清理')
                    shutil.rmtree(self.folder(pid))
                    for table in ('events', 'jobs'):
                        db.execute(f'DELETE FROM {table} WHERE project=?', (pid,))
                    db.execute('DELETE FROM projects WHERE id=?', (pid,))
        return ids

    @staticmethod
    def load_owner(db, pid):
        return db.execute('SELECT owner FROM projects WHERE id=?', (pid,)).fetchone()[0]
