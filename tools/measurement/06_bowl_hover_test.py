#!/usr/bin/env python3
"""Move only to a safe hover pose above the cached bowl coordinate."""

from __future__ import annotations

import argparse
from pathlib import Path

from robot_common import (
    DEFAULT_MEASUREMENTS, Robot, approach_target, load_poses, move_safe,
    validate_settings,
)
from scene_common import DEFAULT_CORRECTION, DEFAULT_SNAPSHOT, load_json, load_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="저장된 보울 좌표 위 Hover 위치까지만 이동합니다.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--correction", type=Path, default=DEFAULT_CORRECTION)
    parser.add_argument("--measurements", type=Path, default=DEFAULT_MEASUREMENTS)
    parser.add_argument("--hover-height-mm", type=float, default=100.0)
    parser.add_argument("--vel", type=float, default=10.0)
    parser.add_argument("--acc", type=float, default=10.0)
    parser.add_argument("--live", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        correction = load_json(args.correction)
        snapshot = load_snapshot(args.snapshot, correction)
        poses, tcp = load_poses(args.measurements, ("safe_wait", "place_reference"))
        validate_settings(poses, args.hover_height_mm, args.vel, args.acc)
        bowl = snapshot["detections"]["bowl"]
        x, y = float(bowl["robot_x_mm"]), float(bowl["robot_y_mm"])
        reference = poses["place_reference"]["posx"]
        safe_z = float(poses["safe_wait"]["posx"][2])
        hover_z = float(reference[2]) + args.hover_height_mm
        print("\n[Bowl Hover 계획]")
        print(f"bowl XY=({x:.1f}, {y:.1f})mm")
        print(f"place Z={reference[2]:.1f}, hover Z={hover_z:.1f}, safe Z={safe_z:.1f}mm")
        print("이동: 현재 → safe_wait → 보울 안전 높이 → 보울 Hover")
        print("그리퍼와 놓기 Z 하강은 실행하지 않습니다.")
        if not args.live:
            print("DRY RUN 완료. 로봇은 움직이지 않았습니다.")
            return 0

        with Robot(tcp, gripper=False) as robot:
            robot.print_route_start(poses["safe_wait"]["posj"])
            if input("경로·주변·비상정지를 확인한 뒤 MOVE BOWL 입력: ").strip() != "MOVE BOWL":
                print("취소했습니다. 로봇은 움직이지 않았습니다.")
                return 0
            robot.autonomous()
            move_safe(robot, poses, args.vel, args.acc)
            approach_target(robot, x, y, reference, safe_z, args.hover_height_mm, args.vel, args.acc, "bowl")
            print("보울 Hover 완료. 자동 복귀하지 않습니다.")
        return 0
    except KeyboardInterrupt:
        print("\n중단했습니다. 추가 이동 명령은 보내지 않습니다.")
        return 1
    except (FileNotFoundError, KeyError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
