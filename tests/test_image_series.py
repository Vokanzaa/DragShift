from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QRectF

from dragshift import imaging, tools


@pytest.fixture
def images(tmp_path):
    paths=[]
    for name,size,color in [('first.png',(160,120),'red'),('second.png',(320,240),'blue'),
                            ('third.png',(80,160),'green')]:
        path=tmp_path/name
        Image.new('RGB',size,color).save(path)
        paths.append(path)
    return paths


def saved(window,method):
    result=[]
    window.notify=lambda action,paths,outs,*extra:result.extend(outs)
    getattr(window,method)()
    return result


def test_crop_series_scales_area_and_preserves_every_gif_frame(qt_session,images,tmp_path):
    gif=tmp_path/'animated.gif'
    Image.new('RGB',(160,120),'red').save(gif,save_all=True,
        append_images=[Image.new('RGB',(160,120),'blue')],duration=[80,170],loop=2)
    window=tools.CropWindow(images[:2]+[gif],lambda *args:None)
    window.view.sel=QRectF(40,30,80,60)
    outs=saved(window,'apply')
    assert len(outs)==3
    assert [Image.open(p).size for p in outs]==[(80,60),(160,120),(80,60)]
    with Image.open(outs[-1]) as output:
        assert output.n_frames==2 and output.info['loop']==2
        assert output.info['duration']==80
        output.seek(1)
        assert output.info['duration']==170 and output.convert('RGB').getpixel((10,10))[2]>240


def test_edit_series_applies_shared_adjustments_to_all(qt_session,images):
    originals=[p.read_bytes() for p in images]
    window=tools.EditWindow(images,lambda *args:None)
    window.gray.setChecked(True)
    window.size_sl.setValue(50)
    window._rot(90)
    outs=saved(window,'save')
    assert [Image.open(p).size for p in outs]==[(60,80),(120,160),(80,40)]
    for out in outs:
        color=Image.open(out).convert('RGB').getpixel((0,0))
        assert color[0]==color[1]==color[2]
    assert [p.read_bytes() for p in images]==originals


def test_redact_series_maps_rectangles_to_each_canvas(qt_session,images):
    window=tools.RedactWindow(images,lambda *args:None)
    window.view.rects=[QRectF(40,30,80,60)]
    outs=saved(window,'save')
    assert len(outs)==3
    for path in outs:
        with Image.open(path) as output:
            w,h=output.size
            assert output.convert('RGB').getpixel((w//2,h//2))==(0,0,0)
            assert output.convert('RGB').getpixel((0,0))!=(0,0,0)


def test_background_series_uses_same_padding_ratio(qt_session,images):
    window=tools.AddBgWindow(images,lambda *args:None)
    window.pad.setValue(10)
    window.rad.setValue(0)
    window.sha.setValue(0)
    window.colors=['#ffffff']
    outs=saved(window,'save')
    assert [Image.open(p).size for p in outs]==[(192,152),(384,304),(112,192)]


def test_annotate_series_maps_same_mark_to_different_sizes(qt_session,images):
    import numpy as np
    window=tools.AnnotateWindow(images,lambda *args:None)
    window.view.shapes=[tools.Shape('Step','#ffffff',4,[QPointF(80,60)],'1')]
    outs=saved(window,'save')
    assert len(outs)==3
    for path in outs:
        with Image.open(path) as output:
            # Test the actual circle's position/size. The numeral's font and
            # antialiasing differ between native Windows, Linux and Mac fonts.
            white=np.all(np.asarray(output.convert('RGB'))>240,axis=2)
            ys,xs=np.where(white)
            radius=max(10.,4*3.2*min(output.width/160,output.height/120))
            assert len(xs)>50
            assert abs((xs.min()+xs.max())/2-output.width/2)<2
            assert abs((ys.min()+ys.max())/2-output.height/2)<2
            assert abs((xs.max()-xs.min())/2-radius)<3
            assert abs((ys.max()-ys.min())/2-radius)<3


def test_metadata_series_strips_every_source(qt_session,tmp_path):
    paths=[]
    for name in ('one.jpg','two.jpg'):
        path=tmp_path/name
        exif=Image.Exif()
        exif[315]='Example photographer'
        Image.new('RGB',(40,30),'red').save(path,exif=exif)
        paths.append(path)
    window=tools.MetadataWindow(paths,lambda *args:None)
    outs=saved(window,'strip')
    assert len(outs)==2
    assert all(not Image.open(p).getexif() for p in outs)
    assert all(Image.open(p).getexif().get(315) for p in paths)


def test_crop_series_rolls_back_earlier_results_on_later_failure(qt_session,images):
    window=tools.CropWindow(images[:2],lambda *args:None)
    images[1].write_bytes(b'invalid image')
    before=set(images[0].parent.iterdir())
    with pytest.raises(Exception):
        window.apply()
    assert set(images[0].parent.iterdir())==before
    assert images[0].exists()
    window.close()


@pytest.mark.parametrize('name',['Crop','Edit','Add BG','Annotate','Redact','Metadata'])
def test_radial_opens_one_editor_for_the_complete_selection(qt_session,images,name):
    from types import SimpleNamespace
    from dragshift.app import DragShiftApp
    from dragshift.radial import Item
    opened=[]
    app=SimpleNamespace(open_window=opened.append,notify=lambda *args:None)
    DragShiftApp.run_item(app,Item(name,key='tool:'+name),list(map(str,images)))
    assert len(opened)==1 and opened[0].paths==images
    opened[0].show()
    qt_session.processEvents()
    assert not opened[0].grab().isNull()
    opened[0].close()


def test_multifile_drop_replaces_the_whole_image_series(qt_session,images):
    window=tools.EditWindow(images[0],lambda *args:None)
    opened=[]
    window.replacement_handler=opened.append
    window.receive_files(images[1:])
    assert len(opened)==1 and opened[0].paths==images[1:]
    opened[0].close()


def test_crop_series_accounts_for_exif_and_rotation(qt_session,images,tmp_path):
    path=tmp_path/'portrait.jpg'
    exif=Image.Exif()
    exif[274]=6
    Image.new('RGB',(200,100),'blue').save(path,exif=exif)
    window=tools.CropWindow([images[0],path],lambda *args:None)
    window._rotate(90)
    window.view.sel=QRectF(30,40,60,80)
    outs=saved(window,'apply')
    assert [Image.open(p).size for p in outs]==[(60,80),(100,50)]


def test_fixed_crop_ratio_is_preserved_on_another_aspect(qt_session,images):
    window=tools.CropWindow([images[0],images[-1]],lambda *args:None)
    window.view.sel=QRectF(40,20,80,80)
    window.view.ratio=1.
    outs=saved(window,'apply')
    assert [Image.open(p).size for p in outs]==[(80,80),(40,40)]


@pytest.mark.parametrize('mode',['Resize','Compress'])
def test_existing_series_tools_roll_back_on_later_failure(qt_session,images,mode):
    window=getattr(tools,mode+'Window')(images[:2],lambda *args:None)
    images[1].write_bytes(b'not an image')
    before=set(images[0].parent.iterdir())
    with pytest.raises(Exception):
        window.save()
    assert set(images[0].parent.iterdir())==before
    window.close()


def test_batch_cancel_rolls_back_completed_image(qt_session,images):
    import threading
    from dragshift import image_series,video
    cancel=threading.Event()
    before=set(images[0].parent.iterdir())
    def process(path):
        output=imaging.resize_image(path,(40,30))
        cancel.set()
        return output
    with video.job_context(video.Control(cancel=cancel)):
        with pytest.raises(Exception):
            image_series.apply(images[:2],process)
    assert set(images[0].parent.iterdir())==before
