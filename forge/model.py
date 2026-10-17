"""PartSpec -> CadQuery solid, plus STL / STEP / DXF export."""
from __future__ import annotations

from pathlib import Path

import cadquery as cq

from .spec import PartSpec

CUTTER_OVERSHOOT_MM = 1.0   # cutters extend past both faces so no coplanar faces remain


def build_solid(spec: PartSpec) -> cq.Workplane:
    solid = cq.Workplane("XY").polyline(spec.outline).close().extrude(spec.thickness)
    for hole in spec.holes:
        cutter_plane = cq.Workplane("XY").workplane(offset=-CUTTER_OVERSHOOT_MM)
        depth = spec.thickness + 2.0 * CUTTER_OVERSHOOT_MM
        if hole.is_circular:
            cutter = cutter_plane.center(hole.x, hole.y).circle(hole.radius).extrude(depth)
        else:
            cutter = cutter_plane.polyline(list(hole.polygon)).close().extrude(depth)
        solid = solid.cut(cutter)
    return solid


def export_all(spec: PartSpec, out_dir: str | Path) -> dict[str, Path]:
    """Write <name>.stl, <name>.step and <name>.dxf; return their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    solid = build_solid(spec)
    paths = {ext: out / f"{spec.name}.{ext}" for ext in ("stl", "step", "dxf")}
    cq.exporters.export(solid, str(paths["stl"]), tolerance=0.01, angularTolerance=0.1)
    cq.exporters.export(solid, str(paths["step"]))
    face = solid.faces("<Z").val()
    cq.exporters.exportDXF(cq.Workplane("XY").add(face), str(paths["dxf"]))
    return paths


def solid_volume_mm3(spec: PartSpec) -> float:
    """Volume measured by the CAD kernel (cross-check for PartSpec.volume)."""
    return float(build_solid(spec).val().Volume())
