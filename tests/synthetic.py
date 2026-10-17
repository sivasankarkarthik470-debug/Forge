"""Generate a synthetic 'photo' of a bracket on A4 paper, seen from an angle."""
import cv2
import numpy as np

PPM = 5.0   # px per mm of the flat scene


def make_photo(path, part_w=100.0, part_h=40.0, holes=((20.0, 20.0, 5.0), (80.0, 20.0, 5.0)), seed=1):
    scene = np.full((round(297 * PPM), round(210 * PPM), 3), 235, np.uint8)
    x0, y0 = 40.0, 90.0   # part origin on the sheet, mm
    cv2.rectangle(scene, (round(x0 * PPM), round(y0 * PPM)),
                  (round((x0 + part_w) * PPM), round((y0 + part_h) * PPM)), (40, 40, 40), -1)
    for hx, hy, d in holes:
        cv2.circle(scene, (round((x0 + hx) * PPM), round((y0 + part_h - hy) * PPM)), round(d / 2 * PPM), (235, 235, 235), -1)
    h, w = scene.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[350, 100], [1250, 170], [1300, 1400], [300, 1340]])
    photo = cv2.warpPerspective(scene, cv2.getPerspectiveTransform(src, dst), (1600, 1500),
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(90, 90, 90))
    photo = cv2.resize(photo, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)   # realistic loss of detail
    noise = np.random.default_rng(seed).normal(0, 3, photo.shape)
    photo = np.clip(photo.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), photo)
