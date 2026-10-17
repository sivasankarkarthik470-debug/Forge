"""Validated edits to a PartSpec, with undo/redo version history.

Every change goes through a named action with checked parameters. This is the
layer a chat/LLM front-end talks to: it emits {"action": ..., ...} dictionaries
and never executes free-form code.
"""
from __future__ import annotations

from typing import Callable

from .spec import Hole, PartSpec, distance_to_polygon_edge, point_in_polygon

MIN_WALL_MM = 1.5
MIN_THICKNESS_MM = 0.5
MAX_THICKNESS_MM = 50.0
MIN_HOLE_DIAMETER_MM = 1.0
MIN_SCALE, MAX_SCALE = 0.1, 10.0


class EditError(ValueError):
    """An edit was rejected; the part is unchanged."""


def _number(params: dict, key: str, low: float | None = None, high: float | None = None) -> float:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EditError(f"'{key}' must be a number, got {value!r}.")
    value = float(value)
    if low is not None and value < low:
        raise EditError(f"'{key}' must be at least {low}, got {value}.")
    if high is not None and value > high:
        raise EditError(f"'{key}' must be at most {high}, got {value}.")
    return value


def _index(spec: PartSpec, params: dict) -> int:
    value = params["index"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise EditError(f"'index' must be an integer, got {value!r}.")
    if not 0 <= value < len(spec.holes):
        raise EditError(f"No hole with index {value}; the part has {len(spec.holes)} holes (0-based).")
    return value


def hole_position_problem(spec: PartSpec, x: float, y: float, diameter: float,
                          ignore_index: int | None = None) -> str | None:
    """Return a reason the hole cannot be placed there, or None if it fits."""
    radius = diameter / 2.0
    if not point_in_polygon(x, y, spec.outline):
        return f"The point ({x:.1f}, {y:.1f}) is outside the part."
    edge_gap = distance_to_polygon_edge(x, y, spec.outline) - radius
    if edge_gap < MIN_WALL_MM:
        return (f"The hole would leave only {max(edge_gap, 0):.1f} mm to the edge; "
                f"at least {MIN_WALL_MM} mm is required.")
    for i, other in enumerate(spec.holes):
        if i == ignore_index:
            continue
        gap = ((x - other.x) ** 2 + (y - other.y) ** 2) ** 0.5 - radius - other.radius
        if gap < MIN_WALL_MM:
            return f"The hole would be too close to hole {i} (gap {max(gap, 0):.1f} mm, need {MIN_WALL_MM})."
    return None


def _set_thickness(spec: PartSpec, p: dict) -> PartSpec:
    new = spec.copy()
    new.thickness = _number(p, "value", MIN_THICKNESS_MM, MAX_THICKNESS_MM)
    return new


def _add_hole(spec: PartSpec, p: dict) -> PartSpec:
    d = _number(p, "diameter", MIN_HOLE_DIAMETER_MM)
    x, y = _number(p, "x"), _number(p, "y")
    problem = hole_position_problem(spec, x, y, d)
    if problem:
        raise EditError(problem)
    new = spec.copy()
    new.holes.append(Hole(x, y, d))
    return new


def _remove_hole(spec: PartSpec, p: dict) -> PartSpec:
    new = spec.copy()
    del new.holes[_index(spec, p)]
    return new


def _move_hole(spec: PartSpec, p: dict) -> PartSpec:
    i = _index(spec, p)
    old = spec.holes[i]
    if not old.is_circular:
        raise EditError("Only circular holes can be moved; remove and re-add the slot instead.")
    x, y = _number(p, "x"), _number(p, "y")
    problem = hole_position_problem(spec, x, y, old.diameter, ignore_index=i)
    if problem:
        raise EditError(problem)
    new = spec.copy()
    new.holes[i] = Hole(x, y, old.diameter)
    return new


def _resize_hole(spec: PartSpec, p: dict) -> PartSpec:
    i = _index(spec, p)
    old = spec.holes[i]
    if not old.is_circular:
        raise EditError("Only circular holes can be resized.")
    d = _number(p, "diameter", MIN_HOLE_DIAMETER_MM)
    problem = hole_position_problem(spec, old.x, old.y, d, ignore_index=i)
    if problem:
        raise EditError(problem)
    new = spec.copy()
    new.holes[i] = Hole(old.x, old.y, d)
    return new


def _scale(spec: PartSpec, p: dict) -> PartSpec:
    """Scale the plan view (outline, hole positions and sizes); thickness is unchanged."""
    f = _number(p, "factor", MIN_SCALE, MAX_SCALE)
    scale_pt = lambda pt: (pt[0] * f, pt[1] * f)
    holes = [Hole(h.x * f, h.y * f, h.diameter * f, tuple(scale_pt(q) for q in h.polygon))
             for h in spec.holes]
    return PartSpec([scale_pt(q) for q in spec.outline], holes, spec.thickness, spec.name)


# action name -> (handler, required parameter names)
ACTIONS: dict[str, tuple[Callable[[PartSpec, dict], PartSpec], tuple[str, ...]]] = {
    "set_thickness": (_set_thickness, ("value",)),
    "add_hole": (_add_hole, ("diameter", "x", "y")),
    "remove_hole": (_remove_hole, ("index",)),
    "move_hole": (_move_hole, ("index", "x", "y")),
    "resize_hole": (_resize_hole, ("index", "diameter")),
    "scale": (_scale, ("factor",)),
}


def apply_action(spec: PartSpec, action: dict) -> PartSpec:
    """Return a new PartSpec with the action applied, or raise EditError."""
    if not isinstance(action, dict) or "action" not in action:
        raise EditError("An action must be a dict with an 'action' key.")
    name = action["action"]
    if name not in ACTIONS:
        raise EditError(f"Unknown action {name!r}. Available: {', '.join(sorted(ACTIONS))}.")
    handler, required = ACTIONS[name]
    params = {k: v for k, v in action.items() if k != "action"}
    missing = [k for k in required if k not in params]
    if missing:
        raise EditError(f"Action {name!r} is missing: {', '.join(missing)}.")
    extra = [k for k in params if k not in required]
    if extra:
        raise EditError(f"Action {name!r} got unexpected parameters: {', '.join(extra)}.")
    return handler(spec, params)


class EditSession:
    """Holds the current part and its full version history."""

    def __init__(self, spec: PartSpec) -> None:
        self._versions: list[tuple[str, PartSpec]] = [("initial scan", spec.copy())]
        self._cursor = 0

    @property
    def current(self) -> PartSpec:
        return self._versions[self._cursor][1]

    @property
    def log(self) -> list[str]:
        return [f"v{i}: {label}" + ("  <- current" if i == self._cursor else "")
                for i, (label, _) in enumerate(self._versions)]

    def apply(self, action: dict) -> PartSpec:
        new = apply_action(self.current, action)
        label = ", ".join(f"{k}={v}" for k, v in action.items())
        del self._versions[self._cursor + 1:]          # a new edit discards the redo branch
        self._versions.append((label, new))
        self._cursor += 1
        return new

    def undo(self) -> PartSpec:
        if self._cursor == 0:
            raise EditError("Nothing to undo.")
        self._cursor -= 1
        return self.current

    def redo(self) -> PartSpec:
        if self._cursor == len(self._versions) - 1:
            raise EditError("Nothing to redo.")
        self._cursor += 1
        return self.current
