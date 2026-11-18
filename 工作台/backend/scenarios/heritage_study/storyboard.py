"""Plan narration-only history from approved words, with model-authored visuals."""
import json
import math
import re

from scenarios.ink_drama.domain import ShotInput, UserError, board
from .research_plan import ENGINE, analyze_research, reconstruct_visuals
from .visit_route import LABELS


def narration_nodes(text, seconds):
    # Preserve all spoken words and punctuation, including dates. Long sentences
    # may span shots; their continuation is not a new historical assertion.
    sentences = re.findall(r'[^。！？\n]+[。！？]?', text)
    nodes = []
    for sentence in sentences:
        sentence = sentence.strip()
        while len(sentence) > 54:
            # Imported documents often use ASCII punctuation; prefer a real
            # clause boundary instead of splitting words such as 木结构.
            pauses = [match.end() for match in re.finditer(r'[，,；;：:]', sentence[:54]) if match.end() >= 12]
            cut = pauses[-1] if pauses else 54
            if len(sentence)-cut < 12:
                earlier = [position for position in pauses if len(sentence)-position >= 12]
                if earlier:
                    cut = earlier[-1]
                elif len(sentence) <= 90:
                    break
            nodes.append(sentence[:cut]); sentence = sentence[cut:]
        if sentence: nodes.append(sentence)
    if not nodes: raise UserError('历史旁白为空，请先在研学脚本中填写并保存')
    maximum = min(30, seconds // 2)
    while len(nodes) > maximum:
        index = min(range(len(nodes)-1), key=lambda i: len(nodes[i])+len(nodes[i+1]))
        nodes[index:index+2] = [nodes[index]+nodes[index+1]]
    # A long budget with little narration needs additional silent views, not
    # invented facts or a single clip longer than the video model accepts.
    minimum = math.ceil(seconds / 15)
    nodes += [''] * max(0, minimum-len(nodes))
    return nodes


def allocate_seconds(nodes, seconds, speed=.95):
    # Budget each spoken line independently, including pauses and the clip ending.
    durations = []
    for text in nodes:
        units = sum(char.isalnum() for char in text)
        pauses = len(re.findall(r'[，,。！？；;：:]', text))
        estimate = (units / 4 + pauses * .15) / speed + .25
        durations.append(max(2, math.ceil(estimate)))
    if max(durations) > 15:
        raise UserError('单句旁白预计超过15秒，请在研学脚本中分句后再拆分镜')
    if sum(durations) > seconds:
        raise UserError(f'按当前旁白语速，历史段预计至少需要{sum(durations)}秒，当前为{seconds}秒。请延长历史段或精简旁白后再拆分镜')
    weights = [max(4, len(text)) for text in nodes]
    for _ in range(seconds-sum(durations)):
        available = [i for i, duration in enumerate(durations) if duration < 15]
        if not available: raise UserError('历史段超过可用镜头时长，请减少时长或增加讲解节点')
        index = max(available, key=lambda i: weights[i] / (durations[i]+1))
        durations[index] += 1
    return durations


def history_board(text, query, settings, seconds, *, research=None, progress=None, speed=.95):
    if type(seconds) is not int or not 3 <= seconds <= 180:
        raise UserError('历史段时长需为3至180秒的整数')
    guide=(research or {}).get('guide') or {}
    from .guide import character
    if settings.get('characters') and not character(settings,guide):
        raise UserError('参观路线分镜请使用无人讲解或已启用的小向导')
    scenes = settings.get('scenes') or []
    if not scenes: raise UserError('请先确认历史讲解使用的建筑场景')
    nodes = narration_nodes(text, seconds)
    if any(len(words)>300 for words in nodes):
        raise UserError('当前历史时长不足以安排完整旁白，请增加历史段时长后再拆分镜；本次未调用模型')
    durations = allocate_seconds(nodes, seconds, speed)
    report=progress or (lambda message,completed,total:None)
    report('正在解析研学资料',0,3)
    analysis = analyze_research(text,research,query)
    report(f'资料已解析，正在规划{len(nodes)}个分镜的画面与运镜',1,3)
    briefs = reconstruct_visuals(nodes,durations,analysis,settings,research,query)
    report('正在核对旁白、时长与素材引用',2,3)
    return compose_board(nodes,durations,analysis,briefs,settings,guide=guide)


def compose_board(nodes,durations,analysis,briefs,settings,*,guide=None):
    """Materialize a reviewed plan without generating or replacing any media."""
    scenes=settings['scenes']
    facts = {fact['id']:fact for fact in analysis['facts']}
    shots = []
    for index, (words, duration) in enumerate(zip(nodes, durations)):
        brief=briefs[index]
        scene=next(item for item in scenes if item['id']==brief['scene_id'])
        shot=ShotInput.model_validate(dict(
            duration=duration,content=brief['visual'].strip(),scene=scene['name'],scene_id=scene['id'],
            camera=brief['camera'],motion=brief['motion'].strip() or '固定机位，保持本镜主体与构图。',prop_ids=brief['prop_ids'],character_ids=[],
            dialogues=[dict(character_id='narrator',text=words)] if words else [],
        )).model_dump()
        shots.append(shot)
    result = board(json.dumps(dict(characters=[], shots=shots), ensure_ascii=False))
    segments = []
    for index, shot in enumerate(result['shots']):
        shot.update(source_segment=index+1, source_shot=1, generation_unit='shot',
                    study_topic=briefs[index]['topic'],research_evidence=[facts[fid] for fid in briefs[index]['fact_ids']],
                    study_visit=dict(stage=briefs[index]['visit_stage'],label=LABELS[briefs[index]['visit_stage']],
                                     space=briefs[index]['view_space'],viewpoint=briefs[index]['viewpoint']))
        segments.append(dict(segment_id=f'history_{index+1}', segment_number=index+1,
                             episode_number=1, location=shot['scene'], characters=[], total_duration=shot['duration'],
                             shots=[dict(shot_number=1,shot_type=shot['camera'],duration=shot['duration'],content=shot['motion'])]))
    result.update(storyboard_plan=segments, storyboard_episodes=[dict(episode_number=1,segments=segments)],
                  storyboard_analysis=analysis,storyboard_visual_plan=briefs,storyboard_engine=ENGINE)
    if guide and guide.get('enabled'):
        from .guide import guided_board
        result=guided_board(result,settings,guide)
        result['creative_draft']=settings
    return result
