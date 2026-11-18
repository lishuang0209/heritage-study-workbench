"""An optional fictional guide; never a source of architectural history."""
import copy
import json

from scenarios.ink_drama.domain import UserError,ShotInput,board
from scenarios.ink_drama.creative import validate_settings

NAME='小木匠阿木'
DESCRIPTION=('虚构的宋代小木匠学徒，约十二岁男孩，清秀圆脸，神情温和好奇，正常少年身材比例。'
             '黑发收成头后一处低小髻，用素灰布巾包束，发髻数量与布巾形状固定。'
             '灰青色窄袖交领短衫、米白内领、深褐布腰带、褐色长裤、素布鞋；不佩华丽首饰，不持工具。'
             '全程保持脸型、发型、服装版型和固有色，采用项目当前水墨画风。'
             '这是宋代风格的教学虚构人物，不指代真实历史人物；建筑按现存研学资料展示，不随人物服饰复原整座寺院。')
VISIBLE={'overview','approach','entrance'}
ACTIONS={'overview':'抬手示意大家先看建筑全貌，随后手臂自然放下。',
         'approach':'沿参观方向缓慢走近一小步，侧身示意观察檐下，保持建筑连续。',
         'entrance':'停在入口旁，抬手示意向内看，随后保持朝内的视线。'}
POSITIONS={'overview':'站在建筑外画面一侧，人物较小，不遮挡完整建筑',
           'approach':'位于画面一侧，身体朝向建筑，留出观察主体',
           'entrance':'站在入口侧边，身体朝向内部，不挡住向内的视线'}


def definition(project):
    return project.get('heritage_guide') or {}


def character(settings,guide):
    if not guide or not guide.get('enabled'):return None
    return next((item for item in settings.get('characters',[]) if item['id']==guide['character_id']),None)


def manifest(project,settings):
    result=copy.deepcopy(settings);guide=definition(project)
    if not guide:return result
    cid=guide['character_id'];existing=next((c for c in result['characters'] if c['id']==cid),None)
    if guide.get('enabled'):
        if existing is None:result['characters'].append(dict(id=cid,name=guide['name'],desc=guide['desc'],image=None,views={}))
    else:result['characters']=[c for c in result['characters'] if c['id']!=cid]
    return validate_settings(result)


def visible(stage,guide):
    return bool(guide and guide.get('enabled') and stage in VISIBLE)


def guide_shot(project,shot):
    guide=definition(project)
    return bool(guide and shot.get('character_ids')==[guide['character_id']])


def entrance_motion(project, shot, motion, camera, mode):
    if project.get('project_type') != 'heritage' or not guide_shot(project, shot):
        return motion
    if (shot.get('study_visit') or {}).get('stage') != 'entrance':
        return motion
    if mode == 'first_frame' and not camera and motion == shot.get('motion'):
        motion = '固定入口机位。小向导双脚停在首帧位置，只朝内转头，原地轻抬手指向入口。'
    return motion + ' 人物与梁柱各自保持首帧的前后关系，梁底始终高于头顶。双脚贴地，身体、发髻与手臂不穿过梁柱，木构边缘不透过人物。保持透视连续，不突然放大人物。'


def require_reference(project,shot,store):
    guide=definition(project)
    if project.get('project_type')!='heritage' or not guide or guide['character_id'] not in shot.get('character_ids',[]):return
    item=next((c for c in (project.get('creative_settings') or {}).get('characters',[]) if c['id']==guide['character_id']),None)
    if not item or not item.get('image') or not store.asset(project['id'],item['image']).is_file():
        raise UserError('请先在“素材与画风”生成或上传并确认小向导参考图，再生成出镜画面；本次未调用生图模型')


def guided_board(source,settings,guide):
    """Create an empty-output draft; preserve words, durations and source facts."""
    actor=character(settings,guide);shots=[];metadata=[]
    briefs=source.get('storyboard_visual_plan') or []
    for index,old in enumerate(source['shots']):
        fields={key:copy.deepcopy(old.get(key)) for key in ShotInput.model_fields}
        base=old.get('study_guide') or {}
        fields['content']=base.get('base_content',old['content']);fields['motion']=base.get('base_motion',old['motion'])
        cid=(guide or {}).get('character_id')
        fields['character_ids']=[value for value in fields['character_ids'] if value!=cid]
        visit=old.get('study_visit') or {};stage=visit.get('stage','')
        meta={key:copy.deepcopy(old[key]) for key in ('study_visit','study_topic','research_evidence','source_segment','source_shot','generation_unit') if key in old}
        if actor and visible(stage,guide):
            brief=briefs[index] if index<len(briefs) else {}
            action=(brief.get('guide_action') or ACTIONS[stage]).removeprefix(actor['name']);position=(brief.get('guide_position') or POSITIONS[stage]).removeprefix(actor['name'])
            meta['study_guide']=dict(character_id=actor['id'],base_content=fields['content'],base_motion=fields['motion'])
            fields['content']=f"{actor['name']}{position}。"+fields['content']
            fields['motion']=f"{actor['name']}{action}"+fields['motion']
            fields['character_ids']=[actor['id']]
        shots.append(fields);metadata.append(meta)
    cast=[{key:c[key] for key in ('id','name','desc')} for c in settings['characters']]
    result=board(json.dumps(dict(characters=cast,shots=shots),ensure_ascii=False))
    for shot,meta in zip(result['shots'],metadata):shot.update(meta)
    for key in ('storyboard_analysis','storyboard_visual_plan','storyboard_engine','storyboard_origin','heritage_story_source'):
        if key in source:result[key]=copy.deepcopy(source[key])
    segments=[dict(segment_id=f'history_{i+1}',segment_number=i+1,episode_number=1,location=s['scene'],
                   characters=[c['name'] for c in cast if c['id'] in s['character_ids']],total_duration=s['duration'],
                   shots=[dict(shot_number=1,shot_type=s['camera'],duration=s['duration'],content=s['motion'])]) for i,s in enumerate(result['shots'])]
    result.update(storyboard_plan=segments,storyboard_episodes=[dict(episode_number=1,segments=segments)])
    return result


def set_enabled(project,enabled):
    from .workflow import planning_settings,planning_fingerprint
    current=definition(project)
    if bool(current.get('enabled'))==enabled:return False
    if current:guide={**current,'enabled':enabled}
    else:
        used={c['id'] for c in (project.get('creative_settings') or project.get('creative_draft') or {}).get('characters',[])} | {c['id'] for c in project.get('characters',[])}
        cid=next((value for value in ('c1','c2') if value not in used),None)
        if cid is None:raise UserError('当前已有两位角色，请先在素材与画风中调整角色后再添加向导')
        guide=dict(enabled=enabled,character_id=cid,name=NAME,desc=DESCRIPTION,fictional=True,era='宋代风格',
                   source='https://www.dpm.org.cn/vr/stone-moat/wyd_17.html')
    project['heritage_guide']=guide;project['heritage_guide_version']=project.get('heritage_guide_version',0)+1
    source=project.get('storyboard_draft') or project
    if source.get('shots') and all(s.get('study_visit') for s in source['shots']):
        settings=planning_settings(project);draft=guided_board(source,settings,guide)
        draft.update(creative_draft=settings,heritage_story_source=project['script'],
                     heritage_story_research_stamp=planning_fingerprint(project),storyboard_guide_version=project['heritage_guide_version'])
        if project.get('storyboard_draft'):project.setdefault('storyboard_draft_history',[]).append(project['storyboard_draft'])
        project['storyboard_draft']=draft
    return True
