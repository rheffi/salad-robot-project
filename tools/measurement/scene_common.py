#!/usr/bin/env python3
"""Shared scene capture and pixel-to-robot XY helpers."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "ml" / "models" / "best.pt"
DEFAULT_CORRECTION = PROJECT_ROOT / "config" / "xy_correction.json"
DEFAULT_SNAPSHOT = PROJECT_ROOT / "records" / "scene_snapshot.json"
DEFAULT_SNAPSHOT_IMAGE = PROJECT_ROOT / "records" / "scene_snapshot.jpg"
PICK_CLASSES = ("tomato", "cheese", "berry")
SCENE_CLASSES = (*PICK_CLASSES, "bowl")
BOX_SIZE_MM = 70


def load_json(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"파일이 없습니다: {resolved}")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 최상위 형식 오류: {resolved}")
    return value


def manual_offset(correction: dict[str, Any]) -> tuple[float, float]:
    value = correction.get("manual_offset_mm", {})
    if not isinstance(value, dict):
        raise ValueError("manual_offset_mm 형식이 잘못됐습니다.")
    x, y = float(value.get("x", 0.0)), float(value.get("y", 0.0))
    if not np.isfinite([x, y]).all():
        raise ValueError("manual_offset_mm 값이 유효하지 않습니다.")
    return x, y


def validate_correction(correction: dict[str, Any]) -> None:
    if correction.get("method") != "pixel_to_robot_xy_homography":
        raise ValueError("지원하지 않는 XY 보정 방식입니다.")
    if float(correction.get("fit_error_mm", {}).get("max", 1e9)) > 30.0:
        raise ValueError("XY 보정 최대 오차가 30mm를 넘습니다.")
    profile = correction.get("camera", {})
    if int(profile.get("width", 0)) <= 0 or int(profile.get("height", 0)) <= 0:
        raise ValueError("카메라 해상도 형식이 잘못됐습니다.")
    manual_offset(correction)


def pixel_to_robot_xy(
    u: float, v: float, correction: dict[str, Any]
) -> tuple[float, float]:
    matrix = np.asarray(correction.get("matrix_3x3"), dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("matrix_3x3 형식이 잘못됐습니다.")
    target = matrix @ np.array([u, v, 1.0], dtype=float)
    if abs(target[2]) < 1e-9:
        raise ValueError("Homography 계산 분모가 0입니다.")
    offset_x, offset_y = manual_offset(correction)
    return (
        float(target[0] / target[2]) + offset_x,
        float(target[1] / target[2]) + offset_y,
    )


def validate_target(
    u: float, v: float, x: float, y: float, correction: dict[str, Any]
) -> None:
    hull = np.asarray(correction.get("pixel_convex_hull"), dtype=np.float32)
    if hull.ndim != 2 or hull.shape[1] != 2:
        raise ValueError("pixel_convex_hull 형식이 잘못됐습니다.")
    if cv2.pointPolygonTest(hull, (float(u), float(v)), False) < 0:
        raise ValueError("검출점이 XY 보정점 영역 밖입니다.")
    bounds = correction.get("robot_xy_bounds_mm", {})
    if not (
        float(bounds["x_min"]) <= x <= float(bounds["x_max"])
        and float(bounds["y_min"]) <= y <= float(bounds["y_max"])
    ):
        raise ValueError("보정된 XY가 측정된 로봇 작업영역 밖입니다.")
    radius = float(np.hypot(x, y))
    if not 150.0 < radius < 850.0:
        raise ValueError(f"목표 수평거리 {radius:.1f}mm가 허용 범위 밖입니다.")


def find_camera(camera_arg: str) -> str | int:
    if camera_arg != "auto":
        return int(camera_arg) if camera_arg.isdecimal() else camera_arg
    by_id = Path("/dev/v4l/by-id")
    if by_id.is_dir():
        matches = sorted(by_id.glob("*RealSense*video-index0"))
        if matches:
            resolved = matches[0].resolve().name
            if resolved.startswith("video") and resolved[5:].isdecimal():
                return int(resolved[5:])
    if Path("/dev/video6").exists():
        return 6
    raise RuntimeError("RealSense RGB 장치를 찾지 못했습니다.")


def capture_scene(
    model_path: Path,
    correction: dict[str, Any],
    camera_arg: str,
    confidence: float,
    stable_frames: int,
) -> tuple[dict[str, Any], np.ndarray]:
    validate_correction(correction)
    if not 0.0 < confidence <= 1.0 or stable_frames < 3:
        raise ValueError("conf 또는 stable-frames 값을 확인하세요.")
    model_file = model_path.expanduser().resolve()
    if not model_file.is_file():
        raise FileNotFoundError(f"YOLO 모델이 없습니다: {model_file}")
    model = YOLO(str(model_file))
    raw_names = model.names.values() if isinstance(model.names, dict) else model.names
    names = set(str(name) for name in raw_names)
    missing = sorted(set(SCENE_CLASSES) - names)
    if missing:
        raise ValueError(f"YOLO 모델 누락 클래스: {missing}")

    profile = correction["camera"]
    width, height = int(profile["width"]), int(profile["height"])
    camera = find_camera(camera_arg)
    cap = cv2.VideoCapture(camera, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"카메라를 열지 못했습니다: {camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    recent = {name: deque(maxlen=stable_frames) for name in SCENE_CLASSES}
    captured: np.ndarray | None = None
    window = "Scene capture - C save / Q quit"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    print("tomato, cheese, berry, bowl을 모두 검출합니다. C: 저장 / Q·Esc: 취소")
    try:
        for _ in range(15):
            cap.read()
        actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if actual != (width, height):
            raise RuntimeError(f"카메라 해상도 불일치: 보정={width}x{height}, 현재={actual[0]}x{actual[1]}")
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("카메라 프레임을 읽지 못했습니다.")
            result = model.predict(frame, conf=confidence, imgsz=640, device="cpu", verbose=False)[0]
            annotated = result.plot(labels=True, conf=True, boxes=True)
            found = {name: [] for name in SCENE_CLASSES}
            if result.boxes is not None and len(result.boxes):
                for coords, class_id, score in zip(
                    result.boxes.xyxy.detach().cpu().numpy(),
                    result.boxes.cls.detach().cpu().numpy().astype(int),
                    result.boxes.conf.detach().cpu().numpy(),
                ):
                    name = str(model.names[int(class_id)])
                    if name in found:
                        x1, y1, x2, y2 = [float(value) for value in coords]
                        found[name].append(((x1 + x2) / 2, (y1 + y2) / 2, float(score)))
            for name in SCENE_CLASSES:
                if found[name]:
                    best = max(found[name], key=lambda item: item[2])
                    recent[name].append(best)
                    cv2.drawMarker(annotated, (round(best[0]), round(best[1])), (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
                else:
                    recent[name].clear()
            stable = [name for name in SCENE_CLASSES if len(recent[name]) == stable_frames]
            cv2.putText(annotated, f"stable {len(stable)}/4: {', '.join(stable)}", (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0) if len(stable) == 4 else (0, 200, 255), 2, cv2.LINE_AA)
            cv2.imshow(window, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                raise KeyboardInterrupt
            if key in (ord("c"), ord("C")):
                if len(stable) != 4:
                    print("네 대상의 검출이 아직 모두 안정되지 않았습니다.")
                    continue
                captured = annotated.copy()
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    detections = {}
    for name in SCENE_CLASSES:
        u, v, score = np.median(np.asarray(recent[name], dtype=float), axis=0)
        x, y = pixel_to_robot_xy(float(u), float(v), correction)
        validate_target(float(u), float(v), x, y, correction)
        detections[name] = {"pixel_u": float(u), "pixel_v": float(v), "confidence": float(score), "robot_x_mm": x, "robot_y_mm": y}
    offset_x, offset_y = manual_offset(correction)
    document = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "camera": {"width": width, "height": height},
        "correction_created_at": correction.get("created_at"),
        "manual_offset_mm": {"x": offset_x, "y": offset_y},
        "classes": list(SCENE_CLASSES),
        "box_size_mm": BOX_SIZE_MM,
        "detections": detections,
    }
    if captured is None:
        raise RuntimeError("장면 이미지를 확보하지 못했습니다.")
    return document, captured


def save_snapshot(document: dict[str, Any], image: np.ndarray, output: Path, image_output: Path) -> None:
    target, picture = output.expanduser().resolve(), image_output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    picture.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not cv2.imwrite(str(picture), image):
        raise OSError(f"이미지 저장 실패: {picture}")


def load_snapshot(path: Path, correction: dict[str, Any]) -> dict[str, Any]:
    snapshot = load_json(path)
    validate_correction(correction)
    if snapshot.get("correction_created_at") != correction.get("created_at"):
        raise ValueError("장면 저장 후 XY 보정이 바뀌었습니다. 장면을 다시 촬영하세요.")
    expected_offset = dict(zip(("x", "y"), manual_offset(correction)))
    if snapshot.get("manual_offset_mm") != expected_offset:
        raise ValueError("장면 저장 후 수동 XY 오프셋이 바뀌었습니다. 장면을 다시 촬영하세요.")
    if snapshot.get("camera") != correction.get("camera"):
        raise ValueError("장면과 XY 보정의 카메라 해상도가 다릅니다.")
    detections = snapshot.get("detections")
    if not isinstance(detections, dict):
        raise ValueError("장면 detections 형식이 잘못됐습니다.")
    for name in SCENE_CLASSES:
        item = detections.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"장면에 {name} 검출값이 없습니다.")
        validate_target(float(item["pixel_u"]), float(item["pixel_v"]), float(item["robot_x_mm"]), float(item["robot_y_mm"]), correction)
    return snapshot


def print_snapshot(snapshot: dict[str, Any]) -> None:
    print("\n[장면 좌표]")
    for name in SCENE_CLASSES:
        item = snapshot["detections"][name]
        print(f"{name:<7} pixel=({float(item['pixel_u']):.1f},{float(item['pixel_v']):.1f}) robot=({float(item['robot_x_mm']):.1f},{float(item['robot_y_mm']):.1f})mm conf={float(item['confidence']):.3f}")
