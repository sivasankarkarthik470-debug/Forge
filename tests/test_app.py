from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"
from forge.spec import Hole, PartSpec
from forge.viewer import make_figure, mesh_data, mesh_volume


@pytest.fixture
def plate():
    return PartSpec([(0, 0), (100, 0), (100, 40), (0, 40)], [Hole(20, 20, 5), Hole(80, 20, 5)], 6, "plate")


def test_mesh_volume_matches_spec(plate):
    v, t = mesh_data(plate)
    assert mesh_volume(v, t) == pytest.approx(plate.volume, rel=0.01)


def test_figure_views(plate):
    for view in ("Isometric", "Top", "Front", "Side"):
        assert len(make_figure(plate, view).data) == 2
    with pytest.raises(ValueError):
        make_figure(plate, "Underneath")


def _app():
    return AppTest.from_file(str(APP), default_timeout=60).run()


def test_app_starts_empty():
    at = _app()
    assert not at.exception and at.info


def test_example_scan_edit_and_unavailable_messages():
    at = _app()
    next(b for b in at.button if b.label == "Use example photo").click().run()
    assert not at.exception and len(at.metric) >= 4
    # an impossible edit is reported as unavailable, not as a crash
    next(s for s in at.selectbox if s.label == "Change").select("Add hole").run()
    next(n for n in at.number_input if n.label == "x (mm)").set_value(500).run()
    next(b for b in at.button if b.label == "Apply change").click().run()
    assert not at.exception
    assert any("unavailable" in w.value for w in at.warning)
    # typed chat command
    at.chat_input[0].set_value("make it thicker").run()
    assert any("unavailable" in w.value for w in at.warning)
