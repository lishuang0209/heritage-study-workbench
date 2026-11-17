"""Only teacher-provided facts enter the editable educational narrative."""
import re

from .domain import observation_guidance
from .timing import Timing

CASES = [
 dict(id='baoguo', title='保国寺 · 找斗拱', history='保国寺大殿重建于北宋大中祥符六年（1013年），后来在清代经历修缮。', sources=[dict(title='中国港口博物馆：保国寺北宋大殿价值解读',url='https://www.portmuseum.cn/doc/sx/gbzx/read/38733.shtml')], station=dict(building='宁波保国寺大殿',name='找斗拱',component='斗拱',
      grade='小学三至六年级',standing_position='',
      checked_description='历史背景：保国寺大殿重建于北宋大中祥符六年（1013年），后来在清代经历修缮。\n观察重点：观察柱子上方层层向外伸出的木构件。\n现场核对：现状包含清代加建外檐，不能将照片中所有木构件都视为北宋原构。\n资料来源：中国港口博物馆 https://www.portmuseum.cn/doc/sx/gbzx/read/38733.shtml',
      objective='沿实拍图的柱子向上找到同一组斗拱，并观察向外伸出的部分。',
      instruction='在老师指定位置，沿照片标出的柱子向上找，指出同一组斗拱，再指出向外伸出的部分。',question='哪一层木构件伸得最远？'),
      intro='保国寺大殿重建于北宋，后来也经历了修缮。今天，我们从斗拱开始观察。'),
 dict(id='ningyuan',title='宁远文庙 · 找石狮柱础',history='宁远文庙始建于宋代，现存建筑为清代同治至光绪年间重建。',sources=[dict(title='湖南省文物局：研学营走进宁远文庙',url='https://wwj.hunan.gov.cn/wwj/c100310/c100311/202507/t20250718_33744186.html')],station=dict(building='宁远文庙大成殿',name='找石狮柱础',component='石狮柱础',
      grade='小学三至六年级',standing_position='',
      checked_description='历史背景：宁远文庙始建于宋代，现存建筑为清代同治至光绪年间重建。\n观察重点：沿同一根角柱找到柱脚的石狮柱础。\n现场核对：目标构件名称及其位置须由老师结合实拍确认。\n资料来源：湖南省文物局 https://wwj.hunan.gov.cn/wwj/c100310/c100311/202507/t20250718_33744186.html',
      objective='由角柱定位柱脚，观察石狮形象。',instruction='在老师指定的角柱外侧，先找到照片里的角柱，再看柱子和地面之间，不触摸或攀爬。',
      question='你最先认出的是石狮的脸、爪子，还是身体轮廓？'),intro='宁远文庙始建于宋代，现存建筑为清代重建。今天，我们来找找柱脚的石狮。'),
 dict(id='taihe',title='太和殿 · 找屋角小兽',history='太和殿是明清皇帝举行盛大典礼的地方，现存形制源于清康熙年间重建。',sources=[dict(title='故宫博物院：太和殿',url='https://www.dpm.org.cn/explore/building/236465.html')],station=dict(building='故宫太和殿',name='找屋角小兽',component='骑凤仙人与脊兽',
      grade='小学三至六年级',standing_position='',
      checked_description='历史背景：太和殿是明清皇帝举行盛大典礼的地方，现存形制源于清康熙年间重建。\n观察重点：从同一屋角的特写辨认骑凤仙人与其后的脊兽。\n现场核对：具体屋角、可见构件与计数范围须由老师确认。\n资料来源：故宫博物院 https://www.dpm.org.cn/explore/building/236465.html',
      objective='从全景定位屋角，在特写中辨认和计数。',instruction='在老师指定的地面观察位置，先指出全景图标记的屋角，再在特写里找到骑凤仙人，从他身后开始数，不进入限制区域。',
      question='骑凤仙人身后有几只小兽？'),intro='太和殿是明清皇帝举行盛大典礼的地方。今天，我们抬头找找屋角的小兽。')]


HISTORY_PLACEHOLDER = '【待补充历史背景】'


def research_material(text):
    history=[];observation=[];fallback=[]
    text=re.sub(r'[；;]\s*(?=(?:历史背景|地方历史|历史资料|历史|观察重点|构件特点|构件知识|资料来源|参考来源|来源|现场核对|待老师核对|待核对|注意)[:：])','\n',text)
    for line in text.splitlines():
        line=line.strip()
        if not line or re.match(r'^(资料来源|参考来源|来源|现场核对|待老师核对|待核对|注意)[:：]',line):continue
        # Sources and preparation notes are never spoken narration.
        line=re.sub(r'https?://\S+','',line).strip()
        historical=re.match(r'^(历史背景|地方历史|历史资料|历史)[:：]\s*(.+)',line)
        observed=re.match(r'^(观察重点|构件特点|构件知识)[:：]\s*(.+)',line)
        if historical:history.extend(re.split(r'[。！？!?]',historical[2]))
        elif observed:observation.extend(re.split(r'[。！？!?]',observed[2]))
        else:
            for sentence in re.split(r'[。！？!?]',line):
                if re.search(r'始建|重建|修缮|历史|曾是|曾经|朝代|北宋|南宋|明代|清代|清康熙|[0-9]{3,4}年',sentence):fallback.append(sentence)
    return ([x.strip() for x in (history or fallback) if x.strip()],[x.strip() for x in observation if x.strip()])


def research_excerpt(text):
    history,observation=research_material(text)
    return (history[0] if history else '',observation[0] if observation else '')


def script_from_station(station,timing=None):
    timing=Timing.model_validate(timing or {}).model_dump()
    histories,observations=research_material(station['checked_description'])
    history=histories[0] if histories else '';observation=observations[0] if observations else ''
    if history:
        case=next((c for c in CASES if c['station']['building']==station['building'] and c['station']['component']==station['component'] and history.rstrip('。')==c['history'].rstrip('。')),None)
        if case and timing['intro']<=12:intro=case['intro']
        else:
            prefix='' if case or station['building'] in history else station['building']+'。'
            bridge='今天，我们从'+station['component']+'开始观察。'
            selected=history+'。'
            for fact in histories[1:]:
                if len(prefix+selected+fact+'。'+bridge)<=min(400,timing['intro']*4):selected+=fact+'。'
            intro=prefix+selected+bridge
    else:
        intro=HISTORY_PLACEHOLDER+'请在研学资料中补充一条已核对的地方历史，再引出'+station['component']+'。'
    guidance=observation_guidance(station) or '请对照标注，找到'+station['component']+'。'
    location=(observation+'。' if observation else '')+guidance
    return dict(intro=intro,location=location,task='请指出同一处'+station['component']+'。'+station['question'])
