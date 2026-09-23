#!/usr/bin/env python3
"""Capture the initial scene once, then place three ingredients into the bowl."""

from __future__ import annotations

import argparse
from pathlib import Path

from robot_common import (
    CLOSE_POSITION, DEFAULT_MEASUREMENTS, GRIPPER_CURRENT, OPEN_POSITION,
    Robot, approach_target, load_poses, move_safe, validate_settings,
)
from scene_common import (
    DEFAULT_CORRECTION, DEFAULT_MODEL, DEFAULT_SNAPSHOT, DEFAULT_SNAPSHOT_IMAGE,
    PICK_CLASSES, capture_scene, load_json, print_snapshot, save_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="장면을 한 번 저장한 뒤 세 재료를 보울에 순서대로 넣습니다.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--correction", type=Path, default=DEFAULT_CORRECTION)
    parser.add_argument("--measurements", type=Path, default=DEFAULT_MEASUREMENTS)
    parser.add_argument("--camera", default="auto")
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--stable-frames", type=int, default=10)
    parser.add_argument("--snapshot-output", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--image-output", type=Path, default=DEFAULT_SNAPSHOT_IMAGE)
    parser.add_argument("--hover-height-mm", type=float, default=100.0)
    parser.add_argument("--vel", type=float, default=10.0)
    parser.add_argument("--acc", type=float, default=10.0)
    parser.add_argument("--close-position", type=int, default=CLOSE_POSITION)
    parser.add_argument("--current", type=int, default=GRIPPER_CURRENT)
    parser.add_argument("--live", action="store_true")
    return parser.parse_args()


def run_one(
    robot: Robot, name: str, snapshot: dict, poses: dict,
    hover: float, vel: float, acc: float, close_position: int, current: int,
) -> None:
    item, bowl = snapshot["detections"][name], snapshot["detections"]["bowl"]
    item_xy = float(item["robot_x_mm"]), float(item["robot_y_mm"])
    bowl_xy = float(bowl["robot_x_mm"]), float(bowl["robot_y_mm"])
    pick_ref, place_ref = poses["pick_reference"]["posx"], poses["place_reference"]["posx"]
    safe_z = float(poses["safe_wait"]["posx"][2])
    move_safe(robot, poses, vel, acc)
    robot.grip(OPEN_POSITION, GRIPPER_CURRENT, f"{name} 집기 전 열기")
    robot.wait(0.5)
    pick_safe, pick_hover, pick_action = approach_target(
        robot, *item_xy, pick_ref, safe_z, hover, vel, acc, name
    )
    robot.movel(pick_action, 5.0, 5.0, f"{name} 집기 Z")
    robot.grip(close_position, current, f"{name} 닫기")
    robot.wait(1.0)
    robot.movel(pick_hover, 5.0, 5.0, f"{name} 상승")
    robot.movel(pick_safe, vel, acc, f"{name} 안전 높이")
    place_safe, place_hover, place_action = approach_target(
        robot, *bowl_xy, place_ref, safe_z, hover, vel, acc, "bowl"
    )
    robot.movel(place_action, 5.0, 5.0, f"{name} 놓기 Z")
    robot.grip(OPEN_POSITION, GRIPPER_CURRENT, f"{name} 놓기")
    robot.wait(0.5)
    robot.movel(place_hover, 5.0, 5.0, f"{name} 놓은 후 상승")
    robot.movel(place_safe, vel, acc, f"{name} 놓은 후 안전 높이")
    print(f"{name} 투입 완료")


def main() -> int:
    args = parse_args()
    try:
        if not 0 <= args.close_position < OPEN_POSITION or not 1 <= args.current <= 400:
            raise ValueError("close-position은 0~749, current는 1~400이어야 합니다.")
        correction = load_json(args.correction)
        names = ("home", "safe_wait", "pick_reference", "place_reference")
        poses, tcp = load_poses(args.measurements, names)
        validate_settings(poses, args.hover_height_mm, args.vel, args.acc)

        if not args.live:
            print("DRY RUN: 로봇이 카메라를 가리지 않는 상태에서 장면만 촬영합니다.")
            snapshot, image = capture_scene(
                args.model, correction, args.camera, args.conf, args.stable_frames
            )
            print_snapshot(snapshot)
            save_snapshot(snapshot, image, args.snapshot_output, args.image_output)
            print("실행 계획: tomato → cheese → berry → HOME")
            print("로봇과 그리퍼는 움직이지 않았습니다.")
            return 0

        with Robot(tcp, gripper=True) as robot:
            robot.print_route_start(poses["safe_wait"]["posj"])
            if input("장면 촬영 자세로 이동하려면 PREPARE SCENE 입력: ").strip() != "PREPARE SCENE":
                print("취소했습니다.")
                return 0
            robot.autonomous()
            move_safe(robot, poses, args.vel, args.acc)
            robot.movej(poses["home"]["posj"], args.vel, args.acc, "HOME 촬영 자세")
            snapshot, image = capture_scene(
                args.model, correction, args.camera, args.conf, args.stable_frames
            )
            print_snapshot(snapshot)
            save_snapshot(snapshot, image, args.snapshot_output, args.image_output)
            print("순서: tomato → cheese → berry. 장면 좌표는 다시 인식하지 않습니다.")
            if input("전체 경로·주변·비상정지를 확인한 뒤 RUN SALAD 입력: ").strip() != "RUN SALAD":
                print("작업을 시작하지 않았습니다. HOME에서 정지했습니다.")
                return 0
            for name in PICK_CLASSES:
                run_one(
                    robot, name, snapshot, poses, args.hover_height_mm,
                    args.vel, args.acc, args.close_position, args.current,
                )
            move_safe(robot, poses, args.vel, args.acc)
            robot.movej(poses["home"]["posj"], args.vel, args.acc, "최종 HOME")
            print("세 재료 투입 완료. HOME에서 종료했습니다.")
        return 0
    except KeyboardInterrupt:
        print("\n중단했습니다. 추가 이동 명령은 보내지 않습니다.")
        return 1
    except (FileNotFoundError, KeyError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
