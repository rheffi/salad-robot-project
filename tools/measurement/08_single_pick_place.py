#!/usr/bin/env python3
"""Pick one cached ingredient and place it at the cached bowl coordinate."""

from __future__ import annotations

import argparse
from pathlib import Path

from robot_common import (
    CLOSE_POSITION, DEFAULT_MEASUREMENTS, GRIPPER_CURRENT, OPEN_POSITION,
    Robot, approach_target, load_poses, move_safe, validate_settings,
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
        safe_z = float(poses["safe_wait"]["posx"][2])
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
            move_safe(robot, poses, args.vel, args.acc)
            robot.grip(OPEN_POSITION, GRIPPER_CURRENT, "열기")
            robot.wait(0.5)
            pick_safe, pick_hover, pick_action = approach_target(
                robot, *item_xy, pick_ref, safe_z, args.hover_height_mm,
                args.vel, args.acc, args.class_name,
            )
            robot.movel(pick_action, 5.0, 5.0, "집기 Z")
            robot.grip(args.close_position, args.current, "집기 닫기")
            robot.wait(1.0)
            robot.movel(pick_hover, 5.0, 5.0, "집은 후 상승")
            robot.movel(pick_safe, args.vel, args.acc, "집은 후 안전 높이")

            place_safe, place_hover, place_action = approach_target(
                robot, *bowl_xy, place_ref, safe_z, args.hover_height_mm,
                args.vel, args.acc, "bowl",
            )
            robot.movel(place_action, 5.0, 5.0, "놓기 Z")
            robot.grip(OPEN_POSITION, GRIPPER_CURRENT, "보울 놓기")
            robot.wait(0.5)
            robot.movel(place_hover, 5.0, 5.0, "놓은 후 상승")
            robot.movel(place_safe, args.vel, args.acc, "놓은 후 안전 높이")
            move_safe(robot, poses, args.vel, args.acc)
            robot.movej(poses["home"]["posj"], args.vel, args.acc, "HOME")
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
