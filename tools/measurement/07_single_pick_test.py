#!/usr/bin/env python3
"""Pick one cached ingredient, hold for inspection, then return it."""

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
    parser = argparse.ArgumentParser(description="재료 하나를 집어 올린 뒤 원래 위치에 반환합니다.")
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
        poses, tcp = load_poses(args.measurements, ("safe_wait", "pick_reference"))
        validate_settings(poses, args.hover_height_mm, args.vel, args.acc)
        item = snapshot["detections"][args.class_name]
        x, y = float(item["robot_x_mm"]), float(item["robot_y_mm"])
        reference = poses["pick_reference"]["posx"]
        safe_z = float(poses["safe_wait"]["posx"][2])
        print("\n[단일 집기 계획]")
        print(f"class={args.class_name}, XY=({x:.1f}, {y:.1f})mm, pick Z={reference[2]:.1f}mm")
        print(f"gripper close={args.close_position}, current={args.current}, open={OPEN_POSITION}")
        print("이동: safe_wait → Hover → 집기 → 상승 → 확인 → 원위치 반환 → safe_wait")
        if not args.live:
            print("DRY RUN 완료. 로봇과 그리퍼는 움직이지 않았습니다.")
            return 0

        with Robot(tcp, gripper=True) as robot:
            robot.print_route_start(poses["safe_wait"]["posj"])
            expected = f"PICK {args.class_name.upper()}"
            if input(f"경로·주변·비상정지를 확인한 뒤 {expected} 입력: ").strip() != expected:
                print("취소했습니다.")
                return 0
            robot.autonomous()
            move_safe(robot, poses, args.vel, args.acc)
            robot.grip(OPEN_POSITION, GRIPPER_CURRENT, "열기")
            robot.wait(0.5)
            safe_pose, hover_pose, pick_pose = approach_target(
                robot, x, y, reference, safe_z, args.hover_height_mm,
                args.vel, args.acc, args.class_name,
            )
            robot.movel(pick_pose, 5.0, 5.0, "집기 Z 하강")
            robot.grip(args.close_position, args.current, "닫기")
            robot.wait(1.0)
            robot.movel(hover_pose, 5.0, 5.0, "집은 후 상승")
            robot.movel(safe_pose, args.vel, args.acc, "집은 후 안전 높이")
            print("집기 완료. 박스의 미끄러짐과 찌그러짐을 확인하세요.")
            if input("원래 위치에 반환하려면 RETURN 입력: ").strip() != "RETURN":
                print("반환하지 않았습니다. 로봇은 박스를 든 안전 높이에 있습니다.")
                return 0
            robot.movel(hover_pose, args.vel, args.acc, "반환 Hover")
            robot.movel(pick_pose, 5.0, 5.0, "반환 Z 하강")
            robot.grip(OPEN_POSITION, GRIPPER_CURRENT, "반환 열기")
            robot.wait(0.5)
            robot.movel(hover_pose, 5.0, 5.0, "반환 후 상승")
            robot.movel(safe_pose, args.vel, args.acc, "반환 후 안전 높이")
            move_safe(robot, poses, args.vel, args.acc)
            print("단일 집기·반환 시험 완료. safe_wait에서 정지했습니다.")
        return 0
    except KeyboardInterrupt:
        print("\n중단했습니다. 추가 이동 명령은 보내지 않습니다.")
        return 1
    except (FileNotFoundError, KeyError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
