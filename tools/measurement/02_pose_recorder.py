#!/usr/bin/env python3
"""Record the robot's current joint/task pose without commanding motion."""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "config" / "robot_measurements.yaml"
ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
REQUIRED_DOMAIN_ID = "15"
PICK_CLASSES = ["tomato", "cheese", "berry"]
BOX_SIZE_MM = 70


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="현재 로봇 자세를 이름과 함께 저장합니다. 로봇 이동 명령은 보내지 않습니다."
    )
    parser.add_argument(
        "--name",
        required=True,
        help=(
            "예: home, camera, safe_wait, pick_reference, bowl_approach, "
            "bowl_release, bowl_retreat, workspace_left_top"
        ),
    )
    parser.add_argument("--note", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--tcp-offset-mm-deg",
        type=float,
        nargs=6,
        metavar=("X", "Y", "Z", "RX", "RY", "RZ"),
        help="컨트롤러에 등록한 TCP offset [mm, degree]를 함께 저장",
    )
    return parser.parse_args()


def validate_name(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("name은 영문 소문자로 시작하고 소문자/숫자/_만 사용할 수 있습니다.")


def read_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ValueError(f"기존 파일의 YAML 최상위가 객체가 아닙니다: {path}")
    return document


def main() -> int:
    args = parse_args()
    try:
        validate_name(args.name)
        if os.environ.get("ROS_DOMAIN_ID") != REQUIRED_DOMAIN_ID:
            raise RuntimeError(
                f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID')!r}. "
                f"먼저 export ROS_DOMAIN_ID={REQUIRED_DOMAIN_ID} 를 실행하세요."
            )

        output = args.output.expanduser().resolve()
        document = read_existing(output)
        poses = document.setdefault("poses", {})
        if args.name in poses and not args.overwrite:
            raise ValueError(
                f"'{args.name}' 자세가 이미 있습니다. 확인 후 --overwrite를 사용하세요."
            )

        import rclpy
        import DR_init

        DR_init.__dsr__id = ROBOT_ID
        DR_init.__dsr__model = ROBOT_MODEL
        rclpy.init()
        node = rclpy.create_node("salad_pose_recorder", namespace=ROBOT_ID)
        DR_init.__dsr__node = node

        try:
            import DSR_ROBOT2 as dsr
            from DSR_ROBOT2 import get_current_posj, get_current_posx, get_robot_mode, get_tcp

            if not dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=10.0):
                raise RuntimeError("로봇 서비스를 찾지 못했습니다. bringup을 확인하세요.")

            posj = [round(float(v), 6) for v in get_current_posj()]
            posx_raw, solution = get_current_posx()
            posx = [round(float(v), 6) for v in posx_raw]
            tcp_name = str(get_tcp())
            robot_mode = int(get_robot_mode())

            print("\n저장할 이름:", args.name)
            print("현재 posj [degree]:", posj)
            print("현재 posx [mm, degree]:", posx)
            print("solution space:", solution)
            print("현재 TCP:", tcp_name)
            print("로봇 모드:", robot_mode)
            print("이 스크립트는 로봇을 움직이지 않습니다.")
            if input("현재 값이 맞으면 SAVE 입력: ").strip() != "SAVE":
                print("취소했습니다. 파일을 변경하지 않았습니다.")
                return 1

            document.setdefault(
                "project",
                {
                    "robot_id": ROBOT_ID,
                    "robot_model": ROBOT_MODEL,
                    "ros_domain_id": int(REQUIRED_DOMAIN_ID),
                    "pick_classes": PICK_CLASSES,
                    "box_size_mm": BOX_SIZE_MM,
                    "coordinate_units": "mm_degree",
                },
            )
            tcp = document.setdefault("tcp", {})
            tcp["active_name"] = tcp_name
            if args.tcp_offset_mm_deg is not None:
                tcp["offset_mm_deg"] = [float(v) for v in args.tcp_offset_mm_deg]
            else:
                tcp.setdefault("offset_mm_deg", None)

            poses[args.name] = {
                "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "posj_deg": posj,
                "posx_mm_deg": posx,
                "solution_space": int(solution),
                "robot_mode": robot_mode,
                "tcp": tcp_name,
                "note": args.note,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            print("저장 완료:", output)
            return 0
        finally:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
