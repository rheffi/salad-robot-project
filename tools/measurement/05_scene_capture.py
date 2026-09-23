#!/usr/bin/env python3
"""Capture and cache tomato, cheese, berry and bowl coordinates once."""

from __future__ import annotations

import argparse
from pathlib import Path

from scene_common import (
    DEFAULT_CORRECTION, DEFAULT_MODEL, DEFAULT_SNAPSHOT, DEFAULT_SNAPSHOT_IMAGE,
    capture_scene, load_json, print_snapshot, save_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="최초 장면의 재료 3개와 보울 좌표를 한 번에 저장합니다.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--correction", type=Path, default=DEFAULT_CORRECTION)
    parser.add_argument("--camera", default="auto")
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--stable-frames", type=int, default=5)
    parser.add_argument("--angles", action="store_true", help="70mm 박스 외곽과 로봇 기준 각도 검출")
    parser.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--image-output", type=Path, default=DEFAULT_SNAPSHOT_IMAGE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        correction = load_json(args.correction)
        snapshot, image = capture_scene(
            args.model, correction, args.camera, args.conf, args.stable_frames,
            angles=args.angles,
        )
        print_snapshot(snapshot)
        save_snapshot(snapshot, image, args.output, args.image_output)
        print("\n장면 JSON 저장:", args.output.expanduser().resolve())
        print("장면 이미지 저장:", args.image_output.expanduser().resolve())
        print("물체나 보울이 움직이면 이 파일을 사용하지 말고 다시 촬영하세요.")
        return 0
    except KeyboardInterrupt:
        print("\n사용자가 취소했습니다.")
        return 1
    except (FileNotFoundError, KeyError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
