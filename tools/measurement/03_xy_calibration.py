#!/usr/bin/env python3
"""Collect pixel-to-robot XY samples and fit a planar homography.

No robot motion command is sent. During ``collect`` the operator moves the TCP
manually to the physical center of the already captured object and confirms
the current pose. The fitted mapping is valid only while the camera stays fixed
and the same resolution is used.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "ml" / "models" / "best.pt"
DEFAULT_RECORDS = PROJECT_ROOT / "records" / "xy_calibration.csv"
DEFAULT_CORRECTION = PROJECT_ROOT / "config" / "xy_correction.json"
ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
REQUIRED_DOMAIN_ID = "15"
SCENE_CLASSES = ("tomato", "cheese", "berry", "bowl")
PICK_CLASSES = ("tomato", "cheese", "berry")
BOX_SIZE_MM = 70
WINDOW_NAME = "XY calibration - C capture / Q quit"
CSV_FIELDS = (
    "timestamp",
    "point_name",
    "class_name",
    "box_size_mm",
    "camera_width",
    "camera_height",
    "pixel_u",
    "pixel_v",
    "confidence",
    "actual_x_mm",
    "actual_y_mm",
    "actual_z_mm",
    "actual_rx_deg",
    "actual_ry_deg",
    "actual_rz_deg",
    "handeye_x_mm",
    "handeye_y_mm",
    "handeye_z_mm",
    "tcp",
    "note",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="카메라 픽셀과 실제 로봇 XY 대응점을 수집하고 보정식을 계산합니다."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="보정점 한 개 수집")
    collect.add_argument("--class-name", choices=SCENE_CLASSES, required=True)
    collect.add_argument("--point-name", required=True, help="예: left_top, center")
    collect.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    collect.add_argument("--camera", default="auto")
    collect.add_argument("--width", type=int, default=640)
    collect.add_argument("--height", type=int, default=480)
    collect.add_argument("--fps", type=int, default=30)
    collect.add_argument("--conf", type=float, default=0.5)
    collect.add_argument("--stable-frames", type=int, default=10)
    collect.add_argument("--output", type=Path, default=DEFAULT_RECORDS)
    collect.add_argument("--note", default="")
    collect.add_argument(
        "--handeye-xyz-mm",
        type=float,
        nargs=3,
        metavar=("X", "Y", "Z"),
        help="기존 HandEye 계산값도 같이 기록하고 싶을 때 입력",
    )

    fit = subparsers.add_parser("fit", help="수집값으로 pixel→robot XY 보정식 생성")
    fit.add_argument("--input", type=Path, default=DEFAULT_RECORDS)
    fit.add_argument("--output", type=Path, default=DEFAULT_CORRECTION)

    listing = subparsers.add_parser("list", help="현재 수집값 표시")
    listing.add_argument("--input", type=Path, default=DEFAULT_RECORDS)
    return parser


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


def capture_detection(args: argparse.Namespace) -> tuple[float, float, float, int, int]:
    model_path = args.model.expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"모델이 없습니다: {model_path}")
    model = YOLO(str(model_path))
    available = set(str(name) for name in model.names.values())
    if args.class_name not in available:
        raise ValueError(f"모델에 {args.class_name!r} 클래스가 없습니다.")

    camera = find_camera(args.camera)
    cap = cv2.VideoCapture(camera, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"카메라를 열지 못했습니다: {camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    recent: deque[tuple[float, float, float]] = deque(maxlen=args.stable_frames)
    print(f"{args.class_name} 박스를 검출합니다. 안정되면 C, 취소는 Q/Esc")
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    try:
        for _ in range(15):
            cap.read()
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("카메라 프레임을 읽지 못했습니다.")
            result = model.predict(frame, conf=args.conf, imgsz=640, device="cpu", verbose=False)[0]
            annotated = result.plot(labels=True, conf=True, boxes=True)

            best: tuple[float, float, float] | None = None
            boxes = result.boxes
            if boxes is not None and len(boxes):
                xyxy = boxes.xyxy.detach().cpu().numpy()
                classes = boxes.cls.detach().cpu().numpy().astype(int)
                confidences = boxes.conf.detach().cpu().numpy()
                matches = []
                for coords, class_id, confidence in zip(xyxy, classes, confidences):
                    if str(model.names[int(class_id)]) == args.class_name:
                        x1, y1, x2, y2 = [float(v) for v in coords]
                        matches.append(((x1 + x2) / 2, (y1 + y2) / 2, float(confidence)))
                if matches:
                    best = max(matches, key=lambda item: item[2])
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

            status = f"{args.class_name} stable {len(recent)}/{args.stable_frames}"
            cv2.putText(
                annotated,
                status,
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0) if len(recent) == args.stable_frames else (0, 200, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(WINDOW_NAME, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                raise KeyboardInterrupt
            if key in (ord("c"), ord("C")):
                if len(recent) < args.stable_frames:
                    print("검출이 아직 안정되지 않았습니다.")
                    continue
                values = np.asarray(recent, dtype=float)
                u, v, confidence = np.median(values, axis=0)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                return float(u), float(v), float(confidence), width, height
    finally:
        cap.release()
        cv2.destroyAllWindows()


def read_robot_pose() -> tuple[list[float], int, str]:
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
    node = rclpy.create_node("salad_xy_sample", namespace=ROBOT_ID)
    DR_init.__dsr__node = node
    try:
        import DSR_ROBOT2 as dsr
        from DSR_ROBOT2 import get_current_posx, get_tcp

        if not dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=10.0):
            raise RuntimeError("로봇 서비스를 찾지 못했습니다.")
        pose, solution = get_current_posx()
        return [float(v) for v in pose], int(solution), str(get_tcp())
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def append_sample(path: Path, row: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def collect(args: argparse.Namespace) -> int:
    u, v, confidence, width, height = capture_detection(args)
    print(f"\n검출 고정: {args.class_name}, pixel=({u:.1f}, {v:.1f}), conf={confidence:.3f}")
    print("이제 TCP 중심을 해당 박스 중심 위의 안전한 높이로 수동 이동하세요.")
    print("XY만 보정하므로 박스를 건드리지 말고, 활성 TCP와 집기 방향을 맞추세요.")
    if input("정확히 맞췄으면 READ 입력: ").strip() != "READ":
        print("취소했습니다. 기록하지 않았습니다.")
        return 1

    pose, solution, tcp_name = read_robot_pose()
    print("읽은 실제 posx:", [round(v, 2) for v in pose], "solution:", solution)
    if input("이 값을 저장하려면 SAVE 입력: ").strip() != "SAVE":
        print("취소했습니다. 기록하지 않았습니다.")
        return 1

    handeye = args.handeye_xyz_mm or ("", "", "")
    row = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "point_name": args.point_name,
        "class_name": args.class_name,
        "box_size_mm": BOX_SIZE_MM if args.class_name in PICK_CLASSES else "",
        "camera_width": width,
        "camera_height": height,
        "pixel_u": f"{u:.6f}",
        "pixel_v": f"{v:.6f}",
        "confidence": f"{confidence:.6f}",
        "actual_x_mm": f"{pose[0]:.6f}",
        "actual_y_mm": f"{pose[1]:.6f}",
        "actual_z_mm": f"{pose[2]:.6f}",
        "actual_rx_deg": f"{pose[3]:.6f}",
        "actual_ry_deg": f"{pose[4]:.6f}",
        "actual_rz_deg": f"{pose[5]:.6f}",
        "handeye_x_mm": handeye[0],
        "handeye_y_mm": handeye[1],
        "handeye_z_mm": handeye[2],
        "tcp": tcp_name,
        "note": args.note,
    }
    append_sample(args.output, row)
    print("보정점 저장:", args.output.expanduser().resolve())
    return 0


def load_rows(path: Path) -> list[dict[str, str]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"수집 파일이 없습니다: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fit(args: argparse.Namespace) -> int:
    rows = load_rows(args.input)
    if len(rows) < 5:
        raise ValueError(f"최소 5점이 필요합니다. 현재 {len(rows)}점입니다.")
    profiles = {(int(row["camera_width"]), int(row["camera_height"])) for row in rows}
    if len(profiles) != 1:
        raise ValueError(f"서로 다른 카메라 해상도가 섞였습니다: {sorted(profiles)}")

    pixel = np.array([[float(row["pixel_u"]), float(row["pixel_v"])] for row in rows])
    robot_xy = np.array(
        [[float(row["actual_x_mm"]), float(row["actual_y_mm"])] for row in rows]
    )
    homography, _ = cv2.findHomography(pixel.astype(np.float64), robot_xy.astype(np.float64), 0)
    if homography is None or not np.isfinite(homography).all():
        raise ValueError("homography 계산 실패. 측정점이 한 직선에 몰리지 않았는지 확인하세요.")

    predicted = cv2.perspectiveTransform(
        pixel.reshape(-1, 1, 2).astype(np.float64), homography
    ).reshape(-1, 2)
    errors = np.linalg.norm(predicted - robot_xy, axis=1)
    rms = float(np.sqrt(np.mean(np.square(errors))))
    maximum = float(np.max(errors))
    hull = cv2.convexHull(pixel.astype(np.float32)).reshape(-1, 2)
    width, height = next(iter(profiles))

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "pixel_to_robot_xy_homography",
        "camera": {"width": width, "height": height},
        "pick_classes": list(PICK_CLASSES),
        "box_size_mm": BOX_SIZE_MM,
        "sample_count": len(rows),
        "matrix_3x3": homography.tolist(),
        "pixel_convex_hull": hull.tolist(),
        "robot_xy_bounds_mm": {
            "x_min": float(robot_xy[:, 0].min()),
            "x_max": float(robot_xy[:, 0].max()),
            "y_min": float(robot_xy[:, 1].min()),
            "y_max": float(robot_xy[:, 1].max()),
        },
        "fit_error_mm": {"rms": rms, "max": maximum},
        "source_csv": str(args.input.expanduser().resolve()),
    }
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"보정식 저장: {output}")
    print(f"샘플: {len(rows)}점 / RMS 오차: {rms:.2f} mm / 최대 오차: {maximum:.2f} mm")
    if maximum > 20:
        print("경고: 최대 오차가 20mm를 넘습니다. 측정점을 다시 확인하세요.")
    return 0


def list_rows(args: argparse.Namespace) -> int:
    rows = load_rows(args.input)
    for index, row in enumerate(rows, start=1):
        print(
            f"{index:2d}. {row['point_name']:<16} {row['class_name']:<8} "
            f"pixel=({float(row['pixel_u']):.1f},{float(row['pixel_v']):.1f}) "
            f"actual=({float(row['actual_x_mm']):.1f},{float(row['actual_y_mm']):.1f})"
        )
    print("합계:", len(rows), "점")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "collect":
            return collect(args)
        if args.command == "fit":
            return fit(args)
        return list_rows(args)
    except KeyboardInterrupt:
        print("\n사용자가 취소했습니다.")
        return 1
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
