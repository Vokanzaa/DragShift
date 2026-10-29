from pathlib import Path
from types import SimpleNamespace
import os
import threading

import pytest
from PIL import Image, ImageDraw

from dragshift import video


def frames(folder, count=3):
    paths=[]
    for i in range(count):
        p=folder/f'frame_{i+1}.png'
        image=Image.new('RGB',(64,48),(i,70,180))
        ImageDraw.Draw(image).rectangle((i%50,10,i%50+4,20),fill='white')
        image.save(p)
        paths.append(p)
    return paths


def test_radial_gif_selection_creates_one_animation(qt_session,tmp_path):
    from dragshift.app import DragShiftApp
    from dragshift.radial import Item
    selected=frames(tmp_path)
    outs=[]
    opened=[]
    app=SimpleNamespace(open_window=opened.append,notify=lambda action,srcs,result,*a:outs.extend(result),
                        submit=lambda action,srcs,fn,*a:outs.extend(fn()))
    DragShiftApp.run_item(app,Item('GIF',key='convert:GIF'),list(map(str,selected)))
    if opened:
        opened[0].save()
    assert len(outs)==1
    with Image.open(outs[0]) as image:
        assert image.n_frames==3 and image.info['loop']==0


def test_exact_160_frame_order_and_cumulative_timing(tmp_path):
    from dragshift.gif_sequence import export
    selected=frames(tmp_path,160)
    original=[p.read_bytes() for p in selected]
    out=export(selected,fps=30)[0]
    with Image.open(out) as image:
        assert image.n_frames==160 and image.info['loop']==0
        elapsed=0
        for i in range(160):
            image.seek(i)
            assert image.convert('RGB').getpixel((0,0))==(i,70,180)
            elapsed+=image.info['duration']
            assert abs(elapsed-(i+1)*1000/30)<=5.01
    assert [p.read_bytes() for p in selected]==original


def test_full_hd_control_colors_remain_exact(tmp_path):
    from dragshift.gif_sequence import export
    paths=[]
    for i,value in enumerate((11,15)):
        p=tmp_path/f'hd_{i}.png'
        image=Image.new('RGB',(1920,1080),(value,70,180))
        ImageDraw.Draw(image).rectangle((100,100,140,300),fill='white')
        image.save(p)
        paths.append(p)
    out=export(paths)[0]
    with Image.open(out) as image:
        for i,value in enumerate((11,15)):
            image.seek(i)
            assert image.convert('RGB').getpixel((0,0))==(value,70,180)


def test_natural_name_date_and_manual_order_are_deterministic(tmp_path):
    from dragshift.gif_sequence import ordered_paths
    names=['render_10.png','render_2.png','render_1.png']
    paths=[]
    for i,name in enumerate(names):
        p=tmp_path/name
        p.touch()
        os.utime(p,ns=(1_000_000_000+i*1_000_000_000,1_000_000_000+i*1_000_000_000))
        paths.append(p)
    assert [p.name for p in ordered_paths(paths,'name')]==['render_1.png','render_2.png','render_10.png']
    assert ordered_paths(paths,'date')==paths
    assert ordered_paths(paths,'manual')==paths
    for p in paths:os.utime(p,ns=(3_000_000_000,3_000_000_000))
    assert ordered_paths(paths,'date')==ordered_paths(list(reversed(paths)),'date')


def test_manual_order_and_identical_frames_are_never_dropped(tmp_path):
    from dragshift.gif_sequence import export
    selected=frames(tmp_path)
    selected=[selected[2],selected[0],selected[0],selected[1]]
    out=export(selected,fps=10,loop=False)[0]
    with Image.open(out) as image:
        assert image.n_frames==4 and 'loop' not in image.info
        for i,p in enumerate(selected):
            image.seek(i)
            with Image.open(p) as source:
                assert image.convert('RGB').tobytes()==source.convert('RGB').tobytes()


def test_transparency_and_different_dimensions_do_not_ghost(tmp_path):
    from dragshift.gif_sequence import export
    paths=[]
    for i,size in enumerate([(80,60),(40,30),(80,60)]):
        p=tmp_path/f'{i}.png'
        frame=Image.new('RGBA',size,(0,0,0,0))
        ImageDraw.Draw(frame).rectangle((i*8,5,i*8+8,15),fill='red')
        frame.save(p)
        paths.append(p)
    out=export(paths)[0]
    with Image.open(out) as image:
        assert image.size==(80,60) and image.n_frames==3
        for i in range(3):
            image.seek(i)
            actual=image.convert('RGBA')
            assert actual.getpixel((79,59))[3]==0
            if i==2:
                assert actual.getpixel((2,10))[3]==0
                assert actual.getpixel((18,10))==(255,0,0,255)


@pytest.mark.parametrize('reason',['bad_later_file','cancel'])
def test_failure_or_cancellation_keeps_no_partial_animation(tmp_path,reason):
    from dragshift.gif_sequence import export
    paths=frames(tmp_path)
    if reason=='bad_later_file':paths[-1].write_bytes(b'bad')
    before=set(tmp_path.iterdir())
    cancel=threading.Event()
    def update(value,text):
        if value>0:cancel.set()
    with video.job_context(video.Control(cancel=cancel,progress=update if reason=='cancel' else lambda *a:None)):
        with pytest.raises(Exception):export(paths)
    assert set(tmp_path.iterdir())==before


def test_animated_inputs_keep_every_composited_frame(tmp_path):
    from dragshift.gif_sequence import export
    paths=[]
    for number,colors in enumerate([('red','blue'),('green','yellow')]):
        p=tmp_path/f'{number}.gif'
        first,second=[Image.new('RGB',(40,30),c) for c in colors]
        first.save(p,save_all=True,append_images=[second],duration=[70,160],loop=0)
        paths.append(p)
    out=export(paths,fps=20)[0]
    with Image.open(out) as image:
        assert image.n_frames==4
        colors=[]
        for index in range(4):
            image.seek(index)
            colors.append(image.convert('RGB').getpixel((0,0)))
            assert image.info['duration']==50
        assert colors==[(255,0,0),(0,0,255),(0,128,0),(255,255,0)]


def test_mid_encode_error_keeps_previous_animation(tmp_path,monkeypatch):
    from dragshift.gif_sequence import export
    from PIL import GifImagePlugin
    paths=frames(tmp_path)
    out=export(paths)[0]
    before={p:p.read_bytes() for p in tmp_path.iterdir()}
    original=GifImagePlugin.getdata
    calls=[]
    def fail(image,**options):
        calls.append(1)
        if len(calls)==2:raise OSError('test encoder failure')
        return original(image,**options)
    monkeypatch.setattr(GifImagePlugin,'getdata',fail)
    with pytest.raises(OSError):export(paths)
    assert {p:p.read_bytes() for p in tmp_path.iterdir()}==before
    assert out.exists()


@pytest.mark.parametrize('fps',[0,101,float('nan'),float('inf')])
def test_invalid_frame_rate_is_rejected_before_writing(tmp_path,fps):
    from dragshift.gif_sequence import export
    paths=frames(tmp_path)
    before=set(tmp_path.iterdir())
    with pytest.raises(Exception):export(paths,fps=fps)
    assert set(tmp_path.iterdir())==before


def test_gap_and_duplicate_notices_never_modify_the_selection():
    from dragshift.gif_sequence import number_notice,ordered_paths
    paths=[Path('shot_3.png'),Path('shot_1.png')]
    assert 'missing' in number_notice(paths)
    assert 'repeat' in number_notice([Path('shot_1.png'),Path('shot_01.jpg')])
    assert not number_notice([Path('shot_1.png'),Path('shot_2.png')])
    assert ordered_paths(paths)==list(reversed(paths))


def test_ui_manual_date_addition_reverse_and_export_use_visible_list(qt_session,tmp_path):
    import time
    from dragshift.gif_sequence_tools import GifSequenceWindow
    paths=frames(tmp_path,12)
    for i,path in enumerate(paths):os.utime(path,ns=((20-i)*10**9,(20-i)*10**9))
    outs=[]
    window=GifSequenceWindow(list(reversed(paths)),lambda action,src,result,*args:outs.extend(result))
    window.show()
    qt_session.processEvents()
    assert not window.grab().isNull()
    assert window.sequence.paths()==paths
    window.order.setCurrentIndex(window.order.findData('date'))
    assert window.sequence.paths()==list(reversed(paths))
    window.order.setCurrentIndex(window.order.findData('added'))
    assert window.sequence.paths()==list(reversed(paths))
    window.order.setCurrentIndex(window.order.findData('name'))
    window.sequence.list.setCurrentRow(0)
    window.sequence.move(1)
    manual=[paths[1],paths[0],*paths[2:]]
    assert window.order.currentData()=='manual' and window.sequence.paths()==manual
    window.receive_files([paths[0]])
    manual.append(paths[0])
    assert window.sequence.paths()==manual  # Adding never re-sorts a manual edit.
    window.reverse()
    manual.reverse()
    assert window.sequence.paths()==manual
    deadline=time.monotonic()+8
    while not window.primary_btn.isEnabled() and time.monotonic()<deadline:
        qt_session.processEvents()
        time.sleep(.01)
    assert window.primary_btn.isEnabled()
    window.save()
    assert len(outs)==1
    with Image.open(outs[0]) as image:
        assert image.n_frames==len(manual)
        for index,path in enumerate(manual):
            image.seek(index)
            with Image.open(path) as source:
                assert image.convert('RGB').getpixel((0,0))==source.convert('RGB').getpixel((0,0))


def test_multiple_gif_inputs_offer_the_animation_action(qt_session):
    from dragshift.app import DragShiftApp
    rings=DragShiftApp.build_rings(None,['one.gif','two.gif'])
    item=next(item for item in rings['Convert'] if item.key=='convert:GIF')
    assert '1 animated GIF' in item.hint


def test_oriented_first_canvas_and_russian_bundled_window(qt_session,tmp_path):
    from dragshift.gif_sequence import export,inspect_frames
    from dragshift.file_check import _check_gif_sequence
    first=tmp_path/'rotated.jpg'
    exif=Image.Exif()
    exif[274]=6
    Image.new('RGB',(80,40),'red').save(first,exif=exif)
    second=tmp_path/'second.png'
    Image.new('RGB',(40,80),'blue').save(second)
    assert inspect_frames([first])[0].size==(40,80)
    with Image.open(export([first,second])[0]) as image:
        assert image.size==(40,80) and image.n_frames==2
        image.seek(1)
        assert image.convert('RGB').getpixel((20,40))==(0,0,255)
    _check_gif_sequence(tmp_path)
