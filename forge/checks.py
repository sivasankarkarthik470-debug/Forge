"""First-pass strength estimate: the part as a cantilever plate.

Model: the part is clamped at one short end and loaded at the free end,
perpendicular to its face (like a shelf bracket or a ruler over a table edge).
Section = narrow dimension minus the biggest hole, by thickness. This is a
screening check, not a substitute for FEA or a safety certification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .buildplan_data import Material
from .spec import PartSpec

GREEN_SAFETY_FACTOR = 2.5
AMBER_SAFETY_FACTOR = 1.25
MIN_NET_WIDTH_FRACTION = 0.2    # holes never remove more than 80% of the section


@dataclass(frozen=True)
class BendingResult:
    stress_mpa: float
    allowable_mpa: float
    safety_factor: float
    deflection_mm: float
    verdict: str      # "green" | "amber" | "red"
    message: str


def check_bending(spec: PartSpec, material: Material, load_n: float) -> BendingResult:
    if load_n < 0:
        raise ValueError("load_n must not be negative.")
    length = max(spec.width, spec.height)
    width = min(spec.width, spec.height)
    thickness = spec.thickness
    biggest_hole = max((h.diameter for h in spec.holes), default=0.0)
    net_width = max(width - biggest_hole, MIN_NET_WIDTH_FRACTION * width)

    stress = 6.0 * load_n * length / (net_width * thickness ** 2)               # MPa (N/mm^2)
    deflection = 4.0 * load_n * length ** 3 / (material.youngs_mpa * net_width * thickness ** 3)
    allowable = material.yield_mpa * material.derate
    safety = math.inf if stress == 0 else allowable / stress

    if safety >= GREEN_SAFETY_FACTOR:
        verdict, headline = "green", "Comfortably strong for this load."
    elif safety >= AMBER_SAFETY_FACTOR:
        verdict, headline = "amber", "Probably holds, but with little margin. Thicken it or use a stiffer material."
    else:
        verdict, headline = "red", "Likely to bend permanently or break. Make it thicker or pick a stronger material."

    flex_ratio = deflection / length
    if flex_ratio > 0.05:
        feel = "It will feel floppy, like a plastic ruler held over a table edge."
    elif flex_ratio > 0.01:
        feel = "It will flex visibly under that load."
    else:
        feel = "It will feel stiff."
    message = (f"{headline} A {load_n:g} N load (about {load_n / 9.81:.1f} kg) at the free end gives "
               f"{stress:.1f} MPa against {allowable:.1f} MPa allowed in {material.name} "
               f"(safety factor {safety:.1f}), and bends it {deflection:.2f} mm. {feel}")
    return BendingResult(stress, allowable, safety, deflection, verdict, message)
