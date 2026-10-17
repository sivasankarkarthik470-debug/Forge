"""Build plan: material choice, cost, fabrication routes, bill of materials, assembly."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .buildplan_data import Fastener, Material, load_fasteners, load_materials
from .checks import BendingResult, check_bending
from .spec import PartSpec

PRINT_WASTE = 1.10         # supports, purge, failed first layer
STOCK_WASTE = 1.15         # offcuts and kerf when cutting from a rectangular blank
HOLE_SIZE_TOLERANCE_MM = 0.6   # how far a measured hole may exceed a standard clearance hole
MIN_RECOMMENDED_SAFETY = 2.0

PROCESS_NAMES = {
    "3d_print": "3D print (FDM)",
    "laser_cut": "Laser cut",
    "cnc": "CNC mill / router",
    "hand_tools": "Hand tools (saw, file, drill)",
}
PROCESS_FILE = {"3d_print": "STL", "laser_cut": "DXF", "cnc": "STEP", "hand_tools": "DXF (print 1:1 as a template)"}
PROCESS_TOOLS = {
    "3d_print": ["3D printer or print service", "Flush cutters", "Sandpaper (200 and 400 grit)", "Calipers"],
    "laser_cut": ["Laser cutter or cutting service", "Calipers", "Deburring tool or sandpaper"],
    "cnc": ["CNC mill or router, or machining service", "Calipers", "Deburring tool", "Vice or clamps"],
    "hand_tools": ["Printed 1:1 template", "Hacksaw or jigsaw", "Files", "Drill and bits", "Calipers", "Clamps"],
}


@dataclass(frozen=True)
class Candidate:
    material: Material
    process: str
    material_cost: float
    check: BendingResult


@dataclass(frozen=True)
class BomLine:
    item: str
    quantity: int
    unit_price: float
    note: str = ""

    @property
    def total(self) -> float:
        return self.quantity * self.unit_price


@dataclass
class BuildPlan:
    spec: PartSpec
    material: Material
    process: str
    check: BendingResult
    bom: list[BomLine]
    alternatives: list[Candidate]
    warnings: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(line.total for line in self.bom)


def process_feasible(spec: PartSpec, material: Material, process: str) -> bool:
    if process not in material.processes:
        return False
    if process == "laser_cut":
        return material.laser_max_mm >= spec.thickness
    return True


def material_cost(spec: PartSpec, material: Material, process: str) -> float:
    """Cost of raw material in dollars (additive uses part volume; others use the bounding blank)."""
    if process == "3d_print":
        volume_mm3 = spec.volume * PRINT_WASTE
    else:
        volume_mm3 = spec.width * spec.height * spec.thickness * STOCK_WASTE
    kilograms = volume_mm3 / 1000.0 * material.density_g_cm3 / 1000.0
    return kilograms * material.price_per_kg


def rank_candidates(spec: PartSpec, materials: list[Material], load_n: float,
                    outdoor: bool, temp_c: float) -> list[Candidate]:
    """Feasible materials with a safe margin, cheapest first."""
    candidates = []
    for material in materials:
        if outdoor and not material.outdoor_ok:
            continue
        if temp_c > material.max_temp_c:
            continue
        processes = [p for p in material.processes if process_feasible(spec, material, p)]
        if not processes:
            continue
        check = check_bending(spec, material, load_n)
        if check.safety_factor < MIN_RECOMMENDED_SAFETY:
            continue
        best = min(processes, key=lambda p: material_cost(spec, material, p))
        candidates.append(Candidate(material, best, material_cost(spec, material, best), check))
    return sorted(candidates, key=lambda c: c.material_cost)


def match_fastener(hole_diameter: float, thickness: float, mate_thickness: float,
                   fasteners: list[Fastener]) -> tuple[Fastener | None, str]:
    """Pick the screw for a hole. Returns (fastener, note); fastener is None if nothing fits."""
    sizes = {}
    for f in fasteners:
        sizes.setdefault(f.size, f)
    fitting = [f for f in sizes.values()
               if f.nominal_mm - 0.2 <= hole_diameter <= f.clearance_mm + HOLE_SIZE_TOLERANCE_MM]
    if not fitting:
        return None, f"{hole_diameter:.1f} mm hole matches no standard screw; treat as a pin, cable or custom hole."
    size = min(fitting, key=lambda f: abs(f.clearance_mm - hole_diameter)).size
    options = sorted((f for f in fasteners if f.size == size), key=lambda f: f.length_mm)
    sample = options[0]
    needed = thickness + mate_thickness + sample.washer_mm + sample.nut_height_mm + 1.0   # +1 mm thread protrusion
    for option in options:
        if option.length_mm >= needed:
            return option, f"needs at least {needed:.1f} mm of screw"
    return options[-1], f"needs {needed:.1f} mm but the longest in the catalog is {options[-1].length_mm:g} mm; source a longer one"


def build_bom(spec: PartSpec, material: Material, process: str, mate_thickness: float,
              fasteners: list[Fastener]) -> tuple[list[BomLine], list[str]]:
    warnings: list[str] = []
    bom = [BomLine(f"{spec.name} ({material.name}, {spec.thickness:g} mm, {PROCESS_NAMES[process]})",
                   1, round(material_cost(spec, material, process), 2), "raw material only")]
    counts: dict[tuple[str, float], list] = {}
    for i, hole in enumerate(spec.holes):
        if not hole.is_circular:
            continue
        fastener, note = match_fastener(hole.diameter, spec.thickness, mate_thickness, fasteners)
        if fastener is None:
            warnings.append(f"Hole {i}: {note}")
            continue
        if "source a longer" in note:
            warnings.append(f"Hole {i}: {note}")
        counts.setdefault((fastener.size, fastener.length_mm), [fastener, 0])[1] += 1
    for (size, length), (fastener, qty) in sorted(counts.items()):
        bom.append(BomLine(f"{size} x {length:g} mm screw", qty, fastener.screw_price))
        bom.append(BomLine(f"{size} nut", qty, fastener.nut_price))
        bom.append(BomLine(f"{size} washer", qty, fastener.washer_price))
    return bom, warnings


def assembly_steps(spec: PartSpec, process: str, material: Material, has_fasteners: bool) -> list[str]:
    steps = []
    if process == "3d_print":
        steps += [f"Import the STL into your slicer. Lay the part flat on the bed so layers run along its length "
                  f"(layer lines are the weak direction). Use 3 or more walls and about 40% infill in {material.name}.",
                  "Print, let the bed cool, then remove the part and trim any stringing with flush cutters."]
    elif process == "laser_cut":
        steps += [f"Send the DXF to the laser cutter with {spec.thickness:g} mm {material.name}; "
                  "set the cut layer to the machine's recommended power and speed for this thickness.",
                  "Remove the part, clean any residue, and lightly sand the edges."]
    elif process == "cnc":
        steps += [f"Load the STEP file into CAM software, fix a {spec.thickness:g} mm {material.name} blank, "
                  "and machine the outline and holes.",
                  "Deburr every edge and hole."]
    else:
        steps += ["Print the DXF at 100% scale, glue it to the material, and mark the outline and hole centres.",
                  "Drill the holes first, then cut out the outline slightly oversize and file to the line."]
    steps.append("Check hole sizes and overall dimensions with calipers against the model before assembling.")
    if has_fasteners:
        steps += ["Fit a washer under each screw head and a washer under each nut.",
                  "Insert screws through the part and mating surface, add nuts, and tighten in a criss-cross "
                  "order so the part pulls down evenly. Snug is enough for plastics and wood; overtightening cracks them."]
    steps.append("Load-test gently at first and watch the part for flexing or cracking before trusting it.")
    return steps


def make_plan(spec: PartSpec, load_n: float = 20.0, outdoor: bool = False, temp_c: float = 25.0,
              mate_thickness: float = 3.0, material_name: str | None = None) -> BuildPlan:
    materials = load_materials()
    fasteners = load_fasteners()
    candidates = rank_candidates(spec, materials, load_n, outdoor, temp_c)
    warnings: list[str] = []

    if material_name:
        matches = [m for m in materials if m.name.lower() == material_name.lower()]
        if not matches:
            raise ValueError(f"Unknown material {material_name!r}. Options: {', '.join(m.name for m in materials)}.")
        material = matches[0]
        processes = [p for p in material.processes if process_feasible(spec, material, p)]
        if not processes:
            raise ValueError(f"{material.name} cannot be made with any listed process at {spec.thickness:g} mm.")
        process = min(processes, key=lambda p: material_cost(spec, material, p))
        check = check_bending(spec, material, load_n)
    elif candidates:
        best = candidates[0]
        material, process, check = best.material, best.process, best.check
    else:
        # Nothing meets the margin: fall back to the strongest feasible option and say so.
        feasible = [(m, p) for m in materials for p in m.processes
                    if process_feasible(spec, m, p) and (not outdoor or m.outdoor_ok) and temp_c <= m.max_temp_c]
        if not feasible:
            raise ValueError("No catalog material satisfies the environment and thickness; relax the constraints.")
        material, process = max(feasible, key=lambda mp: check_bending(spec, mp[0], load_n).safety_factor)
        check = check_bending(spec, material, load_n)
        warnings.append("No material reaches the recommended safety factor of "
                        f"{MIN_RECOMMENDED_SAFETY}; showing the strongest option. Increase thickness.")

    if check.verdict == "red":
        warnings.append("The strength check is RED for this material and load.")
    if temp_c > material.max_temp_c:
        warnings.append(f"{material.name} softens above {material.max_temp_c:g} C.")
    if outdoor and not material.outdoor_ok:
        warnings.append(f"{material.name} is not rated for outdoor use without protection.")

    bom, bom_warnings = build_bom(spec, material, process, mate_thickness, fasteners)
    warnings += bom_warnings
    alternatives = [c for c in candidates if c.material.name != material.name][:3]
    plan = BuildPlan(spec, material, process, check, bom, alternatives, warnings)
    plan.steps = assembly_steps(spec, process, material, has_fasteners=len(bom) > 1)
    plan.tools = list(PROCESS_TOOLS[process])
    if len(bom) > 1:
        plan.tools += ["Screwdriver or hex key", "Spanner for nuts"]
    return plan


def render_markdown(plan: BuildPlan, load_n: float) -> str:
    spec = plan.spec
    lines = [f"# Build plan: {spec.name}", "",
             f"- Size: {spec.width:.1f} x {spec.height:.1f} x {spec.thickness:g} mm, {len(spec.holes)} holes",
             f"- Volume: {spec.volume / 1000:.2f} cm3",
             f"- Chosen material: **{plan.material.name}**, made by **{PROCESS_NAMES[plan.process]}** "
             f"(upload the {PROCESS_FILE[plan.process]} file)", "",
             "## Strength check", "", f"**{plan.check.verdict.upper()}**: {plan.check.message}", ""]
    if plan.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in plan.warnings] + [""]
    lines += ["## Bill of materials", "", "| Item | Qty | Unit (USD) | Total (USD) |", "|---|---|---|---|"]
    lines += [f"| {b.item} | {b.quantity} | {b.unit_price:.2f} | {b.total:.2f} |" for b in plan.bom]
    lines += [f"| **Total** | | | **{plan.total_cost:.2f}** |", "",
              "Prices are placeholder estimates in `data/*.csv`; edit them to match your local supplier.", ""]
    if plan.alternatives:
        lines += ["## Other materials that also pass", "", "| Material | Process | Raw material (USD) | Safety factor |", "|---|---|---|---|"]
        lines += [f"| {c.material.name} | {PROCESS_NAMES[c.process]} | {c.material_cost:.2f} | {c.check.safety_factor:.1f} |"
                  for c in plan.alternatives]
        lines.append("")
    lines += ["## Tools", ""] + [f"- {t}" for t in plan.tools] + ["", "## Steps", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(plan.steps, 1)]
    return "\n".join(lines) + "\n"
