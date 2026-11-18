"""Style policies: image appearance, exclusions, motion and visible evidence."""
PROFILES = {
    'soft': {
        'names': ('工笔淡彩', '清淡柔和'),
        'positive': '传统国画工笔淡彩，细劲匀净连贯的勾线明确形体；外轮廓与内部衣纹保持相近的细线尺度，肩部、袖口、领缘不加粗。衣褶、建筑与器物依结构精细勾勒。先沿结构细腻分染，再以透明淡色逐层薄罩染；色层轻薄清透、过渡均匀，染色收在轮廓以内，保留清晰线条。赭石、花青、藤黄仅为配色倾向；服装与道具的固有色、版型和纹样保持已确认设定，不新增装饰纹样。浅暖白或淡米色绢本视觉质感，不整体泛黄，绢纹细微不抢主体，避免粗重网格底纹。平光、弱明暗塑形，中式空间组织，留白透气，人物与器物空间关系清楚。',
        'negative': '泼墨糊染、枯笔飞白、粗黑轮廓线、随机水渍边缘、斑驳墨团、大块湿画法色斑、漫出衣纹的晕染、用黑色积墨代替衣褶、数字平涂色块、夸张广角透视、强烈主光、轮廓光、光斑、厚涂、CG、3D、磨皮、夸张腮红、高饱和色彩、西式摄影光影、水彩插画质感',
        'motion': '优先固定镜头、缓慢平移或缓缓推近；动作幅度小，提笔斟茶等手部动作保持结构清楚。长卷场景可缓慢横移，不强制所有镜头使用散点透视。',
        'anchors': '细线条是否连贯，设色是否轻薄，是否可见织纹，明暗是否柔和；不要仅凭外观断言真实绢本或具体描法。',
    },
    'simple': {
        'names': ('兼工带写', '简单干净'),
        'positive': '传统国画兼工带写，人物面部和关键动作细致清楚，面部和手部保留细线，衣纹、山石、树木与建筑用简笔写意、松动概括的笔触，与精细面部形成清楚层次差异。衣服用少量主衣褶和大块淡墨表现，不用密集细线填满全身；不画成工笔人物图鉴。背景浅暖白，避免仿古黄纸渐变、做旧晕边，生宣视觉质感与淡墨晕染，墨色浓淡层次丰富，笔墨温润，线条自然，构图舒展，中式留白。',
        'negative': '极端泼墨遮蔽主体、狂乱枯笔、赛璐璐粗勾线、强烈影视打光、写实照片、厚涂插画、高饱和色彩、杂乱数字噪点',
        'motion': '运镜缓慢柔和，优先固定镜头与小幅动作。走动或互动仅在剧情要求时出现，不额外添加打斗；手部、五官和道具结构稳定。',
        'anchors': '人物局部细节与背景概括程度的差异、墨色边缘晕开程度、浓淡层次；不要将兼工带写与小写意直接判为同义。',
    },
    'bold': {
        'names': ('泼墨写意', '泼墨大写意', '浓墨有力'),
        'positive': '传统国画大写意泼墨，枯笔飞白、积墨、生宣墨色渗化，大面积留白，形简神足，苍劲笔墨，浓淡墨层次鲜明，黑白为主、少量淡赭。用大片墨块组织形体，弱化五官和服饰纹样细描，干笔断续与湿墨渗化并置；人物轮廓和关键动作可读，避免摄影式强光硬阴影。',
        'negative': '精细工笔描摹、均匀细线条铺满画面、厚重矿物彩绘、照片般精细五官、强烈摄影阴影、摄影质感、光滑数字插画、网红妆面',
        'motion': '以慢运镜为主，优先远景、空镜和意境转场，避免频繁人脸特写。环境运动仅按明确剧情动作执行；建筑、身体与关键道具保持结构稳定。',
        'anchors': '墨块占比、飞白纹理、留白比例、浓淡层次、人物轮廓和关键动作可辨性；五官简化不等于整张图失败，人物身份无法判断仍须标记不确定。',
    },
}
COMMON_NEGATIVE = '文字、题款、印章、水印、多余肢体、扭曲手指、断裂道具'

def profile_for(project):
    if project.get('_style_override') in PROFILES:
        return PROFILES[project['_style_override']]
    text = (project.get('creative_settings') or {}).get('style', '')
    if not text:
        return None
    for profile in PROFILES.values():
        if any(name in text for name in profile['names']):
            return profile
    return None

def image_style(project):
    profile = profile_for(project)
    if profile:
        return profile['positive'] + '\n' + style_contract(project)
    return (project.get('creative_settings') or {}).get('style') or '传统水墨，低饱和配色，留白与自然笔触'

def style_contract(project):
    """One rendering policy shared by assets, frames, edits and video."""
    profile = profile_for(project)
    if not profile:
        return ''
    common = '全项目统一画风：角色、场景、道具、分镜画面及视频均使用' + profile['names'][0] + '。参考素材只约束身份、形制和布局，旧笔触不得覆盖当前画风。景别只决定取景，不改变绘画媒介；局部特写保持道具结构可辨。'
    if profile is PROFILES['bold']:
        return common + '人物衣纹、近处主建筑、道具与远景都以宽笔墨块、破墨和飞白概括。主建筑不逐片描瓦、不精描斗拱木纹；人物保留完整轮廓和身份特征，关键手部与道具连接清楚，不以缺失身体或道具畸形表现写意。'
    if profile is PROFILES['soft']:
        return common + '人物、建筑和道具统一使用细劲连贯勾线与透明薄染，不在局部混入粗黑墨块、飞白或湿墨糊染。'
    return common + '人物面部与关键手部细致，衣纹、建筑及环境以松动概括笔触表现；道具结构清楚、表面简练，不变成全幅工笔或狂放泼墨。'


def check_frame_style(project, shot):
    """Known preset mismatch is a metadata error, not a visual verdict."""
    from .domain import UserError
    target = profile_for(project)
    prompt = shot.get('used_prompt') or ''
    sources = [profile for profile in PROFILES.values() if profile['positive'].split('，')[0] in prompt]
    if target and len(sources) == 1 and sources[0] is not target:
        raise UserError('当前图片使用的是其他画风，请按项目当前画风重新生成并采用，再修改细节或生成视频。')


def negative_style(project):
    profile = profile_for(project)
    return COMMON_NEGATIVE + '、' + (profile['negative'] if profile else '厚涂油画、磨皮、照片写实、高饱和、3D CG、Q版、赛璐璐平涂')

def video_style_lock(project):
    profile = profile_for(project)
    common = '全片画风统一：本段从开始到结束沿用同一绘画媒介、笔触粗细和概括程度。人物身份、服装固有色不变，保持水墨绘画质感。'
    if profile is PROFILES['bold']:
        return common + '泼墨写意贯穿本段可见人物、建筑和道具。衣褶保留破墨、飞白；可见建筑以断续墨块概括，不补画整齐瓦片和精密斗拱。局部道具轮廓与接触关系清楚，刻字位置和载体保持首帧状态，不额外增加文字。'
    return common


def video_prompt(project, motion):
    profile = profile_for(project)
    style = profile['positive'] if profile else (project.get('creative_settings') or {}).get('style', '传统水墨绘画')
    if project.get('heritage_empty_cast_video'):
        return '\n'.join(['全程是无人建筑观察镜头，严格沿用首帧可见构件、遮挡和取景。画外旁白只进入声音。保持场地空置，禁止新增行人、剪影、倒影或移动道具。',
                          '只按以下运镜要求连续拍摄，固定机位时保持各构件静止：'+motion,
                          '保持首帧的二维笔墨、设色与纸感，禁止转场、叠化、重影、字幕和水印。'])
    return '\n'.join([
        '让输入的绘画首帧产生局部连续动作。保持输入图的实际构图、景别、人物大小、背景布局和二维绘画材质，不重新设计画面。',
        '本次只生成一个连续镜头，不切镜、不反打、不转场。运镜未明确指定时机位固定，焦距、取景范围与人物画面占比保持首帧状态；禁止自行快速拉近、推镜、变焦、裁切放大或追随手和道具改成特写。人物走动只按剧情发生，不靠镜头放大强调动作。明确指定的运镜仅在同一镜头内按指定速度平滑完成。',
        '画法参考（仅保持笔墨，不重新安排画面）：' + style,
        '剧情动作：' + motion,
        '动作完成后保持末态至结束。画外物体继续留在画外；手与道具连接连续，建筑、身体与关键道具保持结构稳定。',
        '保持首帧的平面墨色、纸绢纹理和笔触，不新增摄影虚化、皮肤立体塑形、丝绸镜面高光或实体三维材质。',
        '同一画风贯穿每一帧，也覆盖人物面部、手部、衣料和本镜已有道具；不能只有背景保持水墨、人物变成写实。即使明确要求拉近或近景，也只放大原有笔墨形状，保持首帧的线条概括与平面色块；不因距离变近补出皮肤毛孔、指节立体明暗、写实肌肉、织物纤维、皮革或金属的摄影质感。不从二维绘画逐渐变成真人、照片或三维渲染。',
        '水墨晕染、飞白、墨块和纸张纹理是静态绘画质感，不是烟气。背景默认保持稳定，不凭画风添加飘烟、蒸汽或雾带；只有剧情动作明确要求时才表现对应环境运动。',
        '不生成字幕、题字、印章或水印。'])

def caption_guidance(project):
    profile = profile_for(project)
    return ('仅观察可见视觉证据，不猜测真实纸绢材质、颜料或具体描法。无法判断则用uncertain，技法无法确认时用空数组，其他疑点写入uncertainties。'
            '预设仅作为检查目标，不得为了符合预设而编造特征，不自动覆盖用户选定画风。\n检查重点：' +
            (profile['anchors'] if profile else '线条、晕染、留白、纹理与墨色层次。'))


def clean_image_prompt(prompt):
    rule = ('输出一幅纯绘画，不是图鉴或海报。画面四周及主体内不出现任何文字、汉字、字母、题款、印章、签名、标签、水印或伪文字。'
            '提示中的朝代、画风名称和描述只指导造型，不得作为文字绘入画面。留白保持空白；参考图若有题字印章也不继承。')
    return rule + '\n' + prompt + '\n最终画面要求：纯绘画，无题字、无印章、无标签。'


def current_style_matches(project, shot):
    """Only inherit a known matching preset, not words in negative prompts."""
    target = profile_for(project)
    matches = [v for v in PROFILES.values() if v['positive'].split('，')[0] in (shot.get('used_prompt') or '')]
    return bool(shot.get('image') and target and len(matches) == 1 and matches[0] is target)


def with_style_reference(project, prompt, refs, *, asset_group=None, current_style_reference=None):
    """Append a style-only image without replacing identity reference images."""
    from pathlib import Path
    profile = profile_for(project)
    if profile is None:
        return prompt, list(refs)
    key = next(key for key, value in PROFILES.items() if value is profile)
    suffix = {'scenes': '-empty', 'props': '-props'}.get(asset_group, '')
    sample = Path(__file__).parent / 'references/styles' / (key + suffix + '.png')
    if asset_group == 'frames' and current_style_reference is not None:
        sample = Path(current_style_reference)
    if not sample.is_file():
        raise ValueError('画风参考图缺失，请恢复平台素材后重试')
    inputs = list(refs) + [str(sample)]
    instruction = (f'参考图分工：第{len(inputs)}张是唯一画风样张，只参考笔触、线条详略、墨色晕染和纸绢视觉质感。'
                   '不要复制样张中的人物身份、服饰形制、建筑、伞、姿势、构图、文字或印章；主体数量、场景与动作严格依照本次文字设定。'
                   '其余参考图仅提供人物身份、服饰和场景道具，不继承其旧画风。只输出一幅所要求的新画面，不输出样张复刻或拼贴。')
    if asset_group == 'frames':
        return instruction + '\n' + prompt, inputs
    if asset_group in {'frames', 'scenes'}:
        instruction += '建筑数量和布局只按当前场景设定，不将画风样张中的门楼复制到背景，不额外新增第二座建筑。'
        if profile is PROFILES['bold']:
            instruction += '主建筑与远景必须使用同一泼墨概括程度。近处屋檐是大块破墨与飞白，梁柱是宽笔断续墨带；瓦片、斗拱、木纹不逐个描绘。仅保留屋檐走向、门洞开合、主要柱位与可站立平台，结构可辨不等于构件精描。禁止前景建筑工笔描线、仅远山背景泼墨的混合画法。'
    if asset_group in {'scenes', 'props'}:
        instruction += '本次是无人素材：禁止人物、人体局部、剪影、人影或人物倒影；风格规则中关于人脸、人物的描述不适用于本次。'
    if asset_group == 'props':
        instruction += '只取样张笔墨，禁止复制建筑、台阶、山水；目标道具独立置于空白背景，不画持物的手。'
    return instruction + '\n' + prompt + '\n最终笔墨要求：' + image_style(project), inputs


def check_material_styles(project, items):
    """Reject known incompatible generation presets; unknown uploads stay usable."""
    from .domain import UserError
    target = profile_for(project)
    records = project.get('setting_generation_records', {})
    conflicts = []
    for item in items:
        record = records.get(item.get('image'), {})
        source = profile_for({'creative_settings': {'style': record.get('style', '')}})
        if target and source and source is not target:
            conflicts.append(item['name'])
    if conflicts:
        raise UserError('参考素材画风不一致：' + '、'.join(conflicts) + '。请到创作设定按当前画风重新生成并确认，再生成分镜。')


def style_observation(project, observed):
    """Caption evidence is advisory, never a visual acceptance guarantee."""
    tags = set(observed['ink_style']['techniques'])
    profile = profile_for(project)
    if profile is PROFILES['bold'] and not tags.intersection({'泼墨', '枯笔飞白'}):
        message = '可能偏离泼墨写意：未识别到泼墨或飞白，请检查是否仍以精细描线为主。'
    elif profile is PROFILES['soft'] and tags.intersection({'泼墨', '枯笔飞白'}):
        message = '可能偏离工笔淡彩：识别到了泼墨或飞白，请检查线条与薄染。'
    else:
        message = '已提取画风特征，请对照样张确认；识别结果不代表画风已达标。'
    return {'message': message, 'techniques': sorted(tags), 'uncertainties': observed.get('uncertainties', [])}


def restyle_request(project, current_image, instruction=''):
    """Separate style transfer from detail editing; style sample is image 1."""
    from pathlib import Path
    profile = profile_for(project)
    if profile is None:
        raise ValueError('请先选择水墨类型')
    key = next(k for k, value in PROFILES.items() if value is profile)
    sample = Path(__file__).parent / 'references/styles' / (key + '.png')
    if not sample.is_file():
        raise ValueError('画风参考图缺失')
    changes = {
        'bold': '将屋檐改成淋漓破碎的大墨块，梁柱改成宽笔断续墨带，取消逐片瓦、斗拱和木纹描线；衣服以几块浓淡墨和飞白概括，取消密集衣褶线。人物面容用简练笔触保留识别特征，身体与道具连接完整。',
        'soft': '将粗墨块、飞白和随机水渍改为匀净连续细线与薄层分染，建筑、衣纹用精细勾线和透明淡彩表现，浅米色绢底，弱明暗。',
        'simple': '面部与关键手部保持细致，衣服和建筑删去密集细节，用松动简笔和温润墨色概括，形成工与写的层次。',
    }
    prompt = ('这是整幅换画法重绘任务，必须出现明显笔墨变化。图1是目标画法，图2是待重绘内容。'
              '图1只取笔触、墨块、线条详略和染色，不复制其中的人物、建筑或构图。'
              '图2只取人物身份、服装主色、人数、姿势关系、道具状态和取景，原图的线条、材质、明暗与细部必须重新画。'
              '允许轮廓边缘和局部细节随画法概括，不能把保留内容理解成保留原像素。\n'
              + changes[key] + '\n目标画法：' + profile['positive']
              + ('\n用户补充（服从目标画法）：' + instruction.strip() if instruction.strip() else '')
              + '\n排除：' + negative_style(project))
    return prompt, [str(sample), str(current_image)]


def restyle_change_warning(original, generated):
    """Only detect near-copy outputs, not whether the target style is correct."""
    from PIL import Image, ImageChops, ImageStat
    with Image.open(original) as first, Image.open(generated) as second:
        a = first.convert('RGB').resize((256, 256))
        b = second.convert('RGB').resize((256, 256))
        difference = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
    return ('候选与原图的整体变化较小，画风可能未有效改变，请对照样张检查后再采用。'
            if difference < 10 else None)
