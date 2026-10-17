"""Menu-driven console interface for Forge Lite (the program behind main.py).

Every question keeps asking until the answer is valid, and every unsupported
choice is reported as "unavailable", so bad input can never crash the program.
Input and output functions are injected so the whole menu can be tested with
scripted answers.
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .buildplan import make_plan, render_markdown
from .buildplan_data import load_materials
from .edit import MAX_THICKNESS_MM, MIN_THICKNESS_MM, EditError, EditSession
from .model import export_all
from .scan import ScanError, scan_part
from .spec import PartSpec

PHOTO_TYPES = {".png", ".jpg", ".jpeg"}
ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PHOTO = ROOT / "examples" / "bracket_photo.png"
APP_PATH = ROOT / "app.py"
VIEWS = ["Isometric", "Top", "Front", "Side"]


class ConsoleApp:
    """Holds the part being worked on and runs the main menu loop."""

    def __init__(self, input_fn: Callable[[str], str] = input,
                 output_fn: Callable[[str], None] = print) -> None:
        self._input = input_fn
        self._print = output_fn
        self.session: EditSession | None = None
        self.settings = {"load": 20.0, "mate": 3.0, "temp": 25.0, "outdoor": False, "material": None}
        self._menu: dict[str, tuple[str, Callable[[], None]]] = {
            "1": ("Scan a photo of a part", self._scan),
            "2": ("Load a saved part (.json)", self._load),
            "3": ("Show part summary", self._summary),
            "4": ("Edit the part", self._edit),
            "5": ("Strength check and build plan", self._plan),
            "6": ("Export STL / STEP / DXF / JSON / plan", self._export),
            "7": ("Open interactive 3D viewer in browser", self._view_3d),
            "8": ("Launch the web app (Streamlit)", self._web_app),
        }

    # ---- output helpers ---------------------------------------------------
    def _say(self, text: str = "") -> None:
        self._print(text)

    def _unavailable(self, reason: str = "") -> None:
        self._say(f"  This option is unavailable. {reason}".rstrip())

    # ---- validated input helpers -------------------------------------------
    def _ask(self, prompt: str) -> str:
        return self._input(f"{prompt}: ").strip()

    def _ask_float(self, prompt: str, low: float | None = None, high: float | None = None,
                   default: float | None = None) -> float:
        suffix = f" [{default:g}]" if default is not None else ""
        while True:
            raw = self._ask(f"{prompt}{suffix}")
            if raw == "" and default is not None:
                return default
            try:
                value = float(raw)
            except ValueError:
                self._unavailable("Please enter a number.")
                continue
            if not math.isfinite(value):
                self._unavailable("Please enter an ordinary number.")
            elif (low is not None and value < low) or (high is not None and value > high):
                self._unavailable(f"The value must be between {low} and {high}.")
            else:
                return value

    def _ask_index(self, prompt: str, count: int) -> int:
        while True:
            raw = self._ask(f"{prompt} (0 to {count - 1})")
            if raw.isdigit() and int(raw) < count:
                return int(raw)
            self._unavailable(f"Enter a whole number from 0 to {count - 1}.")

    def _ask_yes_no(self, prompt: str, default: bool) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            raw = self._ask(f"{prompt} [{hint}]").lower()
            if raw == "":
                return default
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False
            self._unavailable("Please answer y or n.")

    def _ask_choice(self, prompt: str, options: list[str], allow_auto: bool = False) -> str | None:
        """Numbered list. With allow_auto, 0 means 'automatic' and returns None."""
        for number, option in enumerate(options, 1):
            self._say(f"  {number}. {option}")
        if allow_auto:
            self._say("  0. Automatic (cheapest safe)")
        low = 0 if allow_auto else 1
        while True:
            raw = self._ask(prompt)
            if raw.isdigit() and low <= int(raw) <= len(options):
                return None if int(raw) == 0 else options[int(raw) - 1]
            self._unavailable(f"Choose a number from {low} to {len(options)}.")

    def _need_part(self) -> PartSpec | None:
        if self.session is None:
            self._unavailable("No part is loaded yet. Choose 1 to scan a photo or 2 to load a saved part.")
            return None
        return self.session.current

    # ---- menu actions ----------------------------------------------------------
    def _scan(self) -> None:
        raw = self._ask("Path to photo (or type 'example')").strip("\"'")
        path = EXAMPLE_PHOTO if raw.lower() == "example" else Path(raw).expanduser()
        if not path.is_file():
            self._unavailable(f"There is no file at '{raw}'.")
            return
        if path.suffix.lower() not in PHOTO_TYPES:
            self._unavailable("Only PNG and JPG photos are supported.")
            return
        thickness = self._ask_float("Part thickness in mm", MIN_THICKNESS_MM, MAX_THICKNESS_MM, 5.0)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_") or "part"
        try:
            spec = scan_part(path, thickness, name)
        except ScanError as error:
            self._unavailable(str(error))
            return
        self.session = EditSession(spec)
        self._say(f"  Scanned: {spec.width:.1f} x {spec.height:.1f} mm, {len(spec.holes)} holes.")

    def _load(self) -> None:
        raw = self._ask("Path to saved part (.json)").strip("\"'")
        try:
            spec = PartSpec.load(Path(raw).expanduser())
        except (OSError, ValueError) as error:    # missing file, bad JSON, malformed data
            self._unavailable(f"Could not read that part ({error}).")
            return
        self.session = EditSession(spec)
        self._say(f"  Loaded '{spec.name}'.")

    def _summary(self) -> None:
        spec = self._need_part()
        if spec is None:
            return
        self._say(f"  {spec.name}: {spec.width:.1f} x {spec.height:.1f} x {spec.thickness:g} mm, "
                  f"volume {spec.volume / 1000:.2f} cm3")
        for i, hole in enumerate(spec.holes):
            kind = "round" if hole.is_circular else "non-round"
            self._say(f"  hole {i}: {kind}, diameter {hole.diameter:.2f} mm at ({hole.x:.1f}, {hole.y:.1f})")
        if not spec.holes:
            self._say("  (no holes)")

    def _edit(self) -> None:
        if self._need_part() is None:
            return
        actions = {
            "1": "Add a hole", "2": "Move a hole", "3": "Resize a hole", "4": "Remove a hole",
            "5": "Set thickness", "6": "Scale the part", "7": "Undo", "8": "Redo", "9": "Show history",
        }
        while True:
            self._say("\n  Edit menu")
            for key, label in actions.items():
                self._say(f"  {key}. {label}")
            self._say("  0. Back")
            choice = self._ask("Choose an edit")
            if choice == "0":
                return
            if choice not in actions:
                self._unavailable("That edit is not on the menu.")
                continue
            try:
                self._run_edit(choice)
            except EditError as error:
                self._unavailable(str(error))

    def _run_edit(self, choice: str) -> None:
        session = self.session
        spec = session.current
        if choice in ("2", "3", "4") and not spec.holes:
            self._unavailable("This part has no holes.")
            return
        if choice == "1":
            diameter = self._ask_float("Hole diameter in mm", 1.0, 500.0)
            x = self._ask_float("x position in mm", -1000.0, 1000.0, round(spec.width / 2, 1))
            y = self._ask_float("y position in mm", -1000.0, 1000.0, round(spec.height / 2, 1))
            session.apply({"action": "add_hole", "diameter": diameter, "x": x, "y": y})
        elif choice == "2":
            i = self._ask_index("Which hole", len(spec.holes))
            x = self._ask_float("New x in mm", -1000.0, 1000.0, spec.holes[i].x)
            y = self._ask_float("New y in mm", -1000.0, 1000.0, spec.holes[i].y)
            session.apply({"action": "move_hole", "index": i, "x": x, "y": y})
        elif choice == "3":
            i = self._ask_index("Which hole", len(spec.holes))
            d = self._ask_float("New diameter in mm", 1.0, 500.0, spec.holes[i].diameter)
            session.apply({"action": "resize_hole", "index": i, "diameter": d})
        elif choice == "4":
            session.apply({"action": "remove_hole", "index": self._ask_index("Which hole", len(spec.holes))})
        elif choice == "5":
            value = self._ask_float("New thickness in mm", MIN_THICKNESS_MM, MAX_THICKNESS_MM, spec.thickness)
            session.apply({"action": "set_thickness", "value": value})
        elif choice == "6":
            session.apply({"action": "scale", "factor": self._ask_float("Scale factor", 0.1, 10.0, 1.0)})
        elif choice == "7":
            session.undo()
        elif choice == "8":
            session.redo()
        else:
            for line in session.log:
                self._say(f"  {line}")
            return
        self._say("  Done.")

    def _plan_settings(self) -> None:
        s = self.settings
        s["load"] = self._ask_float("Load at the free end in newtons (10 N is about 1 kg)", 0.0, 5000.0, s["load"])
        s["mate"] = self._ask_float("Thickness of the plate it bolts to in mm", 0.0, 100.0, s["mate"])
        s["temp"] = self._ask_float("Working temperature in C", -40.0, 400.0, s["temp"])
        s["outdoor"] = self._ask_yes_no("Used outdoors?", s["outdoor"])
        self._say("  Material:")
        s["material"] = self._ask_choice("Choose a material", [m.name for m in load_materials()], allow_auto=True)

    def _plan(self) -> None:
        spec = self._need_part()
        if spec is None:
            return
        self._plan_settings()
        s = self.settings
        try:
            plan = make_plan(spec, s["load"], s["outdoor"], s["temp"], s["mate"], s["material"])
        except ValueError as error:
            self._unavailable(str(error))
            return
        self._say("")
        self._say(render_markdown(plan, s["load"]))

    def _export(self) -> None:
        spec = self._need_part()
        if spec is None:
            return
        folder = Path(self._ask("Output folder [output]").strip("\"'") or "output")
        s = self.settings
        try:
            paths = list(export_all(spec, folder).values())
            spec.save(folder / f"{spec.name}.json")
            paths.append(folder / f"{spec.name}.json")
            try:
                plan = make_plan(spec, s["load"], s["outdoor"], s["temp"], s["mate"], s["material"])
                plan_path = folder / f"{spec.name}_plan.md"
                plan_path.write_text(render_markdown(plan, s["load"]), encoding="utf-8")
                paths.append(plan_path)
            except ValueError as error:
                self._say(f"  Build plan not written: {error}")
        except OSError as error:
            self._unavailable(f"Could not write to '{folder}' ({error}).")
            return
        self._say("  Wrote:")
        for path in paths:
            self._say(f"    {path}")

    def _view_3d(self) -> None:
        spec = self._need_part()
        if spec is None:
            return
        from .viewer import make_figure   # imported here so the menu starts fast
        view = self._ask_choice("Choose a view", VIEWS)
        make_figure(spec, view).show()
        self._say("  The 3D viewer should have opened in your browser.")

    def _web_app(self) -> None:
        self._say("  Starting the web app. Press Ctrl+C in this window to stop it.")
        try:
            subprocess.run([sys.executable, "-m", "streamlit", "run", str(APP_PATH)], check=False)
        except (OSError, KeyboardInterrupt):
            self._unavailable("The web app could not be started. Is streamlit installed?")

    # ---- main loop -------------------------------------------------------------
    def run(self) -> None:
        self._say("=== Forge Lite: photo to CAD to build plan ===")
        try:
            while True:
                self._say("\nMain menu")
                for key, (label, _) in self._menu.items():
                    self._say(f"  {key}. {label}")
                self._say("  0. Quit")
                choice = self._ask("Choose an option")
                if choice == "0":
                    break
                if choice not in self._menu:
                    self._unavailable("That option is not on the menu.")
                    continue
                try:
                    self._menu[choice][1]()
                except (EOFError, KeyboardInterrupt):
                    raise
                except Exception as error:   # safety net: a bug in one feature must not end the session
                    self._unavailable(f"Something went wrong ({type(error).__name__}: {error}).")
        except (EOFError, KeyboardInterrupt):
            self._say("")
        self._say("Goodbye.")
