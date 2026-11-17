"""A narrator is an audio speaker, never a visible cast member."""
NARRATOR = 'narrator'
NARRATOR_NAMES = {'narrator', 'narration', 'voiceover', 'voice-over', '旁白', '解说', '画外音', '旁白（画外音）'}
NARRATION_RULE = ('旁白规则：旁白、解说和画外音只发声，不是出镜角色，不加入characters或character_ids，不画讲解员。'
                  '旁白台词的character_id固定为narrator；人物对白沿用已确认c1/c2并与实际出镜角色对应。'
                  '无人出镜时characters和character_ids都用[]，讲解原文仍完整保留在dialogues中，不为满足台词字段添加人物。')


def speaker_id(value):
    return NARRATOR if isinstance(value, str) and value.strip().casefold() in NARRATOR_NAMES else value


def invalid_speakers(shot):
    return any(line['character_id'] != NARRATOR and line['character_id'] not in shot['character_ids']
               for line in shot['dialogues'])


def native_dialogue_prompt(characters, dialogues):
    names = {c['id']: c['name'] for c in characters}
    spoken = [line for line in dialogues if line['character_id'] != NARRATOR]
    narration = [line for line in dialogues if line['character_id'] == NARRATOR]
    parts = []
    if spoken:
        parts.append('同期对白：按原文生成说话声音与对应人物口型，动作与声音同步。')
    if narration:
        parts.append('画外旁白：按原文生成讲解声音，不新增出镜人物，不安排人物口型；旁白讲述的建筑或构件仍是画面主体。')
    if not dialogues:
        parts.append('本镜无台词，不添加说话或旁白。')
    else:
        parts.append('台词按以下顺序播放：\n' + '\n'.join(
            ('旁白' if line['character_id'] == NARRATOR else names.get(line['character_id'], '角色') + '说')
            + '：“' + line['text'] + '”' for line in dialogues))
        parts.append('只使用上述台词，不额外增加对白或旁白。')
    return '\n'.join(parts)
