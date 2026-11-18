import json
import sqlite3

import pytest

from scenarios.ink_drama.domain import Store
from test_heritage_workflow import split_fresh
from test_ink_demo import setup


def test_legacy_job_table_migrates_without_replacing_old_records(tmp_path):
    with sqlite3.connect(tmp_path/'ink.sqlite3') as db:
        db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, project TEXT, owner TEXT, action TEXT, state TEXT, error TEXT, created REAL)')
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',('old','p','alice','split','failed','旧错误',12.0))
    store=Store(tmp_path)
    old=store.jobs('p')[0]
    assert {key:value for key,value in old.items() if key!='progress'}==dict(
        id='old',project='p',owner='alice',action='split',state='failed',error='旧错误',created=12.0)
    assert old['progress'] is None
    # Reopening is idempotent; new jobs can be created after the added column.
    store=Store(tmp_path)
    jid=store.enqueue('p','alice','split')
    store.progress(jid,'正在规划分镜',1,3)
    assert store.jobs('p')[0]['progress']['message']=='正在规划分镜'


def test_live_progress_survives_reopen_and_late_updates_cannot_rewrite_completed_jobs(tmp_path):
    store=Store(tmp_path)
    jid=store.enqueue('p','alice','split')
    store.progress(jid,'正在解析资料',0,3)
    assert Store(tmp_path).jobs('p')[0]['progress']['completed']==0
    store.progress(jid,'新分镜已保存',3,3)
    store.finish(jid)
    before=store.jobs('p')[0]
    store.progress(jid,'迟到的进度',1,3)
    assert store.jobs('p')[0]==before


@pytest.mark.parametrize('done,total',[(2,1),(-1,3),(0,0),(0,101),(True,3)])
def test_invalid_stage_counts_are_not_persisted(tmp_path,done,total):
    store=Store(tmp_path);jid=store.enqueue('p','alice','split')
    with pytest.raises(ValueError):store.progress(jid,'测试进度',done,total)
    assert store.jobs('p')[0]['progress'] is None


def test_polling_api_receives_real_split_stages_and_terminal_progress(setup,monkeypatch):
    from models.llm_client import LLM
    from heritage_planner_fixtures import planner_reply
    store,client=setup
    p,base=split_fresh(setup,monkeypatch)
    stages=[]
    def query(self,prompt,**kwargs):
        stages.append(client.get(base).json()['jobs'][0]['progress'])
        return planner_reply(prompt)
    monkeypatch.setattr(LLM,'query',query)
    assert client.post(base+'/actions/split').status_code==200
    result=client.get(base).json()
    assert len(stages)==2 and [stage['completed'] for stage in stages]==[0,1]
    assert '解析' in stages[0]['message'] and '画面与运镜' in stages[1]['message']
    assert result['jobs'][0]['state']=='completed'
    assert result['jobs'][0]['progress']['completed']==3
    assert result['jobs'][0]['progress']['message']=='新分镜已保存'
    assert result['storyboard_draft'] and result['shots']==p['shots']
