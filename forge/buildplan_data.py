"""Catalog data classes and CSV loaders (materials and fasteners)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Material:
    name: str
    density_g_cm3: float
    yield_mpa: float
    youngs_gpa: float
    price_per_kg: float
    processes: tuple[str, ...]
    outdoor_ok: bool
    max_temp_c: float
    derate: float          # fraction of yield strength trusted (layer adhesion, grain, flaws)
    laser_max_mm: float    # thickest sheet the usual hobby laser cuts; 0 = not laser-cuttable

    @property
    def youngs_mpa(self) -> float:
        return self.youngs_gpa * 1000.0


@dataclass(frozen=True)
class Fastener:
    size: str
    nominal_mm: float
    clearance_mm: float
    nut_height_mm: float
    washer_mm: float
    length_mm: float
    screw_price: float
    nut_price: float
    washer_price: float


def load_materials(path: str | Path = DATA_DIR / "materials.csv") -> list[Material]:
    materials = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            materials.append(Material(
                name=row["name"],
                density_g_cm3=float(row["density_g_cm3"]),
                yield_mpa=float(row["yield_mpa"]),
                youngs_gpa=float(row["youngs_gpa"]),
                price_per_kg=float(row["price_per_kg_usd"]),
                processes=tuple(row["processes"].split(";")),
                outdoor_ok=row["outdoor_ok"].strip().lower() == "yes",
                max_temp_c=float(row["max_temp_c"]),
                derate=float(row["derate"]),
                laser_max_mm=float(row["laser_max_mm"]),
            ))
    return materials


def load_fasteners(path: str | Path = DATA_DIR / "fasteners.csv") -> list[Fastener]:
    fasteners = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            fasteners.append(Fastener(
                size=row["size"], nominal_mm=float(row["nominal_mm"]),
                clearance_mm=float(row["clearance_mm"]), nut_height_mm=float(row["nut_height_mm"]),
                washer_mm=float(row["washer_mm"]), length_mm=float(row["length_mm"]),
                screw_price=float(row["screw_price_usd"]), nut_price=float(row["nut_price_usd"]),
                washer_price=float(row["washer_price_usd"]),
            ))
    return fasteners
