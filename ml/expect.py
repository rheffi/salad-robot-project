#!/usr/bin/env python3
"""Run the trained salad YOLO model on the RealSense RGB stream.

Controls:
    q / Esc  Quit
    s        Save the currently annotated frame
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
from ultralytics import YOLO


ML_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ML_ROOT / "models" / "best.pt"
DEFAULT_SAVE_DIR = ML_ROOT / "test_outputs"
REALSENSE_BY_ID_GLOB = "*RealSense*video-index0"
REALSENSE_FALLBACK = Path("/dev/video6")
WINDOW_NAME = "Salad YOLO - RealSense RGB"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RealSense RGB 영상으로 학습된 샐러드 YOLO 모델을 테스트합니다."
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "--camera",
        default="auto",
        help="auto, /dev/video6 같은 경로 또는 OpenCV 카메라 번호",
    )
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.model.expanduser().is_file():
        raise FileNotFoundError(f"학습 모델이 없습니다: {args.model}")
    if not 0.0 < args.conf <= 1.0:
        raise ValueError("conf는 0보다 크고 1 이하여야 합니다.")
    if args.imgsz < 32 or args.width < 1 or args.height < 1 or args.fps < 1:
        raise ValueError("imgsz/width/height/fps 값을 확인하세요.")


def camera_candidates(camera_arg: str) -> list[str | int]:
    if camera_arg != "auto":
        if camera_arg.isdecimal():
            return [int(camera_arg)]
        return [str(Path(camera_arg).expanduser())]

    candidates: list[str | int] = []
    by_id_root = Path("/dev/v4l/by-id")
    if by_id_root.is_dir():
        candidates.extend(
            str(path) for path in sorted(by_id_root.glob(REALSENSE_BY_ID_GLOB))
        )
    if REALSENSE_FALLBACK.exists():
        candidates.append(str(REALSENSE_FALLBACK))
    return list(dict.fromkeys(candidates))


def open_camera(
    camera_arg: str, width: int, height: int, fps: int
) -> tuple[cv2.VideoCapture, str | int]:
    candidates = camera_candidates(camera_arg)
    if not candidates:
        raise RuntimeError(
            "RealSense RGB 장치를 찾지 못했습니다. 카메라 연결 후 "
            "'v4l2-ctl --list-devices'로 장치를 확인하세요."
        )

    failures: list[str] = []
    for candidate in candidates:
        cap = cv2.VideoCapture(candidate, cv2.CAP_V4L2)
        if not cap.isOpened():
            failures.append(str(candidate))
            cap.release()
            continue

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # The first frames can be dark while auto exposure settles.
        frame_ok = False
        for _ in range(15):
            frame_ok, _ = cap.read()
            if not frame_ok:
                break
        if frame_ok:
            return cap, candidate

        failures.append(str(candidate))
        cap.release()

    raise RuntimeError(
        "카메라를 열었지만 프레임을 받지 못했습니다: "
        f"{', '.join(failures)}. ch3/ch4나 다른 프로그램이 카메라를 사용 중인지 확인하세요."
    )


def class_summary(result: object, names: dict[int, str] | list[str]) -> str:
    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.cls is None or len(boxes) == 0:
        return "No detections"

    counts: Counter[str] = Counter()
    for class_id in boxes.cls.detach().cpu().tolist():
        index = int(class_id)
        name = names[index] if isinstance(names, list) else names.get(index, str(index))
        counts[str(name)] += 1
    return "  ".join(f"{name}: {count}" for name, count in sorted(counts.items()))


def draw_status(frame: object, fps: float, summary: str) -> None:
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 62), (20, 20, 20), -1)
    cv2.putText(
        frame,
        f"FPS: {fps:.1f}",
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (80, 255, 80),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        summary,
        (12, 51),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def save_snapshot(frame: object, save_dir: Path) -> None:
    save_dir = save_dir.expanduser().resolve()
    save_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = save_dir / f"detection_{timestamp}.jpg"
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"이미지 저장에 실패했습니다: {path}")
    print("화면 저장:", path)


def run(args: argparse.Namespace) -> None:
    model_path = args.model.expanduser().resolve()
    print("모델 로딩:", model_path)
    model = YOLO(str(model_path))
    print("모델 클래스:", model.names)

    cap, selected_camera = open_camera(
        args.camera, args.width, args.height, args.fps
    )
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(
        f"카메라 시작: {selected_camera} / "
        f"{actual_width}x{actual_height}@{actual_fps:g}"
    )
    print("박스를 카메라 앞에 보여주세요. Q/Esc: 종료, S: 화면 저장")

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    smoothed_fps = 0.0
    previous_time = time.perf_counter()
    consecutive_failures = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    raise RuntimeError("카메라 프레임을 연속 30회 읽지 못했습니다.")
                continue
            consecutive_failures = 0

            result = model.predict(
                source=frame,
                conf=args.conf,
                imgsz=args.imgsz,
                device=args.device,
                verbose=False,
            )[0]
            annotated = result.plot(labels=True, conf=True, boxes=True)

            now = time.perf_counter()
            instant_fps = 1.0 / max(now - previous_time, 1e-9)
            previous_time = now
            smoothed_fps = (
                instant_fps
                if smoothed_fps == 0.0
                else 0.9 * smoothed_fps + 0.1 * instant_fps
            )
            summary = class_summary(result, model.names)
            draw_status(annotated, smoothed_fps, summary)

            cv2.imshow(WINDOW_NAME, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("s"), ord("S")):
                save_snapshot(annotated, args.save_dir)
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("카메라 종료 완료")


def main() -> int:
    try:
        args = parse_args()
        validate_args(args)
        run(args)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
