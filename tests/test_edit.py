import pytest

from forge.edit import EditError, EditSession, apply_action
from forge.spec import Hole, PartSpec


@pytest.fixture
def plate():
    return PartSpec([(0, 0), (100, 0), (100, 40), (0, 40)], [Hole(20, 20, 5)], thickness=5, name="plate")


def test_set_thickness(plate):
    assert apply_action(plate, {"action": "set_thickness", "value": 8}).thickness == 8
    assert plate.thickness == 5   # original untouched


def test_add_hole_and_rejections(plate):
    new = apply_action(plate, {"action": "add_hole", "diameter": 5, "x": 80, "y": 20})
    assert len(new.holes) == 2
    with pytest.raises(EditError):   # outside the part
        apply_action(plate, {"action": "add_hole", "diameter": 5, "x": 150, "y": 20})
    with pytest.raises(EditError):   # too close to the edge
        apply_action(plate, {"action": "add_hole", "diameter": 5, "x": 80, "y": 2})
    with pytest.raises(EditError):   # overlaps existing hole
        apply_action(plate, {"action": "add_hole", "diameter": 5, "x": 24, "y": 20})


def test_move_resize_remove(plate):
    moved = apply_action(plate, {"action": "move_hole", "index": 0, "x": 50, "y": 20})
    assert (moved.holes[0].x, moved.holes[0].y) == (50, 20)
    assert apply_action(plate, {"action": "resize_hole", "index": 0, "diameter": 8}).holes[0].diameter == 8
    assert apply_action(plate, {"action": "remove_hole", "index": 0}).holes == []
    with pytest.raises(EditError):
        apply_action(plate, {"action": "remove_hole", "index": 3})


def test_scale(plate):
    scaled = apply_action(plate, {"action": "scale", "factor": 2})
    assert scaled.width == 200 and scaled.holes[0].diameter == 10 and scaled.thickness == 5


@pytest.mark.parametrize("bad", [
    {"action": "fly"}, {"action": "set_thickness"}, {"action": "set_thickness", "value": "thick"},
    {"action": "set_thickness", "value": -1}, {"action": "set_thickness", "value": 5, "extra": 1}, {"value": 5},
])
def test_invalid_actions(plate, bad):
    with pytest.raises(EditError):
        apply_action(plate, bad)


def test_session_history(plate):
    session = EditSession(plate)
    session.apply({"action": "set_thickness", "value": 8})
    session.apply({"action": "set_thickness", "value": 10})
    assert session.undo().thickness == 8
    assert session.redo().thickness == 10
    session.undo()
    session.apply({"action": "set_thickness", "value": 3})   # discards the redo branch
    with pytest.raises(EditError):
        session.redo()
    assert len(session.log) == 3
