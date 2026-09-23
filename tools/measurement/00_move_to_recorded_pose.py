#!/usr/bin/env python3
"""Move the E0509 to a recorded HOME or safe-wait joint pose.

The default mode is read-only: it connects to the robot and prints the current
and target poses. Actual motion requires both ``--live`` and an exact typed
confirmation. This tool does not perform collision-aware path planning.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEASUREMENTS = PROJECT_ROOT / "config" / "robot_measurements.yaml"
ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
REQUIRED_DOMAIN_ID = "15"
TARGETS = ("home", "safe_wait")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "기록된 HOME 또는 safe_wait 관절 자세로 이동합니다. "
            "기본값은 현재/목표 자세만 출력하는 DRY RUN입니다."
        )
    )
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--measurements", type=Path, default=DEFAULT_MEASUREMENTS)
    parser.add_argument("--vel", type=float, default=10.0)
    parser.add_argument("--acc", type=float, default=10.0)
    parser.add_argument(
        "--live",
        action="store_true",
        help="실제 로봇을 움직입니다. 생략하면 현재/목표 자세만 출력합니다.",
    )
    return parser.parse_args()


def load_target(path: Path, target_name: str) -> tuple[list[float], list[float], str]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"측정 파일이 없습니다: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"YAML 최상위 형식이 잘못됐습니다: {path}")

    entry = document.get("poses", {}).get(target_name)
    if not isinstance(entry, dict):
        raise ValueError(
            f"{target_name} 자세가 없습니다. "
            f"02_pose_recorder.py --name {target_name}로 먼저 기록하세요."
        )
    joints = [float(value) for value in entry.get("posj_deg", [])]
    task_pose = [float(value) for value in entry.get("posx_mm_deg", [])]
    if len(joints) != 6 or len(task_pose) != 6:
        raise ValueError(f"{target_name}의 posj/posx 형식이 잘못됐습니다.")
    return joints, task_pose, str(entry.get("tcp", ""))


def validate_args(args: argparse.Namespace) -> None:
    if os.environ.get("ROS_DOMAIN_ID") != REQUIRED_DOMAIN_ID:
        raise RuntimeError(
            f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID')!r}. "
            f"export ROS_DOMAIN_ID={REQUIRED_DOMAIN_ID} 를 실행하세요."
        )
    if not 1.0 <= args.vel <= 20.0 or not 1.0 <= args.acc <= 20.0:
        raise ValueError("vel/acc는 안전을 위해 1~20 범위만 허용합니다.")


def run(args: argparse.Namespace) -> int:
    validate_args(args)
    target_joints, target_pose, expected_tcp = load_target(
        args.measurements, args.target
    )

    import rclpy
    import DR_init

    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL
    if not rclpy.ok():
        rclpy.init()
    node = rclpy.create_node("salad_move_to_recorded_pose", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    try:
        import DSR_ROBOT2 as dsr
        from DSR_ROBOT2 import (
            ROBOT_MODE_AUTONOMOUS,
            get_current_posj,
            get_current_posx,
            get_robot_mode,
            get_tcp,
            movej,
            posj,
            set_robot_mode,
        )

        if not dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=10.0):
            raise RuntimeError(
                "로봇 서비스를 찾지 못했습니다. bringup과 ROS_DOMAIN_ID를 확인하세요."
            )

        current_joints = [float(value) for value in get_current_posj()]
        current_pose_raw, _ = get_current_posx()
        current_pose = [float(value) for value in current_pose_raw]
        actual_tcp = str(get_tcp())

        print("\n[현재 상태]")
        print("robot mode:", get_robot_mode())
        print("TCP:", repr(actual_tcp))
        print("posj:", [round(value, 2) for value in current_joints])
        print("posx:", [round(value, 2) for value in current_pose])
        print(f"\n[목표: {args.target}]")
        print("TCP:", repr(expected_tcp))
        print("posj:", [round(value, 2) for value in target_joints])
        print("posx:", [round(value, 2) for value in target_pose])
        print(f"vel/acc: {args.vel:g}/{args.acc:g}")

        if actual_tcp != expected_tcp:
            raise RuntimeError(
                f"TCP 불일치: 현재={actual_tcp!r}, 기록={expected_tcp!r}. "
                "TCP를 임의로 바꾸지 말고 기록 상태를 확인하세요."
            )

        if not args.live:
            print("\nDRY RUN 완료. 로봇은 움직이지 않았습니다.")
            return 0

        expected_text = f"MOVE {args.target.upper()}"
        print(
            "\n주의: 이 도구는 충돌 회피 경로를 계산하지 않습니다. "
            "현재 자세에서 목표까지의 관절 이동 경로를 사람이 확인해야 합니다."
        )
        confirmation = input(
            f"주변·경로·비상정지를 확인한 뒤 {expected_text} 입력: "
        ).strip()
        if confirmation != expected_text:
            print("취소했습니다. 로봇은 움직이지 않았습니다.")
            return 0

        if set_robot_mode(ROBOT_MODE_AUTONOMOUS) != 0:
            raise RuntimeError("AUTONOMOUS 모드 전환 실패")
        if movej(posj(target_joints), vel=args.vel, acc=args.acc) != 0:
            raise RuntimeError(f"{args.target} 이동 실패")

        completed_joints = [float(value) for value in get_current_posj()]
        completed_pose_raw, _ = get_current_posx()
        completed_pose = [float(value) for value in completed_pose_raw]
        print(f"\n{args.target} 이동 완료")
        print("posj:", [round(value, 2) for value in completed_joints])
        print("posx:", [round(value, 2) for value in completed_pose])
        return 0
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main() -> int:
    try:
        return run(parse_args())
    except KeyboardInterrupt:
        print("\n사용자가 중단했습니다. 추가 이동 명령은 보내지 않습니다.")
        return 1
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
