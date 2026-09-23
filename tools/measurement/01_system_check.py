#!/usr/bin/env python3
"""Read-only preflight check for the salad robot measurement session."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "ml" / "models" / "best.pt"
DEFAULT_CALIBRATION = Path.home() / "HamdEyeCal" / "결과" / "T_base_camera.npy"
ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
REQUIRED_DOMAIN_ID = "15"
REQUIRED_CLASSES = {"tomato", "cheese", "berry", "bowl"}
BOX_SIZE_MM = 70


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="로봇·그리퍼·카메라·YOLO·HandEye 연결 상태를 확인합니다. 로봇은 움직이지 않습니다."
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--camera", default="auto")
    return parser.parse_args()


def find_camera(camera_arg: str) -> str | int | None:
    if camera_arg != "auto":
        return int(camera_arg) if camera_arg.isdecimal() else camera_arg
    by_id = Path("/dev/v4l/by-id")
    if by_id.is_dir():
        matches = sorted(by_id.glob("*RealSense*video-index0"))
        if matches:
            return str(matches[0])
    fallback = Path("/dev/video6")
    return str(fallback) if fallback.exists() else None


def check_matrix(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"파일 없음: {path}"
    try:
        matrix = np.load(path)
    except Exception as exc:
        return False, f"로드 실패: {exc}"
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        return False, f"유효한 4x4 행렬이 아님: shape={matrix.shape}"
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-6):
        return False, "동차변환행렬 마지막 행 오류"
    determinant = float(np.linalg.det(matrix[:3, :3]))
    if not np.isclose(determinant, 1.0, atol=0.05):
        return False, f"회전행렬 determinant 오류: {determinant:.4f}"
    translation = matrix[:3, 3]
    return True, f"카메라 위치(m)={np.round(translation, 4).tolist()}"


def main() -> int:
    args = parse_args()
    failures: list[str] = []

    def report(name: str, ok: bool, detail: str) -> None:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failures.append(name)

    domain_id = os.environ.get("ROS_DOMAIN_ID")
    report(
        "ROS_DOMAIN_ID",
        domain_id == REQUIRED_DOMAIN_ID,
        repr(domain_id),
    )
    print(f"[INFO] 집을 클래스: tomato, cheese, berry / 공통 박스: {BOX_SIZE_MM} mm")

    model_path = args.model.expanduser().resolve()
    if model_path.is_file():
        try:
            model = YOLO(str(model_path))
            raw_names = model.names.values() if isinstance(model.names, dict) else model.names
            names = set(str(name) for name in raw_names)
            missing = sorted(REQUIRED_CLASSES - names)
            report(
                "YOLO model",
                not missing,
                f"{model_path}, 누락 클래스={missing or '없음'}",
            )
        except Exception as exc:
            report("YOLO model", False, f"로드 실패: {exc}")
    else:
        report("YOLO model", False, f"파일 없음: {model_path}")

    calibration_path = args.calibration.expanduser().resolve()
    matrix_ok, matrix_detail = check_matrix(calibration_path)
    report("HandEye matrix", matrix_ok, matrix_detail)

    camera = find_camera(args.camera)
    if camera is None:
        report("RealSense RGB", False, "장치를 찾지 못함")
    else:
        cap = cv2.VideoCapture(camera, cv2.CAP_V4L2)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        detail = (
            f"{camera}, frame={frame.shape[1]}x{frame.shape[0]}"
            if ok and frame is not None
            else f"{camera}, 프레임 읽기 실패"
        )
        report("RealSense RGB", bool(ok), detail)

    node = None
    rclpy = None
    try:
        import rclpy as imported_rclpy
        import DR_init

        rclpy = imported_rclpy
        DR_init.__dsr__id = ROBOT_ID
        DR_init.__dsr__model = ROBOT_MODEL
        if not rclpy.ok():
            rclpy.init()
        node = rclpy.create_node("salad_system_check", namespace=ROBOT_ID)
        DR_init.__dsr__node = node

        import DSR_ROBOT2 as dsr
        from DSR_ROBOT2 import get_current_posj, get_current_posx, get_robot_mode, get_tcp
        from dsr_gripper_interfaces.srv import GripperCmd

        robot_ok = dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=5.0)
        if robot_ok:
            posj = get_current_posj()
            posx, _ = get_current_posx()
            report(
                "E0509 robot",
                True,
                f"mode={get_robot_mode()}, posj={[round(float(v), 1) for v in posj]}",
            )
            print("[INFO] 현재 posx:", [round(float(v), 1) for v in posx])
            report("Active TCP", True, str(get_tcp()))
        else:
            report("E0509 robot", False, "bringup 서비스를 찾지 못함")

        gripper_client = node.create_client(GripperCmd, f"/{ROBOT_ID}/gripper/cmd")
        report(
            "Gripper service",
            gripper_client.wait_for_service(timeout_sec=3.0),
            f"/{ROBOT_ID}/gripper/cmd",
        )
    except Exception as exc:
        report("ROS/Doosan", False, f"연결 실패: {exc}")
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy is not None and rclpy.ok():
            rclpy.shutdown()

    if failures:
        print("\n점검 실패:", ", ".join(failures))
        print("실패 항목을 해결한 뒤 측정을 시작하세요.")
        return 1
    print("\n전체 점검 통과. 이 스크립트는 로봇을 움직이지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
