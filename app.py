"""Forge Lite: Streamlit interface.  Run with:  streamlit run app.py"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import streamlit as st

from forge.buildplan import PROCESS_NAMES, make_plan, render_markdown
from forge.buildplan_data import load_materials
from forge.edit import MAX_THICKNESS_MM, MIN_THICKNESS_MM, EditError, EditSession
from forge.model import export_all
from forge.scan import ScanError, scan_part
from forge.spec import PartSpec
from forge.viewer import CAMERAS, make_figure

MAX_UPLOAD_MB = 15
ALLOWED_TYPES = ["png", "jpg", "jpeg"]
EXAMPLE_PHOTO = Path(__file__).parent / "examples" / "bracket_photo.png"

st.set_page_config(page_title="Forge Lite", page_icon="🔧", layout="wide")


def unavailable(reason: str = "") -> None:
    """Every rejected or unsupported input ends up here."""
    st.warning(f"This option is unavailable. {reason}".strip())


def safe_name(stem: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "part"


@st.cache_data(show_spinner=False)
def exported_files(spec_json: str) -> dict[str, bytes]:
    spec = PartSpec.from_dict(json.loads(spec_json))
    with tempfile.TemporaryDirectory() as tmp:
        paths = export_all(spec, tmp)
        return {ext: path.read_bytes() for ext, path in paths.items()}


def run_scan(photo_path: Path, name: str, thickness: float) -> None:
    try:
        spec = scan_part(photo_path, thickness, name)
    except ScanError as error:
        st.session_state.pop("session", None)
        unavailable(str(error))
        return
    st.session_state["session"] = EditSession(spec)
    st.session_state["flash"] = f"Scanned {spec.width:.1f} x {spec.height:.1f} mm with {len(spec.holes)} holes."


def sidebar() -> dict:
    with st.sidebar:
        st.header("1. Photo")
        upload = st.file_uploader("Part on A4 paper", type=ALLOWED_TYPES,
                                  help="PNG or JPG. Whole sheet in frame, camera roughly overhead.")
        thickness = st.number_input("Thickness (mm)", MIN_THICKNESS_MM, MAX_THICKNESS_MM, 5.0, 0.5)
        scan_clicked = st.button("Scan photo", type="primary", disabled=upload is None)
        example_clicked = st.button("Use example photo", disabled=not EXAMPLE_PHOTO.exists())

        if scan_clicked and upload is not None:
            if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
                unavailable(f"Files above {MAX_UPLOAD_MB} MB are not supported.")
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"upload{Path(upload.name).suffix.lower()}"
                    path.write_bytes(upload.getvalue())
                    run_scan(path, safe_name(Path(upload.name).stem), thickness)
        if example_clicked:
            run_scan(EXAMPLE_PHOTO, "example_bracket", thickness)

        st.header("2. Use case")
        load = st.number_input("Load at free end (N)", 0.0, 5000.0, 20.0, 5.0,
                               help="10 N is about 1 kg hanging off the end.")
        mate = st.number_input("Thickness of what it bolts to (mm)", 0.0, 100.0, 3.0, 0.5)
        temp = st.number_input("Working temperature (C)", -40.0, 400.0, 25.0, 5.0)
        outdoor = st.checkbox("Used outdoors")
        names = [m.name for m in load_materials()]
        choice = st.selectbox("Material", ["Automatic (cheapest safe)"] + names)
    return dict(load=load, mate=mate, temp=temp, outdoor=outdoor,
                material=None if choice.startswith("Automatic") else choice)


def edit_panel(session: EditSession) -> None:
    spec = session.current
    left, right = st.columns(2)
    if left.button("Undo", disabled=len(session.log) < 2 or "<- current" in session.log[0]):
        session.undo()
        st.rerun()
    if right.button("Redo", disabled="<- current" in session.log[-1]):
        session.redo()
        st.rerun()

    action = st.selectbox("Change", ["Set thickness", "Add hole", "Move hole", "Resize hole",
                                     "Remove hole", "Scale part"])
    request: dict | None = None
    labels = [f"Hole {i}: dia {h.diameter:.1f} at ({h.x:.1f}, {h.y:.1f})" for i, h in enumerate(spec.holes)]
    needs_hole = action in ("Move hole", "Resize hole", "Remove hole")
    if needs_hole and not spec.holes:
        unavailable("This part has no holes to change.")
        return
    index = labels.index(st.selectbox("Which hole", labels)) if needs_hole else None

    if action == "Set thickness":
        request = {"action": "set_thickness", "value": st.number_input("New thickness (mm)", 0.0, 500.0, spec.thickness, 0.5)}
    elif action == "Add hole":
        c = st.columns(3)
        request = {"action": "add_hole",
                   "diameter": c[0].number_input("Diameter (mm)", 0.0, 500.0, 5.0, 0.5),
                   "x": c[1].number_input("x (mm)", -1000.0, 1000.0, spec.width / 2, 1.0),
                   "y": c[2].number_input("y (mm)", -1000.0, 1000.0, spec.height / 2, 1.0)}
    elif action == "Move hole":
        c = st.columns(2)
        request = {"action": "move_hole", "index": index,
                   "x": c[0].number_input("New x (mm)", -1000.0, 1000.0, spec.holes[index].x, 1.0),
                   "y": c[1].number_input("New y (mm)", -1000.0, 1000.0, spec.holes[index].y, 1.0)}
    elif action == "Resize hole":
        request = {"action": "resize_hole", "index": index,
                   "diameter": st.number_input("New diameter (mm)", 0.0, 500.0, spec.holes[index].diameter, 0.5)}
    elif action == "Remove hole":
        request = {"action": "remove_hole", "index": index}
    else:
        request = {"action": "scale", "factor": st.number_input("Scale factor", 0.0, 100.0, 1.0, 0.1)}

    if st.button("Apply change", type="primary"):
        try:
            session.apply(request)
        except EditError as error:
            unavailable(str(error))
            return
        st.rerun()

    with st.expander("Version history"):
        for line in session.log:
            st.write(line)


def plan_panel(spec: PartSpec, settings: dict) -> None:
    try:
        plan = make_plan(spec, settings["load"], settings["outdoor"], settings["temp"],
                         settings["mate"], settings["material"])
    except ValueError as error:
        unavailable(str(error))
        return None
    verdict = {"green": st.success, "amber": st.warning, "red": st.error}[plan.check.verdict]
    verdict(f"**{plan.check.verdict.upper()}**: {plan.check.message}")
    c = st.columns(3)
    c[0].metric("Material", plan.material.name)
    c[1].metric("Process", PROCESS_NAMES[plan.process])
    c[2].metric("Estimated cost", f"${plan.total_cost:.2f}")
    for warning in plan.warnings:
        st.warning(warning)
    st.subheader("Bill of materials")
    st.dataframe([{"Item": b.item, "Qty": b.quantity, "Unit (USD)": round(b.unit_price, 2),
                   "Total (USD)": round(b.total, 2)} for b in plan.bom], hide_index=True, use_container_width=True)
    if plan.alternatives:
        st.subheader("Other materials that also pass")
        st.dataframe([{"Material": a.material.name, "Process": PROCESS_NAMES[a.process],
                       "Raw material (USD)": round(a.material_cost, 2),
                       "Safety factor": round(a.check.safety_factor, 1)} for a in plan.alternatives],
                     hide_index=True, use_container_width=True)
    st.subheader("Tools")
    st.write(", ".join(plan.tools))
    st.subheader("Steps")
    for i, step in enumerate(plan.steps, 1):
        st.write(f"{i}. {step}")
    return render_markdown(plan, settings["load"])


def main() -> None:
    st.title("Forge Lite")
    st.caption("Photo of a flat part on A4 paper -> 3D model -> strength check -> build plan")
    settings = sidebar()

    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))
    session: EditSession | None = st.session_state.get("session")
    if session is None:
        st.info("Upload a photo in the sidebar and press **Scan photo**, or try the example.")
    else:
        spec = session.current
        c = st.columns(4)
        c[0].metric("Width", f"{spec.width:.1f} mm")
        c[1].metric("Height", f"{spec.height:.1f} mm")
        c[2].metric("Thickness", f"{spec.thickness:g} mm")
        c[3].metric("Holes", len(spec.holes))

        viewer_tab, edit_tab, plan_tab, files_tab = st.tabs(["3D viewer", "Edit", "Strength and build plan", "Downloads"])
        with viewer_tab:
            v = st.columns([2, 1])
            view = v[0].radio("View", list(CAMERAS), horizontal=True, label_visibility="collapsed")
            edges = v[1].checkbox("Show edges", value=True)
            st.plotly_chart(make_figure(spec, view, edges), use_container_width=True)
            st.caption("Drag to rotate, scroll to zoom, right-drag to pan.")
        with edit_tab:
            edit_panel(session)
        with plan_tab:
            plan_md = plan_panel(spec, settings)
        with files_tab:
            files = exported_files(json.dumps(spec.to_dict()))
            labels = {"stl": ("STL (3D printing)", "model/stl"), "step": ("STEP (CAD / CNC)", "application/step"),
                      "dxf": ("DXF (laser cutting)", "application/dxf")}
            for ext, (label, mime) in labels.items():
                st.download_button(f"Download {label}", files[ext], f"{spec.name}.{ext}", mime)
            st.download_button("Download part data (JSON)", json.dumps(spec.to_dict(), indent=2),
                               f"{spec.name}.json", "application/json")
            if plan_md:
                st.download_button("Download build plan (Markdown)", plan_md, f"{spec.name}_plan.md", "text/markdown")

    typed = st.chat_input("Describe a change in words...")
    if typed:
        unavailable("Typed commands are not supported yet. Use the Edit tab instead.")


main()
