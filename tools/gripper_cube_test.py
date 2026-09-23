#!/usr/bin/env python3
"""Doosan E0509 + dsr_gripper cube grasp parameter test.

The current robot pose is treated as the taught grasp pose.  The tool only
moves along base-frame Z so that position/current values can be tested without
mixing in XY or orientation errors.

Nothing moves unless ``--live`` is supplied.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
REQUIRED_DOMAIN_ID = "15"
OPEN_CURRENT = 200


@dataclass(frozen=True)
class TestSettings:
    size_mm: int
    height_mm: int
    open_position: int
    lift_mm: float
    velocity: float
    acceleration: float
    close_wait_s: float
    hold_s: float
    output: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "현재 로봇 자세를 집기점으로 기록하고, 수직 하강/집기/상승/"
            "원위치/놓기를 한 번씩 시험합니다."
        )
    )
    parser.add_argument("--size-mm", type=int, choices=(40, 50, 60, 70), required=True)
    parser.add_argument("--height-mm", type=int, default=30)
    parser.add_argument("--open-position", type=int, default=750)
    parser.add_argument("--lift-mm", type=float, default=80.0)
    parser.add_argument("--vel", type=float, default=10.0)
    parser.add_argument("--acc", type=float, default=10.0)
    parser.add_argument("--close-wait", type=float, default=1.0)
    parser.add_argument("--hold", type=float, default=2.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/gripper_trials.csv"),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="실제 로봇을 움직입니다. 생략하면 계획만 출력합니다.",
    )
    return parser.parse_args()


def validate_settings(args: argparse.Namespace) -> TestSettings:
    if not 0 <= args.open_position <= 750:
        raise ValueError("open-position은 0~750이어야 합니다.")
    if not 20 <= args.lift_mm <= 150:
        raise ValueError("lift-mm은 안전을 위해 20~150 mm 범위만 허용합니다.")
    if not 1 <= args.vel <= 20 or not 1 <= args.acc <= 20:
        raise ValueError("vel/acc는 안전을 위해 1~20 범위만 허용합니다.")
    if not 0.2 <= args.close_wait <= 10:
        raise ValueError("close-wait은 0.2~10초 범위여야 합니다.")
    if not 0 <= args.hold <= 30:
        raise ValueError("hold는 0~30초 범위여야 합니다.")
    return TestSettings(
        size_mm=args.size_mm,
        height_mm=args.height_mm,
        open_position=args.open_position,
        lift_mm=args.lift_mm,
        velocity=args.vel,
        acceleration=args.acc,
        close_wait_s=args.close_wait,
        hold_s=args.hold,
        output=args.output,
    )


def print_plan(settings: TestSettings) -> None:
    print("\n[고정 동작 순서]")
    print("  1. 시작 시 현재 자세를 집기점으로 기록")
    print(f"  2. 그리퍼 열기({settings.open_position}) 후 Z +{settings.lift_mm:g} mm")
    print("  3. 시험마다 Z 수직 하강 → 지정 position/current로 닫기")
    print(f"  4. Z +{settings.lift_mm:g} mm 상승 후 {settings.hold_s:g}초 관찰")
    print("  5. 같은 집기점으로 수직 하강 → 열기 → 수직 후퇴")
    print(f"  6. 결과를 {settings.output}에 누적 저장")
    print("\nXY 이동, 자세 회전, HOME 이동은 하지 않습니다.")


def prompt_int(label: str, minimum: int, maximum: int) -> int | None:
    while True:
        raw = input(f"{label} ({minimum}~{maximum}, 종료 q): ").strip().lower()
        if raw == "q":
            return None
        try:
            value = int(raw)
        except ValueError:
            print("정수를 입력하세요.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"{minimum}~{maximum} 범위로 입력하세요.")


def append_result(path: Path, row: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    print(f"기록 저장: {path}")


def require_environment() -> None:
    actual = os.environ.get("ROS_DOMAIN_ID")
    if actual != REQUIRED_DOMAIN_ID:
        raise RuntimeError(
            f"ROS_DOMAIN_ID가 {actual!r}입니다. "
            f"먼저 'export ROS_DOMAIN_ID={REQUIRED_DOMAIN_ID}'를 실행하세요."
        )


def run_live(settings: TestSettings) -> None:
    require_environment()

    import rclpy
    import DR_init

    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL

    rclpy.init()
    node = rclpy.create_node("gripper_cube_test", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    # DR_init에 노드를 등록한 뒤에 import해야 올바른 namespace의 서비스를 사용한다.
    import DSR_ROBOT2 as dsr
    from DSR_ROBOT2 import (
        DR_BASE,
        DR_MV_MOD_REL,
        ROBOT_MODE_AUTONOMOUS,
        get_current_posx,
        get_robot_mode,
        get_tcp,
        movel,
        posx,
        set_robot_mode,
        wait,
    )
    from dsr_gripper import gripper_cmd

    def move_z(delta_mm: float) -> None:
        result = movel(
            posx(0, 0, delta_mm, 0, 0, 0),
            vel=settings.velocity,
            acc=settings.acceleration,
            ref=DR_BASE,
            mod=DR_MV_MOD_REL,
        )
        if result != 0:
            raise RuntimeError(f"Z {delta_mm:g} mm 이동 명령이 실패했습니다: {result}")

    try:
        if not dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=10.0):
            raise RuntimeError(
                "로봇 서비스를 찾지 못했습니다. bringup, 네트워크, "
                "ROS_DOMAIN_ID=15를 확인하세요."
            )

        # 사용자가 수동으로 맞춘 현재 위치를 변경 전에 먼저 기록한다.
        pick_pose, solution = get_current_posx()
        tcp_name = get_tcp()
        print("\n[연결 확인]")
        print("현재 로봇 모드:", get_robot_mode())
        print("활성 TCP:", tcp_name)
        print("기록할 집기 자세:", list(pick_pose), "solution:", solution)
        print("\n주의: 비상정지 버튼을 잡고 작업영역에서 사람과 장애물을 치우세요.")
        armed = input("위 자세가 정확한 집기점이면 RUN을 입력: ").strip()
        if armed != "RUN":
            print("취소했습니다. 로봇은 움직이지 않았습니다.")
            return

        if set_robot_mode(ROBOT_MODE_AUTONOMOUS) != 0:
            raise RuntimeError("로봇을 AUTONOMOUS 모드로 전환하지 못했습니다.")

        # 집기점에서 열린 뒤 위로 빠져, 이후 모든 시험을 안전 접근점에서 시작한다.
        if not gripper_cmd(settings.open_position, current=OPEN_CURRENT):
            raise RuntimeError("그리퍼 열기 명령이 실패했습니다.")
        wait(0.5)
        move_z(settings.lift_mm)
        print("안전 접근점으로 상승했습니다.")

        trial_no = 0
        while True:
            print("\n--- 새 시험 ---")
            close_position = prompt_int("닫힘 position", 0, 749)
            if close_position is None:
                break
            current = prompt_int("닫힘 current", 1, 400)
            if current is None:
                break

            print(
                f"예정값: {settings.size_mm} mm 박스 / "
                f"position={close_position} / current={current}"
            )
            confirm = input(
                "박스를 원래 집기점에 놓고 손을 뺀 뒤 RUN 입력: "
            ).strip()
            if confirm != "RUN":
                print("이번 시험을 건너뜁니다.")
                continue

            trial_no += 1
            command_ok = True
            started_at = datetime.now().astimezone().isoformat(timespec="seconds")

            # 접근점 -> 집기점 -> 집기 -> 접근점
            move_z(-settings.lift_mm)
            command_ok = bool(gripper_cmd(close_position, current=current))
            wait(settings.close_wait_s)
            move_z(settings.lift_mm)
            wait(settings.hold_s)

            input("집기 상태를 확인했습니다. 내려놓으려면 Enter: ")

            # 접근점 -> 원래 집기점 -> 놓기 -> 접근점
            move_z(-settings.lift_mm)
            open_ok = bool(
                gripper_cmd(settings.open_position, current=OPEN_CURRENT)
            )
            command_ok = command_ok and open_ok
            wait(0.5)
            move_z(settings.lift_mm)

            result = input("결과 (성공 y / 실패 n / 애매 u): ").strip().lower()
            while result not in {"y", "n", "u"}:
                result = input("y, n, u 중 하나 입력: ").strip().lower()
            note = input("메모(미끄러짐, 찌그러짐 등, 없으면 Enter): ").strip()
            end_pose, _ = get_current_posx()

            append_result(
                settings.output,
                {
                    "timestamp": started_at,
                    "trial": trial_no,
                    "size_mm": settings.size_mm,
                    "height_mm": settings.height_mm,
                    "open_position": settings.open_position,
                    "close_position": close_position,
                    "current": current,
                    "lift_mm": settings.lift_mm,
                    "velocity": settings.velocity,
                    "acceleration": settings.acceleration,
                    "close_wait_s": settings.close_wait_s,
                    "hold_s": settings.hold_s,
                    "tcp": tcp_name,
                    "pick_pose": json.dumps(list(pick_pose), ensure_ascii=False),
                    "end_pose": json.dumps(list(end_pose), ensure_ascii=False),
                    "command_ok": command_ok,
                    "result": {"y": "success", "n": "fail", "u": "uncertain"}[result],
                    "note": note,
                },
            )

        print("시험을 종료합니다. 로봇은 집기점 위 안전 접근점에 있습니다.")
    except KeyboardInterrupt:
        print("\n사용자가 중단했습니다. 안전을 위해 추가 이동 명령은 보내지 않습니다.")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main() -> int:
    try:
        args = parse_args()
        settings = validate_settings(args)
        print_plan(settings)
        if not args.live:
            print("\nDRY RUN입니다. 실제 시험 때만 마지막에 --live를 붙이세요.")
            return 0
        run_live(settings)
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
