"""The displayed keyframes are the exact absolute curve sent to the engine."""

import json
import random
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest

from dragshift.distortion_curve import DistortionCurve


@pytest.fixture
def editor(qt_session):
    widget = DistortionCurve(duration=12)
    widget.resize(640, 370)
    widget.show()
    qt_session.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def _position(editor, time, strength):
    position = editor.curve.position((time, strength/95))
    return QPoint(round(position.x()), round(position.y()))


def test_default_absolute_strength_and_json_contract(editor):
    assert editor.points() == [[0., 40.], [1., 40.]]
    assert json.loads(json.dumps(editor.points())) == editor.points()
    assert editor.level.value() == 40
    assert editor.level.minimum() == 0 and editor.level.maximum() == 95
    assert '%' not in editor.level.suffix()
    assert editor.time.suffix().strip() == 's'
    assert editor.time.maximum() == 12
    assert not editor.time.isEnabled()
    assert not editor.randomize.isChecked()
    assert not editor.variation.isEnabled()


def test_first_click_and_double_click_add_once_without_moving_old_points(editor):
    before = editor.points()
    position = _position(editor, .43, 72)
    QTest.mouseClick(editor.curve, Qt.LeftButton, pos=position)
    QTest.mouseDClick(editor.curve, Qt.LeftButton, pos=position)
    assert len(editor.points()) == 3
    assert editor.points()[0] == before[0]
    assert editor.points()[-1] == before[-1]
    assert editor.points()[1][0] == pytest.approx(.43, abs=.002)
    assert editor.points()[1][1] == pytest.approx(72, abs=.5)
    assert editor.time.value() == pytest.approx(editor.points()[1][0]*12, abs=.01)


def test_selected_numeric_strength_is_actual_and_keeps_precise_time(editor):
    editor.set_points([[0, 40], [.314159, 72], [1, 15]])
    editor.select(1)
    editor.level.setValue(40)
    assert editor.points()[1] == [.314159, 40]
    editor.time.setValue(6)
    assert editor.points()[1] == [.5, 40]
    assert editor.points()[0] == [0, 40] and editor.points()[-1] == [1, 15]
    assert editor.selected_strength() == 40
    editor.set_strength(95)
    assert editor.points()[1] == [.5, 95]


def test_drag_changes_time_and_strength_then_keyboard_uses_seconds(editor):
    editor.set_points([[0, 40], [.3, 30], [1, 40]])
    QTest.mousePress(editor.curve, Qt.LeftButton, pos=_position(editor, .3, 30))
    QTest.mouseMove(editor.curve, _position(editor, .65, 80))
    QTest.mouseRelease(editor.curve, Qt.LeftButton, pos=_position(editor, .65, 80))
    x, strength = editor.points()[1]
    assert x == pytest.approx(.65, abs=.002)
    assert strength == pytest.approx(80, abs=.5)
    QTest.keyClick(editor.curve, Qt.Key_Right)
    QTest.keyClick(editor.curve, Qt.Key_Up)
    assert editor.points()[1][0]*12 == pytest.approx(x*12+.01)
    assert editor.points()[1][1] == pytest.approx(strength+1)


def test_programmatic_playhead_and_duration_do_not_change_stored_curve(editor):
    changed, sought = [], []
    editor.changed.connect(changed.append)
    editor.playheadMoved.connect(sought.append)
    before = editor.points()
    editor.set_playhead(4.2)
    editor.set_duration(24)
    assert editor.curve.playhead == 4.2
    assert '4.20' in editor.playhead_label.text()
    assert editor.time.value() == 0
    assert editor.points() == before
    assert changed == [] and sought == []
    r = editor.curve.area()
    QTest.mouseClick(editor.curve, Qt.LeftButton, pos=QPoint(round(r.center().x()), 10))
    assert sought[-1] == pytest.approx(12, abs=.04)
    assert changed == [] and editor.points() == before


def test_selecting_clicking_and_editing_keyframe_seek_to_its_time(editor):
    editor.set_points([[0, 40], [.25, 70], [.75, 20], [1, 40]])
    changed, sought = [], []
    editor.changed.connect(changed.append)
    editor.playheadMoved.connect(sought.append)
    editor.select(1)
    assert sought == [3]
    assert editor.curve.playhead == 3 and changed == []
    editor.next.click()
    assert sought == [3, 9]
    assert editor.curve.playhead == 9 and changed == []
    QTest.mouseClick(editor.curve, Qt.LeftButton, pos=_position(editor, .25, 70))
    assert sought == [3, 9, 3] and changed == []
    editor.time.setValue(5)
    assert sought[-1] == 5 and editor.curve.playhead == 5
    editor.set_playhead(10)
    editor.level.setValue(50)
    assert sought[-1] == 5 and editor.curve.playhead == 5
    QTest.mousePress(editor.curve, Qt.LeftButton, pos=_position(editor, 5/12, 50))
    QTest.mouseMove(editor.curve, _position(editor, .6, 80))
    QTest.mouseRelease(editor.curve, Qt.LeftButton, pos=_position(editor, .6, 80))
    assert sought[-1] == pytest.approx(7.2, abs=.03)
    assert editor.curve.playhead == pytest.approx(editor.points()[1][0]*12)
    sought.clear()
    editor.set_points([[0, 25], [.5, 75], [1, 10]])
    assert sought == []


def test_add_at_playhead_interpolates_and_remove_has_keyboard_alternative(editor):
    editor.set_points([[0, 10], [1, 90]])
    editor.set_playhead(3)
    editor.add_keyframe.click()
    assert len(editor.points()) == 3
    assert editor.points()[1] == pytest.approx([.25, 30])
    editor.add_keyframe.click()
    assert len(editor.points()) == 3
    editor.next.click()
    assert not editor.remove_keyframe.isEnabled()
    editor.previous.click()
    assert editor.remove_keyframe.isEnabled()
    QTest.keyClick(editor.curve, Qt.Key_Delete)
    assert editor.points() == [[0, 10], [1, 90]]


def test_numeric_time_never_crosses_adjacent_points(editor):
    editor.set_points([[0, 0], [.2, 25], [.4, 50], [1, 95]])
    editor.select(1)
    editor.time.setValue(11)
    assert editor.points()[0][0] < editor.points()[1][0] < editor.points()[2][0]
    assert editor.points()[1][0]*12 == pytest.approx(4.799)
    # Editing strength must preserve even a time closer than the inspector's
    # two-decimal display precision to its neighboring keyframe.
    x = editor.points()[1][0]
    editor.level.setValue(60)
    assert editor.points()[1] == [x, 60]


def test_randomization_is_one_stored_irregular_editable_curve(editor):
    editor._rng = random.Random(42)
    changed = []
    editor.changed.connect(changed.append)
    editor.randomize.setChecked(True)
    generated = editor.points()
    assert 8 <= len(generated) <= 11
    assert generated[0][0] == 0 and generated[-1][0] == 1
    intervals = [round(right[0]-left[0], 5) for left, right in zip(generated, generated[1:])]
    strengths = [point[1] for point in generated]
    assert len(set(intervals)) > 3
    assert len(set(strengths)) > 3
    assert all(0 <= strength <= 95 for strength in strengths)
    assert len(changed) == 1
    editor.set_playhead(3)
    editor.set_duration(18)
    editor.randomize.setChecked(False)
    assert editor.points() == generated and len(changed) == 1
    # Choosing a fresh variation is the only operation here that consumes RNG.
    editor.randomize.setChecked(True)
    assert editor.points() != generated and len(changed) == 2
    second = editor.points()
    editor.variation.click()
    assert editor.points() != second and len(changed) == 3
    editor.select(2)
    x = editor.points()[2][0]
    editor.level.setValue(40)
    assert editor.points()[2] == [x, 40]
    editor.reset_button.click()
    assert editor.points() == [[0, 40], [1, 40]]
    assert not editor.randomize.isChecked() and not editor.variation.isEnabled()


def test_set_points_copies_input_and_repairs_bounds(editor):
    source = [[1, 110], [.5, -5], [0, 40]]
    editor.set_points(source)
    source[1][1] = 70
    assert editor.points() == [[0, 40], [.5, 0], [1, 95]]
    result = editor.points()
    result[1][1] = 80
    assert editor.points()[1][1] == 0
    editor.set_points([[.4, 50]])
    assert editor.points() == [[0, 50], [.4, 50], [1, 50]]
    editor.set_points([])
    assert editor.points() == [[0, 40], [1, 40]]


def test_timeline_and_inspector_render_without_overlapping_controls(editor, qt_session, tmp_path):
    from dragshift.theme import qss

    previous_style = qt_session.styleSheet()
    # The offscreen Windows platform can have no enumerated system fonts.
    # Load the installed UI face explicitly for a legible visual QA artifact.
    font_path = Path('C:/Windows/Fonts/segoeui.ttf')
    font_id = QFontDatabase.addApplicationFont(str(font_path)) if font_path.exists() else -1
    try:
        qt_session.setStyleSheet(qss())
        editor.set_points([[0, 40], [.14, 77], [.39, 18], [.58, 63], [.82, 25], [1, 52]])
        editor.select(3)
        editor.set_playhead(7.5)
        editor.resize(640, 390)
        qt_session.processEvents()
        assert editor.time.geometry().right() < editor.level.geometry().left()
        assert editor.previous.geometry().right() < editor.next.geometry().left()
        image = editor.grab()
        assert not image.isNull()
        path = tmp_path/'distortion-keyframes.png'
        assert image.save(str(path))
        print(f'Curve render: {path}')
    finally:
        qt_session.setStyleSheet(previous_style)
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)
