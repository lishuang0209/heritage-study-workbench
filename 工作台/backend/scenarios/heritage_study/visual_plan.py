"""Assign distinct visual jobs before designing individual history shots."""
import re
from difflib import SequenceMatcher


def visual_briefs(nodes, settings):
    text=''.join(nodes)
    target=next((item for item in settings.get('props',[]) if item['name'] in text),None)
    component=target['name'] if target else '可见构件'
    target_ids=[target['id']] if target else []
    briefs=[]
    for index,words in enumerate(nodes):
        if re.search(r'文物保护|保护单位|国保',words):role='protection'
        elif re.search(r'修缮|修建|大修|维修|后世|后期',words):role='repair'
        elif re.search(r'接下来|抬头|寻找|找到|请.*观察|对照',words):role='observation'
        elif re.search(r'木构|形制|营造|技艺|技术|构造|连接',words):role='structure'
        elif re.search(r'前身|寺额|赐|寺名|原名',words):role='origin'
        elif index==0:role='establish'
        else:role='context'
        plans={
            'establish':('交代建筑及所在环境','远景，斜前方平视，建筑整体与周围已知环境同框','完整建筑和环境关系',[],
                         '以已确认建筑整体为主体，保留完整外轮廓与周围环境，局部构件只占很小比例。'),
            'origin':('寺名沿革的环境承接','全景，侧前方平视，建筑侧向展开，殿前空间形成前景','建筑侧向外观与殿前空间',[],
                      '从侧前方展示已确认建筑和殿前空间，使用现状作为讲解背景。'),
            'structure':('说明木构的整体承接关系','中景，檐下侧向略仰视，柱头、梁架与相邻构件同框','梁柱及'+component+'的结构关系',target_ids,
                         '展示可见柱头、梁架与'+component+'的承接关系，保留上下游结构和空间，单个构件不占满画面。'),
            'repair':('观察连接局部并承接修缮讲解','特写，侧向略仰视，一处构件与梁端连接占画面主体','一处'+component+'与相邻结构的连接细节',target_ids,
                      '取景限于一处'+component+'与相邻梁端的可见连接，保留相接关系，不展示整座建筑。只观察可见形态，不用木色深浅判定年代。'),
            'protection':('以完整建筑承接文物保护意义','全景，正面平视，完整屋顶、殿身和基座入画','完整建筑正立面',[],
                          '正面展示完整屋顶、殿身及基座，建筑整体为主体，四周保留少量空间；不放大檐下局部，不增加未经提供的保护碑或标识。'),
            'observation':('由整体结构引导寻找目标','中景，沿柱线略仰视，柱头至檐下目标的连接路径完整可见','柱子通向'+component+'的定位关系',target_ids,
                           '沿一根可见柱线向上展示柱头到檐下'+component+'的位置关系，保留定位线索，与前面的孤立局部特写区分。'),
            'context':('补充建筑空间观察','全景，斜侧平视，以建筑与相邻空地的空间关系组织画面','建筑与周围空间',[],
                       '展示已确认建筑的现状与周围空间，不另造历史事件现场或未提供的构筑物。'),
        }
        purpose,camera,subject,props,content=plans[role]
        if briefs and briefs[-1]['role']==role and briefs[-1]['camera']==camera:
            # Two sentences about the same topic need a scale/subject change,
            # not another near-identical view with slightly different wording.
            if props:
                camera='中景，侧向平视，构件与相邻结构同框' if camera.startswith('特写') else '特写，侧向略仰视，聚焦一处可见连接'
                subject='相邻结构关系' if camera.startswith('中景') else '一处可见连接'
                content='以已确认素材展示'+subject+'，与上一镜的取景范围拉开距离。'
            else:
                camera='远景，斜后方平视，建筑整体与环境同框'
                subject='建筑整体与环境关系'
                content='保留完整建筑与环境关系，从与上一镜不同的斜侧方向取景。'
        briefs.append(dict(index=index+1,role=role,purpose=purpose,camera=camera,subject=subject,prop_ids=props,content=content))
    return briefs


def differentiated_content(raw,brief,previous=None):
    content=raw.get('content') or ''
    if not isinstance(content,str):return content
    invalid=(not brief['prop_ids'] and re.search(r'特写|中近景|局部.*主体|木纹.*细节',content))
    if previous:
        normalize=lambda value:re.sub(r'[\s，,。:：;；]','',value)
        previous_content=previous['content'].split('\n画面补充：',1)[-1]
        invalid=invalid or SequenceMatcher(None,normalize(content),normalize(previous_content)).ratio()>.8
    # Keep the verified shot brief as a local fallback, with no extra model call.
    return brief['content'] if invalid else brief['content']+'\n画面补充：'+content


def differentiated_motion(raw,brief):
    motion=raw.get('motion') or ''
    if not brief['prop_ids'] and re.search(r'推近|拉近|放大|变焦|聚焦|特写|斗拱|柱础|脊兽',motion):
        return '固定镜头，保持完整建筑与环境的取景范围，仅自然光有细微变化。'
    return motion
