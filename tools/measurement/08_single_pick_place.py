#!/usr/bin/env python3
"""Pick one cached ingredient and place it at the cached bowl coordinate."""

from __future__ import annotations

import argparse
from pathlib import Path
import salad_workflow as flow

from robot_common import (
    CLOSE_POSITION, DEFAULT_MEASUREMENTS, GRIPPER_CURRENT, OPEN_POSITION,
    Robot, load_poses, validate_settings,
    add_rotation_arguments, pick_reference_for_item,
)
from scene_common import (
    DEFAULT_CORRECTION, DEFAULT_SNAPSHOT, PICK_CLASSES, load_json, load_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="재료 하나를 집어 저장된 보울 좌표에 놓습니다.")
    parser.add_argument("--class-name", choices=PICK_CLASSES, required=True)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--correction", type=Path, default=DEFAULT_CORRECTION)
    parser.add_argument("--measurements", type=Path, default=DEFAULT_MEASUREMENTS)
    parser.add_argument("--hover-height-mm", type=float, default=100.0)
    parser.add_argument("--vel", type=float, default=10.0)
    parser.add_argument("--acc", type=float, default=10.0)
    parser.add_argument("--close-position", type=int, default=CLOSE_POSITION)
    parser.add_argument("--current", type=int, default=GRIPPER_CURRENT)
    parser.add_argument("--live", action="store_true")
    add_rotation_arguments(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if not 0 <= args.close_position < OPEN_POSITION or not 1 <= args.current <= 400:
            raise ValueError("close-position은 0~749, current는 1~400이어야 합니다.")
        correction = load_json(args.correction)
        snapshot = load_snapshot(args.snapshot, correction)
        names = ("home", "safe_wait", "pick_reference", "place_reference")
        poses, tcp = load_poses(args.measurements, names)
        validate_settings(poses, args.hover_height_mm, args.vel, args.acc)
        item, bowl = snapshot["detections"][args.class_name], snapshot["detections"]["bowl"]
        item_xy = float(item["robot_x_mm"]), float(item["robot_y_mm"])
        bowl_xy = float(bowl["robot_x_mm"]), float(bowl["robot_y_mm"])
        pick_ref, place_ref = poses["pick_reference"]["posx"], poses["place_reference"]["posx"]
        pick_ref = pick_reference_for_item(pick_ref, item, rotate=args.rotate,
                                           reference_yaw=args.reference_yaw_deg)
        print("\n[단일 집기·놓기 계획]")
        print(f"{args.class_name} XY=({item_xy[0]:.1f}, {item_xy[1]:.1f}), pick Z={pick_ref[2]:.1f}mm")
        print(f"bowl XY=({bowl_xy[0]:.1f}, {bowl_xy[1]:.1f}), place Z={place_ref[2]:.1f}mm")
        print(f"gripper={args.close_position}/{args.current}, 이동 종료=HOME")
        if not args.live:
            print("DRY RUN 완료. 로봇과 그리퍼는 움직이지 않았습니다.")
            return 0

        with Robot(tcp, gripper=True) as robot:
            robot.print_route_start(poses["safe_wait"]["posj"])
            if input("전체 경로·주변·비상정지를 확인한 뒤 RUN ONE 입력: ").strip() != "RUN ONE":
                print("취소했습니다.")
                return 0
            robot.autonomous()
            flow.run_one(
                robot, args.class_name, snapshot, poses, args.hover_height_mm,
                args.vel, args.acc, args.close_position, args.current,
                rotate=args.rotate, reference_yaw=args.reference_yaw_deg,
            )
            flow.home(robot, poses, args.vel, args.acc)
            print("단일 집기·놓기 완료. HOME에서 정지했습니다.")
        return 0
    except KeyboardInterrupt:
        print("\n중단했습니다. 추가 이동 명령은 보내지 않습니다.")
        return 1
    except (FileNotFoundError, KeyError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
