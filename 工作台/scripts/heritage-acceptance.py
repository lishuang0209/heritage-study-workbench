"""Offline-model acceptance using a real licensed photo and retained ink clips.
This creates a draft in the new live app, and runs review/export acknowledgements
ONLY in a separate QA data store, never as a real teacher's approval.
"""
import copy
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT.parent/'验证'/'保国寺找斗拱'
QA.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:8012/api/ink'

def request(path,method='GET',data=None):
    body=json.dumps(data,ensure_ascii=False).encode() if data is not None else None
    req=urllib.request.Request(BASE+path,data=body,method=method,headers={'Content-Type':'application/json'} if body else {})
    with urllib.request.urlopen(req,timeout=40) as response:return json.load(response)

old=request('/projects')['projects']
source_id=next(x['id'] for x in old if x.get('project_type','ink')=='ink')
source=request('/projects/'+source_id)
selected=[];duration=0
for shot in source['shots']:
    if shot.get('rendered') and not any(shot.get(k) for k in ('image_stale','clip_stale','rendered_stale')) and duration+shot.get('duration',5)<=12:
        selected.append(shot);duration+=shot.get('duration',5)
if not selected:raise SystemExit('没有可复用的已确认水墨镜头，未自动生成模型内容')

os.environ['SFA_INK_DATA_DIR']=str(QA/'技术验收数据')
sys.path.insert(0,str(ROOT/'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scenarios.ink_drama import api
from scenarios.heritage_study.templates import CASES
from scenarios.heritage_study.domain import snapshot
from scenarios.ink_drama.providers import Providers,ffmpeg_executable
from PyPDF2 import PdfReader

class Immediate:
    def submit(self,fn,*args):fn(*args)
api.pool=Immediate()
app=FastAPI();app.include_router(api.router);client=TestClient(app)

def check(response):
    if response.status_code!=200:raise RuntimeError(response.text)
    return response.json()

p=check(client.post('/api/ink/projects',json={'title':'技术验收-保国寺找斗拱（非现场审核）','script':'复用已有水墨镜头验证交付链路','project_type':'heritage'}))
pid=p['id'];base='/api/ink/projects/'+pid
photo=ROOT.parent/'素材'/'保国寺-大殿东檐.jpg'
p=check(client.post(base+'/heritage/photos/panorama',params={'version':0},files={'file':('baoguo.jpg',photo.read_bytes(),'image/jpeg')}))
station=p['heritage_station'];station.update(CASES[0]['station']);station['name']='找斗拱 · 技术演示待现场核对'
station['panorama'].pop('url',None);station['panorama'].pop('preview_url',None)
station['panorama'].update(source='https://commons.wikimedia.org/wiki/File:Ningbo_Baoguo_Si_2013.07.27_10-34-40.jpg',author='Zhangzhugang',license='CC BY-SA 3.0 https://creativecommons.org/licenses/by-sa/3.0/',mark={'kind':'rectangle','x':.18,'y':.025,'x2':.65,'y2':.25})
p=check(client.put(base+'/heritage/station',json={'version':p['heritage_version'],'station':station}))
# Populate detached QA with local copies of the selected story; no original data mutation.
stored=api.store.load(pid);shots=[]
for s in selected:
    item=copy.deepcopy(s)
    for key in ('image','clip','rendered'):
        if item.get(key):shutil.copy2(ROOT/'backend/.ink-demo/assets'/source_id/item[key],api.store.asset(pid,item[key]))
    shots.append(item)
stored.update(shots=shots,characters=source['characters'],qa_only=True,qa_note='自动技术验收，不代表教师审核或现场验收')
api.store.save(stored)
p=check(client.post(base+'/heritage/confirm',json={'version':p['heritage_version'],'teacher_verified':True}))
p=check(client.post(base+'/heritage/script-template'))
# Short, reviewable sample text; the station remains teacher-supplied/QA-marked.
s= p['heritage_script']
p=check(client.put(base+'/heritage/script',json={'version':s['version'],'station_version':p['heritage_version'],
  'intro':'小木匠顺着柱子往上看，发现有一组木构件，一层层向外伸。我们去实拍照片里找找。',
  'location':'对照照片标出的柱子，往上找到框内的木构件。正式使用前请老师核对。',
  'task':station['instruction']+' '+station['question']}))
p=check(client.post(base+'/heritage/confirm-script',json={'version':p['heritage_script']['version'],'teacher_verified':True}))
p=check(client.post(base+'/heritage/export',json={'version':p['heritage_version'],'kind':'both'}))
assert p['jobs'][0]['state']=='completed',p['jobs'][0]
folder=api.store.folder(pid)
shutil.copy2(folder/p['final'],QA/'保国寺-技术演示30秒.mp4')
shutil.copy2(folder/p['task_card'],QA/'保国寺-观察任务卡-技术演示.pdf')
for label in ('panorama','task'):
    chapter=next(c for c in p['heritage_chapters'] if c['kind']==label)
    frame=(folder/chapter['video']).with_suffix('.png');shutil.copy2(frame,QA/(label+'-竖屏画面.png'))
provider=Providers();assert abs(provider.duration(folder/p['final'])-30)<.1
pdf=PdfReader(str(folder/p['task_card']));assert len(pdf.pages)==1
assert [c['kind'] for c in p['heritage_chapters']]==['story','panorama','task']
assert client.get(p['final_url']).status_code==200
assert client.get(p['task_card_url']).status_code==200
assert not p['final_stale'] and not p['task_card_stale']
# Reopening persists the exact normalized geometry.
reopened=check(client.get(base));assert reopened['heritage_station']['panorama']['mark']==station['panorama']['mark']
# Ordinary ink export on the new code remains unmodified by the station renderer.
legacy=api.store.create('local','普通水墨兼容验收','原有水墨项目')
legacy.update(shots=shots,characters=source['characters']);api.store.save(legacy)
job=api.store.enqueue(legacy['id'],'local','assemble')
for s in shots:
    for key in ('image','clip','rendered'):
        if s.get(key):shutil.copy2(folder/s[key],api.store.asset(legacy['id'],s[key]))
# A real edit through the unchanged ink endpoints, followed by retaining the existing media.
# Finish the queued assembly placeholder while editing; real API guards correctly reject busy writes.
api.store.finish(job)
legacy_base='/api/ink/projects/'+legacy['id']
from scenarios.ink_drama.domain import ShotInput
first=api.store.load(legacy['id'])['shots'][0]
body={key:first.get(key) for key in ShotInput.model_fields}
body['content']+='\n技术兼容验证：保留现有画面。'
edited=check(client.patch(legacy_base+'/shots/'+first['id'],json=body))['shots'][0]
assert edited['image_stale']
confirmed=check(client.post(legacy_base+'/shots/'+first['id']+'/confirm-image',json={'image':edited['image'],'revision':edited['revision']}))['shots'][0]
check(client.post(legacy_base+'/shots/'+first['id']+'/adopt-video',json={'video':first['rendered'],'revision':confirmed['revision'],'current_clip':confirmed['clip']}))
job=api.store.enqueue(legacy['id'],'local','assemble')
api.run_job(job,legacy['id'],{'id':'local','trial_mode':False},'assemble',None)
assert api.store.jobs(legacy['id'])[0]['state']=='completed'
assert 'project_type' not in api.store.load(legacy['id'])
manifest={'type':'technical_acceptance_only','teacher_approval':False,'field_trial':False,
 'paid_model_calls':0,'duration':30,'pdf_pages':1,'chapters':p['heritage_chapters'],
 'same_confirmation_stamp':api.store.load(pid)['heritage_export_stamp']==snapshot(api.store.load(pid)),
 'ordinary_ink_edit':'passed','ordinary_ink_export':'passed','source_project_unchanged':True}
(QA/'技术验收记录.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
# Add a practical unconfirmed sample to the new app. No teacher approval is submitted here.
existing_draft=next((x for x in request('/projects')['projects'] if x['title']=='保国寺 · 找斗拱（待老师核对）'),None)
if existing_draft:
    print(json.dumps({'qa_duration':30,'pdf_pages':1,'legacy_edit_and_export':'passed','existing_draft':existing_draft['id']},ensure_ascii=False));sys.exit(0)
draft=request('/projects','POST',{'project_type':'heritage','title':'保国寺 · 找斗拱（待老师核对）','script':'请选择或编辑研学脚本，真实构件由老师核对。'})
# Import already uploaded QA photo into the new live app's own isolated data via HTTP multipart.
import httpx
with httpx.Client(timeout=40) as http:
 r=http.post(BASE+f"/projects/{draft['id']}/heritage/photos/panorama",params={'version':0},files={'file':('baoguo.jpg',photo.read_bytes(),'image/jpeg')});r.raise_for_status();draft=r.json()
live_station=copy.deepcopy(station);live_station['name']='找斗拱';live_station['panorama']['image']=draft['heritage_station']['panorama']['image']
draft=request(f"/projects/{draft['id']}/heritage/station",'PUT',{'version':draft['heritage_version'],'station':live_station})
draft=request(f"/projects/{draft['id']}/heritage/reuse-story",'POST',{'source_project':source_id,'shot_ids':[s['id'] for s in selected]})
request(f"/projects/{draft['id']}/heritage/script-template",'POST',{})
print(json.dumps({'qa_duration':30,'pdf_pages':1,'legacy_export':'passed','draft_project':draft['id'],'draft_teacher_confirmed':draft['heritage_ready']},ensure_ascii=False),flush=True)
