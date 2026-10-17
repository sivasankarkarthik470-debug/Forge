import pytest

from forge.buildplan import make_plan, match_fastener, render_markdown
from forge.buildplan_data import load_fasteners, load_materials
from forge.checks import check_bending
from forge.model import build_solid, export_all
from forge.spec import Hole, PartSpec


@pytest.fixture
def plate():
    return PartSpec([(0, 0), (100, 0), (100, 40), (0, 40)], [Hole(20, 20, 5.5), Hole(80, 20, 5.5)], 6, "plate")


def test_cad_volume_matches_spec(plate):
    assert build_solid(plate).val().Volume() == pytest.approx(plate.volume, rel=1e-6)


def test_exports_exist(plate, tmp_path):
    for path in export_all(plate, tmp_path).values():
        assert path.stat().st_size > 0


def test_thicker_is_stronger(plate):
    pla = next(m for m in load_materials() if m.name == "PLA")
    thin = check_bending(plate, pla, 30)
    plate.thickness = 12
    thick = check_bending(plate, pla, 30)
    assert thick.safety_factor > thin.safety_factor * 3   # stress falls with thickness squared


def test_zero_load_is_safe(plate):
    pla = load_materials()[0]
    assert check_bending(plate, pla, 0).verdict == "green"


def test_fastener_matching():
    fasteners = load_fasteners()
    fastener, _ = match_fastener(5.5, 6, 3, fasteners)
    assert fastener.size == "M5" and fastener.length_mm >= 6 + 3 + 1 + 4 + 1
    assert match_fastener(15.0, 6, 3, fasteners)[0] is None


def test_plan_respects_constraints(plate):
    plan = make_plan(plate, load_n=20, outdoor=True)
    assert plan.material.outdoor_ok
    assert any("M5" in line.item for line in plan.bom)
    assert "Bill of materials" in render_markdown(plan, 20)


def test_overloaded_part_warns(plate):
    plate.thickness = 1
    plan = make_plan(plate, load_n=500)
    assert plan.warnings
