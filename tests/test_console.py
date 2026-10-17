import pytest

from forge.console import ConsoleApp


def run_script(answers):
    """Run the menu with scripted answers; running out of answers acts like Ctrl+D."""
    feed = iter(answers)
    out = []

    def fake_input(prompt):
        out.append(prompt)
        try:
            return next(feed)
        except StopIteration:
            raise EOFError

    app = ConsoleApp(input_fn=fake_input, output_fn=out.append)
    app.run()
    return app, "\n".join(out)


def test_invalid_menu_choices_are_unavailable_not_crashes():
    _, text = run_script(["9", "abc", "", "0"])
    assert text.count("unavailable") == 3 and "Goodbye" in text


def test_actions_need_a_part_first():
    _, text = run_script(["3", "4", "5", "6", "7", "0"])
    assert text.count("No part is loaded") == 5


def test_end_of_input_exits_cleanly():
    _, text = run_script([])
    assert "Goodbye" in text


def test_scan_retries_bad_numbers_then_accepts():
    app, text = run_script(["1", "example", "abc", "-5", "nan", "6", "0"])
    assert text.count("unavailable") == 3
    assert app.session.current.thickness == 6


def test_bad_paths_and_file_types():
    _, text = run_script(["1", "nope.png", "1", __file__, "2", "missing.json", "0"])
    assert text.count("unavailable") == 3


def test_impossible_edit_is_rejected_and_part_unchanged():
    app, text = run_script(["1", "example", "", "4", "1", "5", "500", "20", "0", "0"])
    assert "unavailable" in text and len(app.session.current.holes) == 2


def test_edit_undo_redo():
    app, _ = run_script(["1", "example", "", "4", "5", "9", "7", "0", "0"])
    assert app.session.current.thickness == 5
    app, _ = run_script(["1", "example", "", "4", "5", "9", "7", "8", "0", "0"])
    assert app.session.current.thickness == 9


def test_plan_and_export(tmp_path):
    app, text = run_script(["1", "example", "", "5", "", "", "", "", "0", "6", str(tmp_path), "0"])
    assert "Bill of materials" in text
    assert (tmp_path / "bracket_photo.stl").exists() and (tmp_path / "bracket_photo_plan.md").exists()


def test_load_saved_part_roundtrip(tmp_path):
    run_script(["1", "example", "", "6", str(tmp_path), "0"])
    app, text = run_script(["2", str(tmp_path / "bracket_photo.json"), "3", "0"])
    assert "hole 0" in text and app.session is not None


def test_malformed_json_is_unavailable(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"outline": "oops"}')
    _, text = run_script(["2", str(bad), "0"])
    assert "unavailable" in text
