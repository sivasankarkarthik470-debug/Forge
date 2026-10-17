"""Pure-Python description of a flat part (no OpenCV / CadQuery needed).

All lengths are millimetres. The outline is a counter-clockwise polygon in a
y-up coordinate system whose bounding box starts at (0, 0).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

Point = tuple[float, float]


def polygon_area(points: list[Point] | tuple[Point, ...]) -> float:
    """Signed area (shoelace). Positive for counter-clockwise polygons."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def point_in_polygon(x: float, y: float, polygon: list[Point]) -> bool:
    """Ray-casting test."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def distance_to_segment(px: float, py: float, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_polygon_edge(px: float, py: float, polygon: list[Point]) -> float:
    n = len(polygon)
    return min(distance_to_segment(px, py, polygon[i], polygon[(i + 1) % n]) for i in range(n))


@dataclass(frozen=True)
class Hole:
    """A circular hole, or a non-circular one described by a polygon.

    For polygon holes, (x, y) is the centroid and `diameter` the equivalent
    circle diameter (used for clearance checks and fastener matching).
    """

    x: float
    y: float
    diameter: float
    polygon: tuple[Point, ...] = ()

    @property
    def radius(self) -> float:
        return self.diameter / 2.0

    @property
    def is_circular(self) -> bool:
        return not self.polygon

    @property
    def area(self) -> float:
        if self.polygon:
            return abs(polygon_area(self.polygon))
        return math.pi * self.radius ** 2


@dataclass
class PartSpec:
    outline: list[Point]
    holes: list[Hole] = field(default_factory=list)
    thickness: float = 5.0
    name: str = "part"

    def copy(self) -> "PartSpec":
        # Hole and tuples are immutable, so a shallow list copy is a true copy.
        return PartSpec(list(self.outline), list(self.holes), self.thickness, self.name)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.outline]
        ys = [p[1] for p in self.outline]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def width(self) -> float:
        x0, _, x1, _ = self.bbox
        return x1 - x0

    @property
    def height(self) -> float:
        _, y0, _, y1 = self.bbox
        return y1 - y0

    @property
    def plan_area(self) -> float:
        """Area of the face in mm^2 after subtracting holes."""
        return abs(polygon_area(self.outline)) - sum(h.area for h in self.holes)

    @property
    def volume(self) -> float:
        """Volume in mm^3 (exact for an extruded prism)."""
        return self.plan_area * self.thickness

    # ---- file I/O -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "thickness": self.thickness,
            "outline": [list(p) for p in self.outline],
            "holes": [
                {"x": h.x, "y": h.y, "diameter": h.diameter,
                 "polygon": [list(p) for p in h.polygon]}
                for h in self.holes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PartSpec":
        """Build a part from saved data; raise ValueError if the data is malformed."""
        try:
            outline = [(float(x), float(y)) for x, y in data["outline"]]
            holes = [
                Hole(float(h["x"]), float(h["y"]), float(h["diameter"]),
                     tuple((float(a), float(b)) for a, b in h.get("polygon", [])))
                for h in data.get("holes", [])
            ]
            thickness = float(data.get("thickness", 5.0))
            name = str(data.get("name", "part"))
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"Invalid part data: {error!r}") from error
        if len(outline) < 3:
            raise ValueError("A part needs an outline with at least 3 points.")
        if not math.isfinite(thickness) or thickness <= 0:
            raise ValueError("Thickness must be a positive number.")
        return cls(outline, holes, thickness, name)

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "PartSpec":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))
