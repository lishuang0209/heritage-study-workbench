"""Role-specific identity anchors for editing a storyboard image in place."""
from .domain import UserError
from .styles import image_style, negative_style


def detail_request(project, shot, instruction, store):
    pid = project['id']
    current = store.asset(pid, shot['image'])
    if not current.is_file():
        raise UserError('当前分镜图片不存在，请先恢复图片再局部调整')
    refs = [str(current)]
    settings = project.get('creative_settings')
    if settings:
        characters = settings.get('characters', [])
    else:
        # Older projects can have confirmed identity text in the caption baseline.
        baseline = {x.get('character_id'): x for x in (project.get('baseline') or {}).get('characters', [])}
        characters = [{**c, 'desc': baseline.get(c['id'], {}).get('desc') or c.get('desc', '')}
                      for c in project.get('characters', [])]
    anchors = []
    for character in characters:
        if character['id'] not in shot.get('character_ids', []):
            continue
        text = character.get('name') or character['id']
        if character.get('desc'):
            text += '：' + character['desc']
        if character.get('image'):
            path = store.asset(pid, character['image'])
            if not path.is_file():
                raise UserError('角色参考图不存在：' + (character.get('name') or character['id']) + '。请先恢复角色参考图，再局部调整')
            if str(path) not in refs:
                refs.append(str(path))
            text += f'（参考图{refs.index(str(path)) + 1}）'
        anchors.append(text)
    prompt = ('以参考图1（当前分镜）为底图进行局部编辑。用户要求：' + instruction +
              '\n允许仅修改要求中明确指定的人物局部动作、视线、表情、手势或持物方式。'
              '调整涉及的关节、手指和道具连接，使姿态自然；其余站位、场景、景别、构图和原图笔墨保持。'
              '这是静态姿势调整，不表现连续动作过程，不新增人物，不重画整幅布局。'
              '若原图姿势与本次要求冲突，仅以本次要求更新对应局部，其余区域尽量不变。\n')
    if anchors:
        prompt += ('角色身份依据（只应用于本镜实际出场角色）：\n' + '\n'.join(anchors) +
                   '\n参考图分工：图1决定本镜动作底稿、站位、场景、景别和构图；后续角色图只提供对应角色的面容、发型、发饰和服饰，'
                   '不复制角色图的姿势、朝向、道具、背景、画面左右、人物数量或旧画风。描述中关于参考图左右位置的措辞仅用于辨认身份，不改变本镜站位。'
                   '\n除用户本次明确要求改变的特征外，固定身份以角色设定和角色图为准，不把当前分镜已有的身份偏差当成新设定。'
                   '发髻数量、位置和轮廓、收束或披散方式、发绳配饰保持一致；转头、侧身或面对镜头只改变可见角度，'
                   '遮挡可以使某个发髻不可见，但不合并、增添或重新设计发髻。表情和张嘴不改变脸型、发际线或发型。'
                   '用户明确要求修改发型或服饰时，仅对应特征按本次要求改变，其余身份特征继续保持；不自动修改项目角色设定。'
                   '画外角色保持画外，手部特写不为展示发型而拉远或补齐人物。\n')
    prompt += image_style(project) + '\n避免：' + negative_style(project)
    return prompt, refs
