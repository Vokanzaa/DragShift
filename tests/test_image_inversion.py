from PIL import Image
import pytest

from dragshift import imaging,tools


@pytest.mark.parametrize('mode',['RGB','RGBA','P'])
def test_inversion_preserves_alpha_and_two_inversions_restore_pixels(mode):
    source=Image.new('RGBA',(12,10),(10,80,240,73))
    if mode=='RGB':source=source.convert('RGB')
    elif mode=='P':
        source=source.convert('P',palette=Image.Palette.ADAPTIVE)
        source.info['transparency']=0
    before=source.convert('RGBA')
    inverted=imaging.apply_adjust(source,imaging.Adjust(invert=True))
    expected_alpha=before.getpixel((0,0))[3]
    assert inverted.convert('RGBA').getpixel((0,0))==(245,175,15,expected_alpha)
    restored=imaging.apply_adjust(inverted,imaging.Adjust(invert=True))
    assert restored.convert('RGBA').tobytes()==before.tobytes()


def test_edit_button_applies_to_complete_series_and_reset(qt_session,tmp_path):
    paths=[]
    for index,color in enumerate(((10,80,240,73),(150,60,0,255))):
        path=tmp_path/f'frame-{index}.png'
        Image.new('RGBA',(100,80),color).save(path)
        paths.append(path)
    window=tools.EditWindow(paths,lambda *_:None)
    window.show()
    window.invert.click()
    assert window._collect(False).invert
    calls=[]
    window.run=lambda fn,*args:calls.append(fn())
    window.save()
    assert len(calls[0])==2
    for source,output in zip(paths,calls[0]):
        with Image.open(source) as a,Image.open(output) as b:
            r,g,blue,alpha=a.getpixel((0,0))
            assert b.convert('RGBA').getpixel((0,0))==(255-r,255-g,255-blue,alpha)
    window.reset()
    assert not window.invert.isChecked() and not window._collect(False).invert
    window.close()


def test_invert_gif_preserves_all_frames_and_delays(tmp_path):
    source=tmp_path/'animation.gif'
    Image.new('RGB',(20,20),'red').save(source,save_all=True,
        append_images=[Image.new('RGB',(20,20),'blue')],duration=[80,170],loop=0)
    output=imaging.edit_image(source,imaging.Adjust(invert=True))
    with Image.open(output) as image:
        assert image.n_frames==2
        assert image.convert('RGB').getpixel((0,0))==(0,255,255)
        assert image.info['duration']==80
        image.seek(1)
        assert image.convert('RGB').getpixel((0,0))==(255,255,0)
        assert image.info['duration']==170


@pytest.mark.parametrize('editor',[tools.EditWindow,tools.AddBgWindow])
def test_closing_before_queued_preview_does_not_access_deleted_controls(qt_session,tmp_path,monkeypatch,editor):
    import sys
    from PySide6.QtCore import QCoreApplication,QEvent
    source=tmp_path/'selected.png';Image.new('RGB',(80,60),'red').save(source)
    errors=[]
    monkeypatch.setattr(sys,'excepthook',lambda kind,error,tb:errors.append(str(error)))
    for _ in range(3):
        window=editor([source],lambda *_:None)
        window.show();window.close()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        qt_session.processEvents()
    assert not errors
