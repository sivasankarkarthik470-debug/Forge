"""Command line entry point: python -m forge photo.jpg --thickness 5 --load 20"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .buildplan import make_plan, render_markdown
from .model import export_all
from .scan import ScanError, scan_part


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge", description="Photo of a flat part on A4 paper -> CAD files and build plan.")
    p.add_argument("photo", help="photo of the part lying on a sheet of A4 paper")
    p.add_argument("--thickness", type=float, default=5.0, help="part thickness in mm (default 5)")
    p.add_argument("--load", type=float, default=20.0, help="load at the free end in newtons (default 20)")
    p.add_argument("--mate", type=float, default=3.0, help="thickness of the plate it bolts to, mm (default 3)")
    p.add_argument("--temp", type=float, default=25.0, help="working temperature in C (default 25)")
    p.add_argument("--outdoor", action="store_true", help="part will be used outdoors")
    p.add_argument("--material", help="force a material instead of the cheapest safe one")
    p.add_argument("--name", help="part name (defaults to the photo file name)")
    p.add_argument("--out", default="output", help="output folder (default ./output)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = scan_part(args.photo, args.thickness, args.name)
        plan = make_plan(spec, args.load, args.outdoor, args.temp, args.mate, args.material)
    except (ScanError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = export_all(spec, out)
    spec.save(out / f"{spec.name}.json")
    (out / f"{spec.name}_plan.md").write_text(render_markdown(plan, args.load), encoding="utf-8")
    print(f"Part: {spec.width:.1f} x {spec.height:.1f} x {spec.thickness:g} mm, {len(spec.holes)} holes")
    for i, hole in enumerate(spec.holes):
        kind = "round" if hole.is_circular else "non-round"
        print(f"  hole {i}: {kind}, dia {hole.diameter:.2f} mm at ({hole.x:.1f}, {hole.y:.1f})")
    print(f"Material: {plan.material.name} | strength: {plan.check.verdict.upper()} | cost: ${plan.total_cost:.2f}")
    print("Wrote: " + ", ".join(str(p) for p in [*paths.values(), out / f"{spec.name}.json", out / f"{spec.name}_plan.md"]))
    return 0
