"""Structured simulated model replies; no live provider calls in tests."""
import json


def planner_reply(prompt):
    data=json.loads(prompt.split('\n输入数据：',1)[1])
    if prompt.startswith('阶段1：'):
        facts=[]
        for term in ('大殿','斗拱','木构','柱子','保国寺','石狮','柱础','屋角','脊兽','建筑','藻井','天花','前槽','拼合柱'):
            for source,text in data['sources'].items():
                if term in text:
                    start=text.index(term)
                    facts.append(dict(id=f'f{len(facts)+1}',source=source,
                                      quote=text[max(0,start-12):start+len(term)+24],elements=[term]))
                    break
        if not facts:
            text=data['sources']['narration']
            facts=[dict(id='f1',source='narration',quote=text,elements=[text[:2]])]
        return json.dumps(dict(facts=facts,limitations=['照片未进行视觉识别']),ensure_ascii=False)
    if prompt.startswith('阶段2：'):
        facts=[fact for fact in data['analysis']['facts'] if fact['elements']];scene=data['settings']['scenes'][0]['id']
        views=[('全景，平视','整体位于画面中央，两侧保留已知空间'),
               ('中景，侧视','一侧相接部位成为主体，取景收紧到可见边界'),
               ('特写，略仰视','外缘与相邻木构并排，展示层叠轮廓'),
               ('近景，平视','与梁端的接触位置清楚，下方保留连接线索'),
               ('中景，沿柱略仰视','定位关系贯穿画面，柱线引向观察目标'),
               ('特写，侧视','前后层次分明，画面只保留本镜观察区域')]
        shots=[]
        entered=False
        for i,node in enumerate(data['narration']):
            stop=data['visit_route'][i];stage=stop['stage']
            if stage=='interior':entered=True
            fact=facts[i%len(facts)];element=fact['elements'][0];camera,visual=views[i%len(views)]
            space='interior' if entered else 'entrance' if stage=='entrance' else 'exterior'
            viewpoint={'overview':'在建筑外观察整体','approach':'走近建筑观察主体','entrance':'在入口观察相接关系','interior':'在殿内观察资料所述空间','structure':'在殿内观察构造' if entered else '在主体附近观察构造','detail':'在殿内观察构件细节' if entered else '走近构件观察细节'}[stage]
            if entered:
                fact=next(fact for fact in facts if fact['id'] in data['interior_fact_ids'])
                element=fact['elements'][0]
            if stage=='overview':camera='全景，平视'
            elif stage in {'structure','detail'}:camera='近景，略仰视' if stage=='structure' else '特写，平视'
            shots.append(dict(index=i,topic=f'资料主题{i+1}',subject=element+'观察',focus_element=element,
                              visit_stage=stage,view_space=space,viewpoint=viewpoint,
                              guide_position='位于画面一侧，不遮挡建筑' if data.get('guide',{}).get('enabled') and stage in {'overview','approach','entrance'} else '',
                              guide_action='抬手示意观察后自然放下。' if data.get('guide',{}).get('enabled') and stage in {'overview','approach','entrance'} else '',
                              fact_ids=[fact['id']],scene_id=scene,
                              prop_ids=[p['id'] for p in data['settings'].get('props',[]) if p['name']==element],
                              camera=camera,visual=viewpoint+'，'+element+visual+'。'))
        return json.dumps(dict(shots=shots),ensure_ascii=False)
    raise AssertionError('Unexpected extra model call')
