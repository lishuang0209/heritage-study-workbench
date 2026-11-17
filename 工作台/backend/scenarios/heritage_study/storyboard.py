"""Plan narration-only history from approved words, with model-authored visuals."""
import json
import math
import re

from scenarios.ink_drama.domain import ShotInput, UserError, board, parse_json
from .visual_plan import visual_briefs, differentiated_content, differentiated_motion


def narration_nodes(text, seconds):
    # Preserve all spoken words and punctuation, including dates. Long sentences
    # may span shots; their continuation is not a new historical assertion.
    sentences = re.findall(r'[^。！？\n]+[。！？]?', text)
    nodes = []
    for sentence in sentences:
        sentence = sentence.strip()
        while len(sentence) > 54:
            cut = max(sentence.rfind('，', 12, 54), sentence.rfind('；', 12, 54)) + 1
            if cut < 12: cut = 54
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


def allocate_seconds(nodes, seconds):
    durations = [2] * len(nodes)
    weights = [max(4, len(text)) for text in nodes]
    for _ in range(seconds-sum(durations)):
        available = [i for i, duration in enumerate(durations) if duration < 15]
        if not available: raise UserError('历史段超过可用镜头时长，请减少时长或增加讲解节点')
        index = max(available, key=lambda i: weights[i] / (durations[i]+1))
        durations[index] += 1
    return durations


def history_board(text, query, settings, seconds):
    if type(seconds) is not int or not 3 <= seconds <= 180:
        raise UserError('历史段时长需为3至180秒的整数')
    if settings.get('characters'):
        raise UserError('历史旁白专用分镜仅适用于已确认无人出镜的项目')
    scenes = settings.get('scenes') or []
    if not scenes: raise UserError('请先确认历史讲解使用的建筑场景')
    nodes = narration_nodes(text, seconds)
    if any(len(words)>300 for words in nodes):
        raise UserError('当前历史时长不足以安排完整旁白，请增加历史段时长后再拆分镜；本次未调用模型')
    durations = allocate_seconds(nodes, seconds)
    briefs = visual_briefs(nodes,settings)
    shots = []
    for index, (words, duration) in enumerate(zip(nodes, durations)):
        brief=briefs[index]
        allowed={**settings,'props':[item for item in settings.get('props',[]) if item['id'] in brief['prop_ids']]}
        prompt = ('为古建研学历史讲解规划一个水墨镜头，只设计画面，不起草或改写旁白。'
                  '已确认无人出镜，不画讲解员、僧人、工匠或学生，不把旁白当作人物；不补造古代事件现场或未经核实的建筑复原。'
                  '每个历史节点对应不同的观察角度，可使用建筑整体、梁架、已确认构件和环境细节；不能用无关画面凑镜头。'
                  '实拍只约束可见形制，后续实物观察使用真实照片；不得将当前外观全部称为北宋原构。'
                  '首帧content写静态起点，motion仅写局部环境变化或平缓运镜，不切镜、不新增人物。'
                  '只输出一个JSON对象：{"content":"首帧画面","scene_id":"已确认场景编号","motion":"动作或运镜"}。'
                  '不返回角色、台词、时长或数组；景别与素材引用由分工表确定，程序使用已审核的旁白原文。'
                  f'\n本镜：{index+1}/{len(nodes)}，{duration}秒。'
                  '\n当前历史节点：'+(words or '讲解后的建筑静观，不增加台词')+
                  '\n本镜必须遵守的画面分工：'+json.dumps(brief,ensure_ascii=False)+
                  '\n全片画面分工（保持各镜主体、景别、角度的变化）：'+json.dumps(briefs,ensure_ascii=False)+
                  '\n已完成的前镜（不要重复其主体大小、角度及构图）：'+json.dumps([{key:shot[key] for key in ('content','camera','prop_ids')} for shot in shots[-2:]],ensure_ascii=False)+
                  '\n完整已审核旁白：'+text+'\n本镜可用素材：'+json.dumps(allowed,ensure_ascii=False))
        raw = parse_json(query(prompt))
        if isinstance(raw, dict) and isinstance(raw.get('shots'), list) and len(raw['shots']) == 1:
            raw = raw['shots'][0]
        if not isinstance(raw, dict): raise UserError(f'第{index+1}镜画面规划格式错误，原镜头保留')
        scene = next((item for item in scenes if item['id'] == raw.get('scene_id')), None)
        if scene is None and len(scenes) == 1: scene = scenes[0]
        if scene is None: raise UserError(f'第{index+1}镜未选择已确认的建筑场景')
        props=brief['prop_ids']
        shot = ShotInput.model_validate(dict(
            duration=duration, content=differentiated_content(raw,brief,shots[-1] if shots else None), scene=scene['name'], scene_id=scene['id'],
            camera=brief['camera'], motion=differentiated_motion(raw,brief), prop_ids=props,
            character_ids=[], dialogues=[dict(character_id='narrator', text=words)] if words else [],
        )).model_dump()
        shots.append(shot)
    result = board(json.dumps(dict(characters=[], shots=shots), ensure_ascii=False))
    segments = []
    for index, shot in enumerate(result['shots']):
        shot.update(source_segment=index+1, source_shot=1, generation_unit='shot')
        segments.append(dict(segment_id=f'history_{index+1}', segment_number=index+1,
                             episode_number=1, location=shot['scene'], characters=[], total_duration=shot['duration'],
                             shots=[dict(shot_number=1,shot_type=shot['camera'],duration=shot['duration'],content=shot['motion'])]))
    result.update(storyboard_plan=segments, storyboard_episodes=[dict(episode_number=1,segments=segments)],
                  storyboard_visual_plan=briefs,storyboard_engine='heritage-history-facts-v2')
    return result
