"""Photo of a flat part on A4 paper -> PartSpec in millimetres.

Pipeline: find the A4 sheet -> perspective-correct to a top-down view with a
known scale -> segment the part -> extract outline and holes.

Photo requirements: part lying flat on a plain A4 sheet, sheet fully visible
on a surface that contrasts with the paper, diffuse light, camera roughly above.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from .spec import Hole, PartSpec, Point, polygon_area

A4_SHORT_MM = 210.0
A4_LONG_MM = 297.0
PX_PER_MM = 5.0              # resolution of the rectified image (0.2 mm per pixel)
MAX_PHOTO_SIDE = 2400        # photos larger than this are downscaled
PAPER_MARGIN_MM = 8.0        # ignore the sheet edge (shadows, curl)
MIN_CONTRAST = 20            # part must differ from paper by at least this (0-255)
MIN_PART_AREA_MM2 = 100.0
MIN_HOLE_DIAMETER_MM = 1.5
OUTLINE_TOLERANCE_MM = 0.25  # polygon simplification tolerance
CIRCULARITY_LIMIT = 0.88     # 1.0 is a perfect circle
ASPECT_TOLERANCE = 0.2       # allowed deviation of sheet aspect from A4
MIN_EDGE_MM = 1.0            # shorter edges are pixel-rounding artefacts at corners


class ScanError(Exception):
    """Raised when the photo cannot be turned into a part."""


def order_corners(points: np.ndarray) -> np.ndarray:
    """Return corners as top-left, top-right, bottom-right, bottom-left."""
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).ravel()   # y - x
    return np.array([points[np.argmin(sums)], points[np.argmin(diffs)],
                     points[np.argmax(sums)], points[np.argmax(diffs)]], dtype=np.float32)


def find_paper_corners(image: np.ndarray) -> np.ndarray:
    gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ScanError("No bright sheet of paper found in the photo.")
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 0.15 * image.shape[0] * image.shape[1]:
        raise ScanError("The A4 sheet is too small in the photo; move the camera closer.")
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    for epsilon in np.linspace(0.01, 0.08, 15):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) == 4:
            return order_corners(approx.reshape(4, 2).astype(np.float32))
    raise ScanError("Could not find four clean corners of the paper. "
                    "Make sure the whole sheet is visible on a contrasting surface.")


def rectify_paper(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = corners
    width_px = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0
    height_px = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0
    landscape = width_px > height_px
    ratio = max(width_px, height_px) / min(width_px, height_px)
    if abs(ratio - A4_LONG_MM / A4_SHORT_MM) > ASPECT_TOLERANCE:
        raise ScanError(f"The detected sheet has aspect ratio {ratio:.2f}, not A4 (1.41). "
                        "Use A4 paper and shoot closer to straight down.")
    w_mm, h_mm = (A4_LONG_MM, A4_SHORT_MM) if landscape else (A4_SHORT_MM, A4_LONG_MM)
    w, h = round(w_mm * PX_PER_MM), round(h_mm * PX_PER_MM)
    target = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(image, matrix, (w, h), flags=cv2.INTER_CUBIC)


def segment_part(rectified: np.ndarray) -> np.ndarray:
    """Binary mask (255 = part). Uses difference from the paper colour so both
    dark and light parts work, as long as they differ from the paper."""
    gray = cv2.GaussianBlur(cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    margin = round(PAPER_MARGIN_MM * PX_PER_MM)
    ring = np.zeros(gray.shape, dtype=bool)
    ring[:margin, :] = ring[-margin:, :] = True
    ring[:, :margin] = ring[:, -margin:] = True
    paper_level = float(np.median(gray[ring]))
    diff = np.abs(gray.astype(np.int16) - paper_level).astype(np.uint8)
    threshold, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if threshold < MIN_CONTRAST:
        raise ScanError("The part does not contrast enough with the paper. "
                        "Use a darker background paper or a different part colour.")
    mask[ring] = 0
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def _offset_polygon(points: list[Point], delta: float) -> list[Point]:
    """Offset a counter-clockwise polygon outward by delta (mitre joins)."""
    n = len(points)
    if n < 3 or delta == 0.0:
        return points
    normals = []
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        normals.append((dy / length, -dx / length))   # outward for CCW
    result = []
    for i in range(n):
        n1, n2 = normals[i - 1], normals[i]
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        mlen = math.hypot(mx, my)
        if mlen < 1e-9:
            result.append(points[i])
            continue
        mx, my = mx / mlen, my / mlen
        cos_half = max(mx * n2[0] + my * n2[1], 0.5)   # cap mitre length
        result.append((points[i][0] + mx * delta / cos_half, points[i][1] + my * delta / cos_half))
    return result


def _line_intersection(p1: Point, p2: Point, p3: Point, p4: Point) -> Point | None:
    """Intersection of the infinite lines p1-p2 and p3-p4, or None if parallel."""
    d = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
    if abs(d) < 1e-9:
        return None
    a = p1[0] * p2[1] - p1[1] * p2[0]
    b = p3[0] * p4[1] - p3[1] * p4[0]
    return ((a * (p3[0] - p4[0]) - (p1[0] - p2[0]) * b) / d,
            (a * (p3[1] - p4[1]) - (p1[1] - p2[1]) * b) / d)


def _remove_short_edges(points: list[Point]) -> list[Point]:
    """Replace tiny corner chamfers by the sharp corner formed by the neighbouring edges."""
    pts = list(points)
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            if math.dist(a, b) >= MIN_EDGE_MM:
                continue
            rotated = pts[i:] + pts[:i]
            corner = _line_intersection(rotated[-1], rotated[0], rotated[1], rotated[2 % len(rotated)])
            if corner is None or math.dist(corner, a) > 3 * MIN_EDGE_MM:
                corner = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            pts = [corner] + rotated[2:]
            changed = True
            break
    return pts


def _to_mm(contour: np.ndarray, image_height_px: int) -> list[Point]:
    """Simplify a pixel contour and convert to a CCW y-up polygon in mm."""
    approx = cv2.approxPolyDP(contour, OUTLINE_TOLERANCE_MM * PX_PER_MM, True).reshape(-1, 2)
    points = [(float(x) / PX_PER_MM, (image_height_px - float(y)) / PX_PER_MM) for x, y in approx]
    if polygon_area(points) < 0:
        points.reverse()
    return _remove_short_edges(points)


def extract_part(mask: np.ndarray, thickness: float, name: str) -> PartSpec:
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None or len(contours) == 0:
        raise ScanError("No part found on the paper.")
    hierarchy = hierarchy[0]                      # rows: next, previous, child, parent
    top_level = [i for i in range(len(contours)) if hierarchy[i][3] == -1]
    outer_index = max(top_level, key=lambda i: cv2.contourArea(contours[i]))
    if cv2.contourArea(contours[outer_index]) < MIN_PART_AREA_MM2 * PX_PER_MM ** 2:
        raise ScanError("The detected part is too small; check lighting and framing.")

    height_px = mask.shape[0]
    half_pixel = 0.5 / PX_PER_MM   # contours run through edge-pixel centres, true edge is half a pixel out
    outline = _offset_polygon(_to_mm(contours[outer_index], height_px), half_pixel)
    min_x = min(p[0] for p in outline)
    min_y = min(p[1] for p in outline)
    outline = [(x - min_x, y - min_y) for x, y in outline]

    holes: list[Hole] = []
    for i in range(len(contours)):
        if hierarchy[i][3] != outer_index:
            continue
        contour = contours[i]
        area_px = cv2.contourArea(contour)
        perimeter_px = cv2.arcLength(contour, True)
        if area_px <= 0 or perimeter_px <= 0:
            continue
        diameter = 2.0 * math.sqrt(area_px / math.pi) / PX_PER_MM + 2.0 * half_pixel
        if diameter < MIN_HOLE_DIAMETER_MM:
            continue
        moments = cv2.moments(contour)
        cx = moments["m10"] / moments["m00"] / PX_PER_MM - min_x
        cy = (height_px - moments["m01"] / moments["m00"]) / PX_PER_MM - min_y
        circularity = 4.0 * math.pi * area_px / perimeter_px ** 2
        if circularity >= CIRCULARITY_LIMIT:
            holes.append(Hole(round(cx, 3), round(cy, 3), round(diameter, 3)))
        else:
            poly = _offset_polygon(_to_mm(contour, height_px), half_pixel)
            poly = [(x - min_x, y - min_y) for x, y in poly]
            holes.append(Hole(round(cx, 3), round(cy, 3), round(diameter, 3), tuple(poly)))
    holes.sort(key=lambda h: (round(h.y), h.x))
    return PartSpec(outline, holes, thickness, name)


def scan_part(image_path: str | Path, thickness: float = 5.0, name: str | None = None) -> PartSpec:
    path = Path(image_path)
    image = cv2.imread(str(path))
    if image is None:
        raise ScanError(f"Cannot read image: {path}")
    longest = max(image.shape[:2])
    if longest > MAX_PHOTO_SIDE:
        scale = MAX_PHOTO_SIDE / longest
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    corners = find_paper_corners(image)
    rectified = rectify_paper(image, corners)
    mask = segment_part(rectified)
    return extract_part(mask, thickness, name or path.stem)
