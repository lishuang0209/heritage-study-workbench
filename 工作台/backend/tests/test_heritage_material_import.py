"""Real in-memory documents, local extraction only, and preview/save boundaries."""
import copy
import io
import zipfile

import pytest
from docx import Document
from PyPDF2 import PdfWriter
from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject

from test_ink_demo import api, setup, example_board
from test_heritage_study import create, prepared, clean
from scenarios.heritage_study import api as study_api
from scenarios.heritage_study import material_import
from scenarios.heritage_study.material_import import extract_material, MAX_FILE_BYTES, MAX_MATERIAL_CHARACTERS
from scenarios.heritage_study.templates import research_material
from scenarios.ink_drama.domain import UserError


def word():
    document=Document();document.add_heading('保国寺研学资料',0)
    document.add_paragraph('历史背景：保国寺大殿重建于1013年。')
    table=document.add_table(rows=1,cols=2)
    table.cell(0,0).text='观察重点：斗拱';table.cell(0,1).text='层叠连接的木构件'
    document.add_paragraph('资料来源：课程老师提供的资料')
    output=io.BytesIO();document.save(output);return output.getvalue()


def pdf(texts, encrypted=False):
    writer=PdfWriter()
    for text in texts:
        writer.add_blank_page(width=600,height=800)
        page=writer.pages[-1]
        if text is not None:
            face=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(face)})})
            stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 50 700 Td ({text}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')]=writer._add_object(stream)
    if encrypted:writer.encrypt('test-password')
    output=io.BytesIO();writer.write(output);return output.getvalue()


@pytest.mark.parametrize('encoding',['utf-8-sig','utf-16','gb18030'])
def test_txt_preserves_chinese_dates_and_paragraphs_for_common_encodings(encoding):
    text='历史背景：保国寺大殿重建于1013年。\r\n观察重点：斗拱。'
    result=extract_material(text.encode(encoding),'资料.TXT')
    assert result['text']==text.replace('\r\n','\n')
    assert result['format']=='txt' and result['characters']==len(result['text'])


def test_docx_extracts_paragraphs_tables_in_order_without_executing_or_extracting_files():
    result=extract_material(word(),r'C:\fakepath\保国寺.docx')
    assert result['filename']=='保国寺.docx'
    text=result['text']
    assert text.index('1013年')<text.index('观察重点：斗拱')<text.index('层叠连接')<text.index('资料来源')
    assert not result['warnings'] and result['pages'] is None


def test_pdf_extracts_text_layer_and_reports_blank_or_scanned_pages():
    result=extract_material(pdf(['Baoguo Temple was rebuilt in 1013.',None]),'Baoguo.pdf')
    assert 'rebuilt in 1013' in result['text'] and result['pages']==2
    assert len(result['warnings'])==1 and '1页' in result['warnings'][0]


@pytest.mark.parametrize('filename,data,message',[
    ('old.doc',b'legacy','另存为.docx'),('image.png',b'image','请上传Word'),
    ('empty.txt',b'','为空'),('spaces.txt',b' \n \t ','未提取到'),
    ('binary.txt',b'\x00\x01','编码无法识别'),('fake.pdf',b'not pdf','不是PDF'),
    ('broken.docx',b'not a zip','Word文档无法读取'),
])
def test_invalid_documents_fail_with_actionable_messages(filename,data,message):
    with pytest.raises(UserError,match=message):extract_material(data,filename)


def test_scanned_encrypted_oversized_and_long_documents_are_not_silently_accepted_or_truncated(monkeypatch):
    with pytest.raises(UserError,match='扫描版PDF'):extract_material(pdf([None]),'scan.pdf')
    with pytest.raises(UserError,match='加密PDF'):extract_material(pdf(['Private text'],True),'locked.pdf')
    with pytest.raises(UserError,match='10MB'):extract_material(b'a'*(MAX_FILE_BYTES+1),'large.txt')
    with pytest.raises(UserError,match='未截断资料'):extract_material(('文'*(MAX_MATERIAL_CHARACTERS+1)).encode(),'long.txt')
    monkeypatch.setattr(material_import,'MAX_PDF_PAGES',1)
    with pytest.raises(UserError,match='最多支持1页'):extract_material(pdf(['one','two']),'long.pdf')
    monkeypatch.setattr(material_import,'MAX_XML_BYTES',64)
    with pytest.raises(UserError,match='解压后过大'):extract_material(word(),'compressed.docx')


def test_invalid_word_xml_and_non_word_archive_have_clear_errors():
    for name,content,message in [('word/document.xml',b'<broken','无法读取'),('random.txt',b'hello','不是有效')]:
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr(name,content)
        with pytest.raises(UserError,match=message):extract_material(output.getvalue(),'bad.docx')


def test_material_preview_never_writes_current_project_or_calls_models(setup,monkeypatch):
    store,client=setup;p=prepared(setup)
    def unexpected(*args,**kwargs):pytest.fail('Uploading material must not call a model')
    monkeypatch.setattr(api,'call',unexpected)
    before=store.load(p['id']);files=set(store.folder(p['id']).iterdir())
    path=f'/api/ink/projects/{p["id"]}/heritage/material/preview'
    response=client.post(path,params={'version':p['heritage_version']},files={'file':('course.docx',word(),'application/octet-stream')})
    assert response.status_code==200,response.text
    assert '1013年' in response.json()['text']
    assert store.load(p['id'])==before and set(store.folder(p['id']).iterdir())==files
    assert store.usage('alice')=={} and not store.jobs(p['id'])
    failure=client.post(path,params={'version':p['heritage_version']},files={'file':('scan.pdf',pdf([None]),'application/pdf')})
    assert failure.status_code==422 and '扫描版' in failure.json()['detail']
    assert store.load(p['id'])==before


@pytest.mark.parametrize('block',['owner','ended','busy','version','ink','unauthenticated'])
def test_preview_respects_project_type_permissions_busy_and_saved_revision(setup,block, monkeypatch):
    store,client=setup;p=create(client);version=0
    expected=403
    if block=='owner':
        monkeypatch.setenv('SFA_INK_SHARED_PROJECT_IDS', p['id'])
        client.post('/api/ink/login',json={'token':'bob-test'})
    elif block=='ended':client.post('/api/ink/end-trial')
    elif block=='busy':store.enqueue(p['id'],'alice','split');expected=409
    elif block=='version':version=99;expected=409
    elif block=='ink':
        stored=store.load(p['id']);stored['project_type']='ink';store.save(stored);expected=422
    else:client.cookies.clear();expected=401
    response=client.post(f'/api/ink/projects/{p["id"]}/heritage/material/preview',params={'version':version},files={'file':('data.txt',b'History facts','text/plain')})
    assert response.status_code==expected,response.text


def test_revision_change_during_extraction_rejects_stale_preview(setup,monkeypatch):
    store,client=setup;p=create(client)
    def changed(data,filename):
        current=store.load(p['id']);current['heritage_version']=1;store.save(current)
        return extract_material(data,filename)
    monkeypatch.setattr(study_api,'extract_material',changed)
    response=client.post(f'/api/ink/projects/{p["id"]}/heritage/material/preview',params={'version':0},files={'file':('data.txt',b'History text','text/plain')})
    assert response.status_code==409
    assert store.load(p['id'])['heritage_station']['checked_description']==''


def test_long_import_saves_after_user_action_and_existing_history_source_does_not_hide_new_facts(setup):
    store,client=setup;p=prepared(setup)
    current=store.load(p['id']);current.update(example_board());store.save(current)
    before_shots=copy.deepcopy(current['shots'])
    text='保国寺大殿重建于1013年。\n2001年，技术测试资料记载一次调查。\n'+('观察重点：请核对照片中的木构件。\n'*100)
    base=f'/api/ink/projects/{p["id"]}'
    preview=client.post(base+'/heritage/material/preview',params={'version':p['heritage_version']},files={'file':('history.txt',text.encode(),'text/plain')}).json()
    station=clean(p['heritage_station'])
    station['checked_description']+='\n\n资料内容：\n'+preview['text']+'\n资料来源：上传文件《history.txt》'
    assert len(station['checked_description'])>1500
    response=client.put(base+'/heritage/station',json={'version':p['heritage_version'],'station':station})
    assert response.status_code==200,response.text
    saved=store.load(p['id']);assert saved['shots']==before_shots
    assert saved['heritage_station']['checked_description']==station['checked_description']
    assert not response.json()['heritage_ready']
    history,observations=research_material(station['checked_description'])
    assert any('1013年' in fact for fact in history) and any('2001年' in fact for fact in history)
    assert all('history.txt' not in fact for fact in history)
    too_long={**station,'checked_description':'文'*(MAX_MATERIAL_CHARACTERS+1)}
    assert client.put(base+'/heritage/station',json={'version':saved['heritage_version'],'station':too_long}).status_code==422
    assert store.load(p['id'])['heritage_station']['checked_description']==station['checked_description']
