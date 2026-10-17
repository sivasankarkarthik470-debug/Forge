"""3D view of a PartSpec as an interactive Plotly figure (rotate, zoom, pan)."""
from __future__ import annotations

import math

import plotly.graph_objects as go

from .model import build_solid
from .spec import PartSpec

TESSELLATION_TOLERANCE_MM = 0.05
ANGULAR_TOLERANCE_RAD = 0.1
CIRCLE_SEGMENTS = 64

CAMERAS = {
    "Isometric": dict(eye=dict(x=1.5, y=-1.5, z=1.2), up=dict(x=0, y=0, z=1)),
    "Top": dict(eye=dict(x=0.0, y=0.001, z=2.6), up=dict(x=0, y=1, z=0)),
    "Front": dict(eye=dict(x=0.0, y=-2.6, z=0.35), up=dict(x=0, y=0, z=1)),
    "Side": dict(eye=dict(x=2.6, y=0.0, z=0.35), up=dict(x=0, y=0, z=1)),
}


def mesh_data(spec: PartSpec) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices, triangles = build_solid(spec).val().tessellate(TESSELLATION_TOLERANCE_MM, ANGULAR_TOLERANCE_RAD)
    return [(v.x, v.y, v.z) for v in vertices], [tuple(t) for t in triangles]


def mesh_volume(vertices, triangles) -> float:
    """Volume from the triangle mesh (divergence theorem); used to verify the display mesh."""
    total = 0.0
    for a, b, c in triangles:
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = vertices[a], vertices[b], vertices[c]
        total += (x1 * (y2 * z3 - y3 * z2) - x2 * (y1 * z3 - y3 * z1) + x3 * (y1 * z2 - y2 * z1)) / 6.0
    return abs(total)


def _edge_lines(spec: PartSpec) -> tuple[list, list, list]:
    """Outline and hole edges on both faces as one polyline with gaps (None)."""
    xs: list = []
    ys: list = []
    zs: list = []
    loops = [list(spec.outline)]
    for hole in spec.holes:
        if hole.polygon:
            loops.append(list(hole.polygon))
        else:
            loops.append([(hole.x + hole.radius * math.cos(2 * math.pi * k / CIRCLE_SEGMENTS),
                           hole.y + hole.radius * math.sin(2 * math.pi * k / CIRCLE_SEGMENTS))
                          for k in range(CIRCLE_SEGMENTS)])
    for loop in loops:
        for z in (0.0, spec.thickness):
            closed = loop + [loop[0]]
            xs += [p[0] for p in closed] + [None]
            ys += [p[1] for p in closed] + [None]
            zs += [z] * len(closed) + [None]
    return xs, ys, zs


def make_figure(spec: PartSpec, view: str = "Isometric", show_edges: bool = True,
                color: str = "#4f8fc0") -> go.Figure:
    if view not in CAMERAS:
        raise ValueError(f"Unknown view {view!r}.")
    vertices, triangles = mesh_data(spec)
    fig = go.Figure()
    fig.add_trace(go.Mesh3d(
        x=[v[0] for v in vertices], y=[v[1] for v in vertices], z=[v[2] for v in vertices],
        i=[t[0] for t in triangles], j=[t[1] for t in triangles], k=[t[2] for t in triangles],
        color=color, flatshading=True, name=spec.name,
        lighting=dict(ambient=0.45, diffuse=0.8, specular=0.25, roughness=0.6),
        lightposition=dict(x=200, y=-300, z=400),
        hovertemplate="x %{x:.1f} mm<br>y %{y:.1f} mm<br>z %{z:.1f} mm<extra></extra>",
    ))
    if show_edges:
        xs, ys, zs = _edge_lines(spec)
        fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", hoverinfo="skip",
                                   line=dict(color="#1c2b3a", width=3), showlegend=False))
    fig.update_layout(
        scene=dict(aspectmode="data", camera=CAMERAS[view],
                   xaxis_title="x (mm)", yaxis_title="y (mm)", zaxis_title="z (mm)"),
        margin=dict(l=0, r=0, t=0, b=0), height=560, showlegend=False,
    )
    return fig
