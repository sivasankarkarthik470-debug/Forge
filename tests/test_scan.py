import pytest

from forge.scan import ScanError, scan_part
from .synthetic import make_photo


def test_scan_recovers_dimensions_and_holes(tmp_path):
    photo = tmp_path / "bracket.png"
    make_photo(photo)
    spec = scan_part(photo, thickness=6)
    assert spec.width == pytest.approx(100.0, abs=1.0)
    assert spec.height == pytest.approx(40.0, abs=1.0)
    assert len(spec.holes) == 2
    for hole in spec.holes:
        assert hole.is_circular
        assert hole.diameter == pytest.approx(5.0, abs=0.4)
    assert sorted(round(h.x) for h in spec.holes) == [20, 80]


def test_scan_non_a4_is_rejected(tmp_path):
    import cv2
    import numpy as np
    img = np.full((600, 600, 3), 90, np.uint8)
    cv2.rectangle(img, (100, 100), (500, 500), (235, 235, 235), -1)   # square sheet, not A4
    path = tmp_path / "square.png"
    cv2.imwrite(str(path), img)
    with pytest.raises(ScanError):
        scan_part(path)


def test_missing_file_is_a_scan_error(tmp_path):
    with pytest.raises(ScanError):
        scan_part(tmp_path / "nope.png")
