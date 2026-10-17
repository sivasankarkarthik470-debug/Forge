# Forge Lite

![tests](../../actions/workflows/ci.yml/badge.svg)

## Description
Forge Lite turns a photo of a broken or missing flat part (a bracket, plate or gasket) into a measured 3D model,
a plain-language strength check and a complete build plan: what to make it from, what it costs, which screws to buy
and how to assemble it. In Singapore, where people live in small flats and throw away objects that only need a
replacement part, it lowers the barrier to repairing instead of replacing, with no CAD skills or software licence needed.

## Features
- Scans a photo of a part lying on A4 paper and measures its outline and holes in millimetres (OpenCV, perspective correction)
- Menu-driven program in `main.py` that keeps asking until input is valid, and reports anything unsupported as "unavailable" instead of crashing
- Builds a parametric 3D model and exports STL (3D printing), STEP (CNC) and DXF (laser cutting)
- Interactive 3D viewer with Isometric, Top, Front and Side views
- Edits the part (add, move, resize, remove holes; change thickness; scale) with every change validated, plus undo/redo and version history (a list of versions with a cursor, which behaves like undo/redo stacks)
- Strength check: a cantilever bending estimate with a green / amber / red verdict and an everyday explanation
- Build plan: ranks materials from `data/materials.csv` by cost, matches screws from `data/fasteners.csv` to each hole size, and writes a bill of materials, tools list and assembly steps
- File IO: reads CSV catalogs, saves and loads parts as JSON, writes the build plan as Markdown
- Optional web interface (Streamlit) with the same features
- 35 automated tests, run on every push by GitHub Actions

## How to Run
Requires Python 3.10 to 3.12.
```
pip install -r requirements.txt
python main.py
```
Choose **1**, type `example` to try the included photo, then explore the menu. For your own part, lay it flat on a plain
A4 sheet with the whole sheet in frame, shoot from roughly overhead in even light, and give the program the photo path.

Optional: `streamlit run app.py` for the web interface, and `pytest` to run the tests.

## File Structure
```
main.py                  entry point (console menu)
app.py                   optional Streamlit web interface
requirements.txt         packages to install
forge/
  console.py             ConsoleApp: menu loop and validated input
  scan.py                photo -> PartSpec (A4 detection, perspective fix, outline and hole extraction)
  spec.py                PartSpec and Hole classes, geometry helpers, JSON save/load
  edit.py                validated edit actions and EditSession (undo/redo history)
  model.py               PartSpec -> CadQuery solid, STL/STEP/DXF export
  viewer.py              interactive 3D figure
  checks.py              strength estimate
  buildplan.py           material ranking, cost, fastener matching, BOM, assembly steps
  buildplan_data.py      Material and Fastener classes, CSV loaders
data/                    materials.csv, fasteners.csv (editable catalogs)
examples/                sample photo
tests/                   automated tests
```

## Class Design
- **`PartSpec`**: the part itself (outline, holes, thickness, name). Computes size, area and volume and saves/loads JSON. Holds no CAD or image code, so it is easy to test.
- **`Hole`**: one hole (position, diameter, optional polygon). Immutable (frozen), so copies of a part can safely share holes.
- **`EditSession`**: owns the version history of a part and applies edits through named actions. Each edit is validated first (inside the part, minimum wall left, no overlap), so an invalid change raises `EditError` and the part is left untouched.
- **`ConsoleApp`**: runs the menu. Input and output functions are passed in, which is how the whole menu is tested with scripted answers.
- **`Material`, `Fastener`**: read-only rows of the CSV catalogs.
- **`Candidate`, `BomLine`, `BuildPlan`, `BendingResult`**: results of the material ranking, bill of materials, plan and strength check.

## Reflection
**Hardest problem:** getting trustworthy measurements out of a photo. Edge pixels sit half a pixel inside the true edge, so holes measured too small and parts too thin, and pixel rounding left tiny fake chamfers at corners. I fixed it by testing against a synthetic photo with known sizes, adding a half-pixel offset correction and a step that removes edges shorter than 1 mm. After that the test part measured within about 0.5 mm.

**With two more weeks:** plain-English editing ("make it thicker and add two M5 holes") using an LLM that can only produce the validated edit actions, an explain mode with real-life analogies, proper FEA instead of the beam estimate, and curved parts and multi-photo scanning.

## Limits
Flat, extruded parts only. The strength check is a screening estimate, not a safety certification. Prices in `data/*.csv` are placeholders. Tested on synthetic photos; accuracy on real photos depends on lighting and camera angle.

## Licence
MIT. See `LICENSE`.
