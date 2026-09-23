"""Foam-box geometry only: no camera, model or robot side effects."""
from __future__ import annotations

import math
import cv2
import numpy as np

METHOD = "contour_homography_min_area_rect_v1"


def square_delta(angle: float, reference: float = 0.0) -> float:
    """Nearest equivalent square orientation, in [-45, 45)."""
    if not math.isfinite(angle) or not math.isfinite(reference):
        raise ValueError("각도는 유한한 숫자여야 합니다.")
    return (angle - reference + 45.0) % 90.0 - 45.0


def square_mean(angles) -> float:
    values = np.asarray(angles, dtype=float)
    if not values.size or not np.isfinite(values).all():
        raise ValueError("각도 표본이 유효하지 않습니다.")
    vector = np.mean(np.exp(4j * np.deg2rad(values)))
    if abs(vector) < 0.5:
        raise ValueError("각도가 안정적이지 않습니다.")
    return square_delta(float(np.rad2deg(np.angle(vector)) / 4))


def estimate_box(frame, bbox, correction):
    """Return (candidate, reason). Geometry score is NOT a probability.

    Transform the contour before fitting: a camera-view minimum rectangle
    is not generally a rectangle on the robot's XY plane.
    """
    x1, y1, x2, y2 = map(float, bbox)
    h, w = frame.shape[:2]
    bw, bh = x2 - x1, y2 - y1
    if min(bw, bh) < 16:
        return None, "ROI too small"
    # YOLO often follows the pasted photograph rather than the foam-box edge.
    # Use a wider ROI so the physical 70 mm outline is still available.
    left, top = max(0, int(x1 - bw * .5)), max(0, int(y1 - bh * .5))
    right, bottom = min(w, int(x2 + bw * .5) + 1), min(h, int(y2 + bh * .5) + 1)
    gray = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    contours = []
    kernel = np.ones((5, 5), np.uint8)
    for low, high in ((15, 50), (30, 100), (60, 180)):
        edges = cv2.Canny(gray, low, high)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        found, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours.extend(found)
    matrix = np.asarray(correction["matrix_3x3"], dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("XY 행렬이 유효하지 않습니다.")
    inverse = np.linalg.inv(matrix)

    def transform(points, mapping):
        points = np.asarray(points, dtype=float).reshape(-1, 2)
        homogeneous = np.c_[points, np.ones(len(points))] @ mapping.T
        if np.any(np.abs(homogeneous[:, 2]) < 1e-9):
            raise ValueError("Homography 분모가 0입니다.")
        return homogeneous[:, :2] / homogeneous[:, 2:3]

    center = np.array([(x1+x2)/2, (y1+y2)/2])
    hull = np.asarray(correction["pixel_convex_hull"], dtype=np.float32)
    candidates = []
    for contour in contours:
        area = abs(cv2.contourArea(contour))
        if area < bw * bh * .08:
            continue
        bx, by, cw, ch = cv2.boundingRect(contour)
        if bx <= 1 or by <= 1 or bx+cw >= right-left-1 or by+ch >= bottom-top-1:
            continue  # cropped edges / neighbouring objects
        points = contour.reshape(-1, 2).astype(float) + [left, top]
        if cv2.pointPolygonTest(points.astype(np.float32), tuple(center), False) < 0:
            continue
        world = transform(points, matrix).astype(np.float32)
        rect = cv2.minAreaRect(world)
        rw, rh = rect[1]
        if min(rw, rh) <= 1e-6:
            continue
        aspect = min(rw, rh) / max(rw, rh)
        if not (40 <= rw <= 105 and 40 <= rh <= 105) or aspect < 1 / 1.5:
            continue  # rough 70 mm square candidate
        fill = abs(cv2.contourArea(world)) / (rw * rh)
        if fill < .60:
            continue
        corners_world = cv2.boxPoints(rect)
        corners = transform(corners_world, inverse)
        if any(cv2.pointPolygonTest(hull, tuple(map(float, p)), False) < 0 for p in corners):
            continue
        center_error = float(np.linalg.norm(np.mean(corners, axis=0)-center))
        if center_error > .45*min(bw, bh):
            continue
        edge = corners_world[1] - corners_world[0]
        angle = square_delta(math.degrees(math.atan2(float(edge[1]), float(edge[0]))))
        size_score = max(0.0, 1.0 - (abs(rw-70) + abs(rh-70)) / 90.0)
        center_score = max(0.0, 1.0 - center_error / max(1.0, .45*min(bw, bh)))
        score = float(.35*fill + .25*aspect + .30*size_score + .10*center_score)
        candidates.append({"method": METHOD, "yaw_base_deg": angle,
                           "quality": score, "size_mm": [float(rw), float(rh)],
                           "fill": float(fill), "center_error_px": center_error,
                           "corners_px": corners.tolist()})
    if not candidates:
        return None, "no 70mm square outline"
    candidates.sort(key=lambda c: c["quality"], reverse=True)
    best = candidates[0]
    return best, "OK"


def stable_orientation(samples):
    """Combine consecutive samples; reject motion and orientation jitter."""
    if not samples or any(s is None for s in samples):
        raise ValueError("외곽선 검출이 끊겼습니다.")
    angle = square_mean([s["yaw_base_deg"] for s in samples])
    spread = max(abs(square_delta(s["yaw_base_deg"], angle)) for s in samples)
    centers = np.array([np.mean(s["corners_px"], axis=0) for s in samples])
    if spread > 10 or np.max(np.linalg.norm(centers-centers.mean(axis=0), axis=1)) > 10:
        raise ValueError("박스 위치 또는 각도가 흔들립니다.")
    return {**samples[-1], "yaw_base_deg": angle, "spread_deg": spread,
            "quality": float(np.median([s["quality"] for s in samples])),
            "stable_frames": len(samples)}
