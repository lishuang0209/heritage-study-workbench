"""Organize study pictures as a continuous teacher-led observation route."""
import re

from scenarios.ink_drama.domain import UserError

LABELS = {'overview':'外观全貌','approach':'走近建筑','entrance':'入口过渡',
          'interior':'内部空间','structure':'木构关系','detail':'构件细节'}
INTERIOR = r'殿内|室内|内部|内檐|前槽|天花|藻井'


def positive_text(text):
    return '，'.join(part for part in re.split(r'[，,。；;\n]',text)
                    if not re.search(r'不|禁止|避免|缺少|未提供|未识别|不能',part))


def interior_facts(analysis):
    return [fact['id'] for fact in analysis['facts'] if fact['source']=='material'
            and fact['elements'] and re.search(INTERIOR,positive_text(fact['quote']))]


def route_for(count, analysis):
    inside=bool(interior_facts(analysis))
    if count==1:stages=['overview']
    elif count==2:stages=['overview','detail']
    elif count==3:stages=['overview','approach','detail']
    elif count==4:stages=['overview','approach','interior' if inside else 'entrance','detail']
    else:
        stages=['overview','approach']
        if count>=6 or not inside:stages.append('entrance')
        if inside:stages.append('interior')
        stages+=['structure']*(count-len(stages)-1)+['detail']
    return [dict(index=i,stage=stage,label=LABELS[stage]) for i,stage in enumerate(stages)]


def observation_motion(brief, seconds, guided=False):
    stage = brief['visit_stage']
    focus = brief['focus_element']
    motion = brief['motion']
    if guided and stage == 'entrance':
        return '入口机位固定，保持向导与门柱的间距，观察方向朝内。'
    if seconds <= 2:
        return f'稳定取景，给学生时间辨认{focus}。'
    if stage == 'overview' or guided:
        return motion
    # Keep purposeful camera movement. Wind, moving shadows and static holds
    # alone do not lead a student from one architectural feature to another.
    if re.search(r'推近|推进|前移|平移|横移|上移|下移|上仰|上摇|下摇|缓推', positive_text(motion)):
        return motion
    if stage == 'interior' and re.search(r'天花|藻井|顶部', brief['visual']):
        return f'从画面中相邻木构缓缓上摇，到{focus}处停稳，让学生看清它与周围结构的位置关系。'
    if stage == 'structure' and '柱' in focus and re.search(r'上方|上部|柱头', brief['visual']):
        return f'沿画面中的{focus}从柱身缓缓上移，到它与上方木构的交接处停住。'
    if stage == 'detail':
        return f'从可见轮廓轻推至{focus}的细部，停稳后留出辨认时间。'
    return f'从首帧可见范围缓缓推近{focus}，到观察位置停稳，保持相邻结构可辨。'


def validate_route(shots, route, analysis):
    inside=set(interior_facts(analysis));entered=False
    for shot,stop in zip(shots,route):
        if shot['visit_stage']!=stop['stage']:
            raise UserError('参观路线未按从外到内的顺序规划，原分镜已保留，请重新规划')
        space=shot['view_space'];text=positive_text(shot['visual']+'，'+shot['viewpoint'])
        if space=='interior' and (not inside.intersection(shot['fact_ids']) or not re.search(INTERIOR,text)):
            raise UserError('内部镜头缺少研学资料中的空间依据，原分镜已保留，请补充内部资料或改为入口观察')
        if entered and space!='interior':
            raise UserError('参观路线进入内部后又跳回外景，原分镜已保留，请连续安排观察位置')
        if space=='interior':entered=True
        stage=stop['stage']
        if stage in {'overview','approach'} and space!='exterior' or stage=='entrance' and space!='entrance' or stage=='interior' and space!='interior':
            raise UserError('分镜观察位置与参观步骤不符，原分镜已保留，请重新规划')
        wide=bool(re.search(r'全景|远景',shot['camera']))
        if stage=='overview' and not wide or stage in {'structure','detail'} and wide:
            raise UserError('参观路线景别未从全貌收紧到构件，原分镜已保留，请重新规划')
        if space!='interior' and re.search(INTERIOR,text) and (space!='entrance' or not inside.intersection(shot['fact_ids'])):
            raise UserError('分镜内部取景与观察位置或资料依据不一致，原分镜已保留，请重新规划')


def interior_view(shot):
    return bool(re.search(INTERIOR,positive_text(shot.get('camera','')+'，'+shot.get('content',''))))


def interior_material(project):
    material=(project.get('heritage_station') or {}).get('checked_description','')
    return [part.strip() for part in re.split(r'[。；;\n]',material)
            if re.search(INTERIOR,positive_text(part)) and not re.search(r'https?://',part)][:8]


def compatible_reference(project, shot, item):
    if project.get('project_type')!='heritage' or not interior_view(shot):return True
    if not interior_material(project):
        raise UserError('当前资料没有可用于内部画面的描述，请先补充殿内资料；原图保留，本次未调用生成模型')
    # A front elevation cannot constrain an interior camera. Components and
    # independently authored interior materials can still constrain their form.
    return item['id']!=shot.get('scene_id') or bool(re.search(INTERIOR,positive_text(item.get('desc',''))))
