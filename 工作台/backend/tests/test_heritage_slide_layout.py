"""Classroom slide layout keeps copy, attribution and annotation geometry intact."""
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from scenarios.heritage_study import media


@pytest.mark.parametrize('mode',['contain','cover'])
def test_photo_panel_resizing_preserves_shape_and_visible_marks(tmp_path,mode):
    original=Image.new('RGB',(900,1200),'white')
    ImageDraw.Draw(original).rectangle((675,575,725,625),fill='blue')
    original.save(tmp_path/'photo.png')
    before=(tmp_path/'photo.png').read_bytes()
    store=SimpleNamespace(asset=lambda pid,name:tmp_path/name)
    photo=dict(image='photo.png',mode=mode,focus_x=.5,focus_y=.5,
               mark=dict(kind='rectangle',x=.2,y=.4,x2=.6,y2=.55))
    result=media.annotated_photo(store,'project',photo,size=(704,464))
    assert result.size==(704,464)
    pixels=np.asarray(result)
    y,x=np.where((pixels[:,:,2]>200)&(pixels[:,:,0]<50)&(pixels[:,:,1]<50))
    assert len(x)>0 and abs((x.max()-x.min())-(y.max()-y.min()))<=2
    assert ((pixels[:,:,0]>130)&(pixels[:,:,1]<70)&(pixels[:,:,2]<70)).any()
    assert (tmp_path/'photo.png').read_bytes()==before


def test_chinese_wrapping_keeps_text_and_punctuation_together():
    text='请沿柱子向上看（注意安全），找到同一组斗拱。再观察它的连接方式。'
    face=media.font(28)
    wrapped=media.lines(text,face,200)
    assert ''.join(wrapped)==text
    assert all(face.getlength(line)<=200 for line in wrapped)
    assert all(line[0] not in '，。！？；：、）》】」』”’' for line in wrapped)
    assert all(line[-1] not in '（《【「『“‘' for line in wrapped)
    assert face.getname()[1]!='Black'


def test_slide_separates_question_preserves_exact_copy_and_all_photo_credits(tmp_path,monkeypatch):
    Image.new('RGB',(900,1200),'white').save(tmp_path/'photo.png')
    store=SimpleNamespace(asset=lambda pid,name:tmp_path/name)
    station=dict(building='宁波保国寺大殿',name='找斗拱',question='哪一层木构件伸得最远？',
                 panorama=dict(image='photo.png',mode='contain',focus_x=.5,focus_y=.5,mark=None,
                               author='Photo author',license='CC BY-SA 3.0 https://example.test/license',source='https://example.test/photo'))
    guidance='在老师指定位置，沿照片标出的柱子向上找，指出同一组斗拱，再指出向外伸出的部分。'
    seen=[];original=media.block
    def record(draw,text,*args,**kwargs):
        seen.append(text);return original(draw,text,*args,**kwargs)
    monkeypatch.setattr(media,'block',record)
    result=media.photo_frame(store,'project',station,'panorama',guidance+'\n'+station['question'])
    assert result.size==(1280,720)
    assert station['building'] in seen and station['name'] in seen
    assert sum(text==station['question'] for text in seen)==1
    assert any(text.replace('\n','')==guidance for text in seen)
    credit_text=next(text for text in seen if text.startswith('照片：'))
    assert all(station['panorama'][key] in credit_text for key in ('author','license','source'))
