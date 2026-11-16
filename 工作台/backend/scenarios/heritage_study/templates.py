"""Only teacher-provided facts enter the editable educational narrative."""
CASES = [
 dict(id='baoguo', title='保国寺 · 找斗拱', station=dict(building='宁波保国寺大殿',name='找斗拱',component='斗拱',
      grade='小学三至六年级',standing_position='由老师现场选定的大殿外安全观察位置，沿照片标出的柱子向上看。',
      checked_description='待老师核对：沿柱子上方观察一组层层向外伸出的木构件。保国寺现状包含清代加建外檐，应核对照片视角与目标构件。',
      objective='沿实拍图的柱子向上找到同一组斗拱，并观察向外伸出的部分。',
      instruction='沿照片标出的柱子向上找，指出同一组斗拱，再指出向外伸出的部分。',question='哪一层木构件伸得最远？'),
      intro='小木匠顺着柱子往上看，发现一组木构件，一层层往外伸。它藏在哪里？我们一起去找找。'),
 dict(id='ningyuan',title='宁远文庙 · 找石狮柱础',station=dict(building='宁远文庙大成殿',name='找石狮柱础',component='石狮柱础',
      grade='小学三至六年级',standing_position='老师选定角柱外侧的安全位置，不触摸或攀爬。',
      checked_description='待老师核对：目标是同一根角柱下的石狮柱础，使用该角柱全景和柱脚近照。',
      objective='由角柱定位柱脚，观察石狮形象。',instruction='先找到照片里的角柱，再看柱子和地面之间。',
      question='你最先认出的是石狮的脸、爪子，还是身体轮廓？'),intro='小木匠发现，柱子脚下似乎藏着一个小伙伴。先沿着柱子往下看，再仔细观察它的轮廓。'),
 dict(id='taihe',title='太和殿 · 找屋角小兽',station=dict(building='故宫太和殿',name='找屋角小兽',component='骑凤仙人与脊兽',
      grade='小学三至六年级',standing_position='老师选定能观察指定屋角的地面安全位置，不进入限制区域。',
      checked_description='待老师核对：用地面全景定位同一屋角，再以对应特写辨认骑凤仙人与其后的脊兽。',
      objective='从全景定位屋角，在特写中辨认和计数。',instruction='先指出全景图标记的屋角，再在特写里找到骑凤仙人，从他身后开始数。',
      question='骑凤仙人身后有几只小兽？'),intro='小木匠抬头发现，屋角上似乎排着一支小队伍。谁在前面，谁在后面？先找到老师指定的屋角。')]


def script_from_station(station):
    return dict(intro='小木匠来到'+station['building']+'。今天的观察目标是'+station['component']+'。'+station['checked_description'],
                location='站在'+station['standing_position']+'请对照标注，找到'+station['component']+'。',
                task=station['instruction']+' '+station['question'])
