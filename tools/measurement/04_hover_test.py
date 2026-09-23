#!/usr/bin/env python3
"""Detect one 70 mm ingredient box and optionally move to a safe hover pose.

Default mode is dry-run. Actual motion requires ``--live`` and typing MOVE.
The script never descends to the grasp Z and never operates the gripper.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import yaml
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "ml" / "models" / "best.pt"
DEFAULT_MEASUREMENTS = PROJECT_ROOT / "config" / "robot_measurements.yaml"
DEFAULT_CORRECTION = PROJECT_ROOT / "config" / "xy_correction.json"
ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
REQUIRED_DOMAIN_ID = "15"
PICK_CLASSES = ("tomato", "cheese", "berry")
BOX_SIZE_MM = 70
WINDOW_NAME = "Hover test - C lock target / Q quit"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="7cm 재료 박스의 보정 XY를 계산하고 물체 위까지만 이동합니다."
    )
    parser.add_argument("--class-name", choices=PICK_CLASSES, required=True)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--measurements", type=Path, default=DEFAULT_MEASUREMENTS)
    parser.add_argument("--correction", type=Path, default=DEFAULT_CORRECTION)
    parser.add_argument("--camera", default="auto")
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--stable-frames", type=int, default=10)
    parser.add_argument("--hover-height-mm", type=float, default=100.0)
    parser.add_argument("--vel", type=float, default=10.0)
    parser.add_argument("--acc", type=float, default=10.0)
    parser.add_argument("--live", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"파일이 없습니다: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 최상위 형식 오류: {path}")
    return value


def load_yaml(path: Path) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"파일이 없습니다: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"YAML 최상위 형식 오류: {path}")
    return value


def find_camera(camera_arg: str) -> str | int:
    if camera_arg != "auto":
        return int(camera_arg) if camera_arg.isdecimal() else camera_arg
    by_id = Path("/dev/v4l/by-id")
    if by_id.is_dir():
        matches = sorted(by_id.glob("*RealSense*video-index0"))
        if matches:
            return str(matches[0])
    if Path("/dev/video6").exists():
        return "/dev/video6"
    raise RuntimeError("RealSense RGB 장치를 찾지 못했습니다.")


def capture_target(
    model: YOLO,
    class_name: str,
    camera_arg: str,
    confidence: float,
    stable_frames: int,
    expected_width: int,
    expected_height: int,
) -> tuple[float, float, float]:
    camera = find_camera(camera_arg)
    cap = cv2.VideoCapture(camera, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"카메라를 열지 못했습니다: {camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, expected_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, expected_height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    recent: deque[tuple[float, float, float]] = deque(maxlen=stable_frames)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    print(f"{class_name} 박스를 카메라에 보여주세요. C: 좌표 고정, Q/Esc: 취소")
    try:
        for _ in range(15):
            cap.read()
        actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (actual_width, actual_height) != (expected_width, expected_height):
            raise RuntimeError(
                f"카메라 해상도가 보정값과 다릅니다. "
                f"보정={expected_width}x{expected_height}, 현재={actual_width}x{actual_height}"
            )

        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("카메라 프레임을 읽지 못했습니다.")
            result = model.predict(frame, conf=confidence, imgsz=640, device="cpu", verbose=False)[0]
            annotated = result.plot(labels=True, conf=True, boxes=True)
            best: tuple[float, float, float] | None = None
            if result.boxes is not None and len(result.boxes):
                xyxy = result.boxes.xyxy.detach().cpu().numpy()
                classes = result.boxes.cls.detach().cpu().numpy().astype(int)
                confidences = result.boxes.conf.detach().cpu().numpy()
                candidates = []
                for coords, class_id, score in zip(xyxy, classes, confidences):
                    if str(model.names[int(class_id)]) == class_name:
                        x1, y1, x2, y2 = [float(v) for v in coords]
                        candidates.append(((x1 + x2) / 2, (y1 + y2) / 2, float(score)))
                if candidates:
                    best = max(candidates, key=lambda item: item[2])
                    recent.append(best)
                    cv2.drawMarker(
                        annotated,
                        (round(best[0]), round(best[1])),
                        (0, 0, 255),
                        cv2.MARKER_CROSS,
                        28,
                        2,
                    )
            if best is None:
                recent.clear()

            cv2.putText(
                annotated,
                f"{class_name} stable {len(recent)}/{stable_frames}",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0) if len(recent) == stable_frames else (0, 200, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(WINDOW_NAME, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                raise KeyboardInterrupt
            if key in (ord("c"), ord("C")):
                if len(recent) < stable_frames:
                    print("검출이 아직 안정되지 않았습니다.")
                    continue
                u, v, score = np.median(np.asarray(recent, dtype=float), axis=0)
                return float(u), float(v), float(score)
    finally:
        cap.release()
        cv2.destroyAllWindows()


def pixel_to_robot_xy(u: float, v: float, correction: dict) -> tuple[float, float]:
    matrix = np.asarray(correction.get("matrix_3x3"), dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("xy_correction의 matrix_3x3 형식이 잘못됐습니다.")
    source = np.array([u, v, 1.0], dtype=float)
    target = matrix @ source
    if abs(target[2]) < 1e-9:
        raise ValueError("homography 계산 결과의 분모가 0입니다.")
    offset = correction.get("manual_offset_mm", {})
    if not isinstance(offset, dict):
        raise ValueError("manual_offset_mm 형식이 잘못됐습니다.")
    offset_x = float(offset.get("x", 0.0))
    offset_y = float(offset.get("y", 0.0))
    if not np.isfinite([offset_x, offset_y]).all():
        raise ValueError("manual_offset_mm에 유효하지 않은 값이 있습니다.")
    return (
        float(target[0] / target[2]) + offset_x,
        float(target[1] / target[2]) + offset_y,
    )


def validate_target(u: float, v: float, x: float, y: float, correction: dict) -> None:
    hull = np.asarray(correction.get("pixel_convex_hull"), dtype=np.float32)
    if hull.ndim != 2 or hull.shape[1] != 2:
        raise ValueError("pixel_convex_hull 형식이 잘못됐습니다.")
    if cv2.pointPolygonTest(hull, (float(u), float(v)), False) < 0:
        raise ValueError("검출점이 XY 보정점 영역 밖입니다. 외삽 이동을 거부합니다.")

    bounds = correction.get("robot_xy_bounds_mm", {})
    if not (
        float(bounds["x_min"]) <= x <= float(bounds["x_max"])
        and float(bounds["y_min"]) <= y <= float(bounds["y_max"])
    ):
        raise ValueError("계산 XY가 측정된 로봇 작업영역 밖입니다.")
    radius = float(np.hypot(x, y))
    if not 150.0 < radius < 850.0:
        raise ValueError(f"목표 수평거리 {radius:.1f}mm가 허용 범위 밖입니다.")


def move_live(
    target_x: float,
    target_y: float,
    hover_z: float,
    orientation: list[float],
    tcp_expected: str,
    safe_wait_joints: list[float],
    safe_wait_z: float,
    vel: float,
    acc: float,
) -> None:
    if os.environ.get("ROS_DOMAIN_ID") != REQUIRED_DOMAIN_ID:
        raise RuntimeError(
            f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID')!r}. "
            f"export ROS_DOMAIN_ID={REQUIRED_DOMAIN_ID} 를 실행하세요."
        )
    import rclpy
    import DR_init

    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL
    rclpy.init()
    node = rclpy.create_node("salad_hover_test", namespace=ROBOT_ID)
    DR_init.__dsr__node = node
    try:
        import DSR_ROBOT2 as dsr
        from DSR_ROBOT2 import (
            DR_BASE,
            DR_MV_MOD_ABS,
            ROBOT_MODE_AUTONOMOUS,
            get_current_posj,
            get_current_posx,
            get_tcp,
            movej,
            movel,
            posj,
            posx,
            set_robot_mode,
        )

        if not dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=10.0):
            raise RuntimeError("로봇 서비스를 찾지 못했습니다.")
        actual_tcp = str(get_tcp())
        if actual_tcp != tcp_expected:
            raise RuntimeError(f"TCP 불일치: 기록={tcp_expected!r}, 현재={actual_tcp!r}")

        current_joints = [float(value) for value in get_current_posj()]
        current_raw, _ = get_current_posx()
        current = [float(value) for value in current_raw]
        print("현재 posj:", [round(v, 1) for v in current_joints])
        print("현재 posx:", [round(v, 1) for v in current])
        print("목표 safe_wait posj:", [round(v, 1) for v in safe_wait_joints])
        print(
            "이동 순서: safe_wait로 이동 → 안전 높이에서 방향 정렬·수평 이동 → "
            f"({target_x:.1f}, {target_y:.1f}, {hover_z:.1f}) hover"
        )
        print("주의: 현재 자세에서 safe_wait까지의 movej 경로는 충돌 회피를 계산하지 않습니다.")
        print("그리퍼 동작과 집기 Z 하강은 하지 않습니다.")
        if input("현재→safe_wait 경로·주변·비상정지를 확인한 뒤 MOVE 입력: ").strip() != "MOVE":
            print("취소했습니다. 로봇은 움직이지 않았습니다.")
            return
        if set_robot_mode(ROBOT_MODE_AUTONOMOUS) != 0:
            raise RuntimeError("AUTONOMOUS 모드 전환 실패")

        if movej(posj(safe_wait_joints), vel=vel, acc=acc) != 0:
            raise RuntimeError("safe_wait 이동 실패")
        horizontal = posx(target_x, target_y, safe_wait_z, *orientation)
        if movel(horizontal, vel=vel, acc=acc, ref=DR_BASE, mod=DR_MV_MOD_ABS) != 0:
            raise RuntimeError("안전 높이 방향 정렬·수평 이동 실패")
        hover = posx(target_x, target_y, hover_z, *orientation)
        if movel(hover, vel=vel, acc=acc, ref=DR_BASE, mod=DR_MV_MOD_ABS) != 0:
            raise RuntimeError("hover Z 이동 실패")
        print("hover 이동 완료. 자동 복귀하지 않으므로 위치를 확인하세요.")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main() -> int:
    args = parse_args()
    try:
        if not 0.0 < args.conf <= 1.0 or args.stable_frames < 3:
            raise ValueError("conf 또는 stable-frames 값을 확인하세요.")
        measurements = load_yaml(args.measurements)
        correction = load_json(args.correction)
        if correction.get("method") != "pixel_to_robot_xy_homography":
            raise ValueError("지원하지 않는 XY 보정 방식입니다.")
        if float(correction.get("fit_error_mm", {}).get("max", 1e9)) > 30.0:
            raise ValueError("XY 보정 최대 오차가 30mm를 넘습니다. 보정점을 다시 측정하세요.")

        poses = measurements.get("poses", {})
        required_entries = {}
        for pose_name in ("safe_wait", "pick_reference"):
            entry = poses.get(pose_name)
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{pose_name} 자세가 없습니다. "
                    f"02_pose_recorder.py --name {pose_name}로 기록하세요."
                )
            required_entries[pose_name] = entry

        safe_wait_entry = required_entries["safe_wait"]
        pick_entry = required_entries["pick_reference"]
        safe_wait_joints = [float(v) for v in safe_wait_entry["posj_deg"]]
        safe_wait_pose = [float(v) for v in safe_wait_entry["posx_mm_deg"]]
        pick_pose = [float(v) for v in pick_entry["posx_mm_deg"]]
        if len(safe_wait_joints) != 6:
            raise ValueError("safe_wait posj 형식이 잘못됐습니다.")
        if len(safe_wait_pose) != 6:
            raise ValueError("safe_wait posx 형식이 잘못됐습니다.")
        if len(pick_pose) != 6:
            raise ValueError("pick_reference posx 형식이 잘못됐습니다.")
        tcp_expected = str(pick_entry.get("tcp", ""))
        for pose_name, entry in required_entries.items():
            recorded_tcp = str(entry.get("tcp", ""))
            if recorded_tcp != tcp_expected:
                raise ValueError(
                    f"기록된 TCP가 일치하지 않습니다: "
                    f"pick_reference={tcp_expected!r}, {pose_name}={recorded_tcp!r}"
                )
        hover_z = pick_pose[2] + args.hover_height_mm
        safe_wait_z = safe_wait_pose[2]
        if safe_wait_z <= hover_z:
            raise ValueError(
                f"safe_wait Z={safe_wait_z:.1f}mm가 hover Z={hover_z:.1f}mm보다 높아야 합니다."
            )
        orientation = pick_pose[3:6]

        model_path = args.model.expanduser().resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"모델이 없습니다: {model_path}")
        model = YOLO(str(model_path))
        profile = correction["camera"]
        u, v, score = capture_target(
            model,
            args.class_name,
            args.camera,
            args.conf,
            args.stable_frames,
            int(profile["width"]),
            int(profile["height"]),
        )
        target_x, target_y = pixel_to_robot_xy(u, v, correction)
        validate_target(u, v, target_x, target_y, correction)

        print("\n[Hover 계산 결과]")
        print(f"class={args.class_name}, box={BOX_SIZE_MM}mm, conf={score:.3f}")
        print(f"pixel=({u:.1f}, {v:.1f})")
        offset = correction.get("manual_offset_mm", {})
        print(
            "manual offset="
            f"({float(offset.get('x', 0.0)):+.1f}, {float(offset.get('y', 0.0)):+.1f}) mm"
        )
        print(f"robot XY=({target_x:.1f}, {target_y:.1f}) mm")
        print(f"pick Z={pick_pose[2]:.1f}, hover Z={hover_z:.1f} mm")
        print(f"orientation={np.round(orientation, 2).tolist()}")

        if not args.live:
            print("DRY RUN 완료. 로봇은 움직이지 않았습니다. 실제 시험 때만 --live를 추가하세요.")
            return 0
        move_live(
            target_x,
            target_y,
            hover_z,
            orientation,
            tcp_expected,
            safe_wait_joints,
            safe_wait_z,
            args.vel,
            args.acc,
        )
        return 0
    except KeyboardInterrupt:
        print("\n사용자가 취소했습니다. 추가 이동 명령은 보내지 않습니다.")
        return 1
    except (FileNotFoundError, KeyError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
