#!/usr/bin/env python3
"""Shared recorded-pose loading and blocking Doosan motion helpers."""

from __future__ import annotations

import os
import math
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEASUREMENTS = PROJECT_ROOT / "config" / "robot_measurements.yaml"
ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
REQUIRED_DOMAIN_ID = "15"
OPEN_POSITION = 750
CLOSE_POSITION = 430
GRIPPER_CURRENT = 200


def load_poses(path: Path, names: tuple[str, ...]) -> tuple[dict[str, dict[str, Any]], str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"측정 파일이 없습니다: {resolved}")
    document = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("robot_measurements.yaml 형식이 잘못됐습니다.")
    source = document.get("poses", {})
    poses, expected_tcp = {}, None
    for name in names:
        entry = source.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"기록 자세가 없습니다: {name}")
        joints = [float(value) for value in entry.get("posj_deg", [])]
        task = [float(value) for value in entry.get("posx_mm_deg", [])]
        if len(joints) != 6 or len(task) != 6:
            raise ValueError(f"{name}의 posj/posx 형식이 잘못됐습니다.")
        if not all(math.isfinite(value) for value in joints + task):
            raise ValueError(f"{name}의 posj/posx에 NaN/무한대가 있습니다.")
        tcp = str(entry.get("tcp", ""))
        if expected_tcp is None:
            expected_tcp = tcp
        elif tcp != expected_tcp:
            raise ValueError(f"기록 자세의 TCP가 일치하지 않습니다: {name}={tcp!r}")
        poses[name] = {"posj": joints, "posx": task, "tcp": tcp}
    return poses, expected_tcp or ""


def validate_settings(poses: dict[str, dict[str, Any]], hover: float, vel: float, acc: float) -> None:
    if not 50.0 <= hover <= 150.0:
        raise ValueError("hover-height-mm은 50~150mm 범위만 허용합니다.")
    if not 1.0 <= vel <= 20.0 or not 1.0 <= acc <= 20.0:
        raise ValueError("vel/acc는 1~20 범위만 허용합니다.")
    safe_z = float(poses["safe_wait"]["posx"][2])
    for name in ("pick_reference", "place_reference"):
        if name in poses and safe_z <= float(poses[name]["posx"][2]) + hover:
            raise ValueError(f"safe_wait Z가 {name} Hover Z보다 높아야 합니다.")


class Robot:
    def __init__(self, expected_tcp: str, gripper: bool, *, web_worker: bool = False) -> None:
        self.expected_tcp = expected_tcp
        self.use_gripper = gripper
        self.node = None
        self.rclpy = None
        self.api: dict[str, Any] = {}
        self.gripper_cmd = None
        self.web_worker = web_worker

    def __enter__(self) -> "Robot":
        if os.environ.get("ROS_DOMAIN_ID") != REQUIRED_DOMAIN_ID:
            raise RuntimeError(f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID')!r}. export ROS_DOMAIN_ID=15를 실행하세요.")
        import rclpy
        import DR_init

        self.rclpy = rclpy
        # DR_init uses double-underscore module attributes.  Direct access from
        # this class body would be name-mangled to _Robot__dsr__*, so assign
        # the exact attribute names explicitly.
        setattr(DR_init, "__dsr__id", ROBOT_ID)
        setattr(DR_init, "__dsr__model", ROBOT_MODEL)
        if not rclpy.ok():
            if self.web_worker:
                from rclpy.signals import SignalHandlerOptions
                # Uvicorn owns SIGINT/SIGTERM; do not replace its handlers.
                rclpy.init(args=[], signal_handler_options=SignalHandlerOptions.NO)
            else:
                rclpy.init()
        self.node = rclpy.create_node("salad_workflow", namespace=ROBOT_ID)
        setattr(DR_init, "__dsr__node", self.node)
        import DSR_ROBOT2 as dsr
        from DSR_ROBOT2 import (
            DR_BASE, DR_MV_MOD_ABS, ROBOT_MODE_AUTONOMOUS,
            get_current_posj, get_current_posx, get_tcp,
            movej, movel, posj, posx, set_robot_mode, wait,
        )

        self.api = dict(
            DR_BASE=DR_BASE, DR_MV_MOD_ABS=DR_MV_MOD_ABS,
            ROBOT_MODE_AUTONOMOUS=ROBOT_MODE_AUTONOMOUS,
            get_current_posj=get_current_posj, get_current_posx=get_current_posx,
            get_tcp=get_tcp, movej=movej, movel=movel, posj=posj, posx=posx,
            set_robot_mode=set_robot_mode, wait=wait,
        )
        if not dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=10.0):
            raise RuntimeError("로봇 서비스를 찾지 못했습니다.")
        actual_tcp = str(get_tcp())
        if actual_tcp != self.expected_tcp:
            raise RuntimeError(f"TCP 불일치: 현재={actual_tcp!r}, 기록={self.expected_tcp!r}")
        if self.use_gripper:
            from dsr_gripper import gripper_cmd
            self.gripper_cmd = gripper_cmd
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.node is not None:
            self.node.destroy_node()
        if self.rclpy is not None and self.rclpy.ok():
            if self.web_worker:
                self.rclpy.shutdown(uninstall_handlers=False)
            else:
                self.rclpy.shutdown()

    def state(self) -> tuple[list[float], list[float]]:
        joints = [float(value) for value in self.api["get_current_posj"]()]
        task, _ = self.api["get_current_posx"]()
        return joints, [float(value) for value in task]

    def print_route_start(self, safe_joints: list[float]) -> None:
        joints, task = self.state()
        print("현재 posj:", [round(value, 1) for value in joints])
        print("현재 posx:", [round(value, 1) for value in task])
        print("목표 safe_wait posj:", [round(value, 1) for value in safe_joints])
        print("주의: 현재→safe_wait movej 경로는 충돌 회피를 계산하지 않습니다.")

    def autonomous(self) -> None:
        if self.api["set_robot_mode"](self.api["ROBOT_MODE_AUTONOMOUS"]) != 0:
            raise RuntimeError("AUTONOMOUS 모드 전환 실패")

    def movej(self, joints: list[float], vel: float, acc: float, label: str) -> None:
        if self.api["movej"](self.api["posj"](joints), vel=vel, acc=acc) != 0:
            raise RuntimeError(f"{label} movej 실패")

    def movel(self, pose: list[float], vel: float, acc: float, label: str) -> None:
        result = self.api["movel"](
            self.api["posx"](*pose), vel=vel, acc=acc,
            ref=self.api["DR_BASE"], mod=self.api["DR_MV_MOD_ABS"],
        )
        if result != 0:
            raise RuntimeError(f"{label} movel 실패")

    def grip(self, position: int, current: int, label: str) -> None:
        if self.gripper_cmd is None or not self.gripper_cmd(position, current=current):
            raise RuntimeError(f"그리퍼 명령 실패: {label}")

    def wait(self, seconds: float) -> None:
        self.api["wait"](seconds)


def move_safe(robot: Robot, poses: dict[str, dict[str, Any]], vel: float, acc: float) -> None:
    robot.movej(poses["safe_wait"]["posj"], vel, acc, "safe_wait")


def target_poses(
    x: float, y: float, reference: list[float], safe_z: float, hover: float
) -> tuple[list[float], list[float], list[float]]:
    orientation = [float(value) for value in reference[3:6]]
    action_z = float(reference[2])
    return (
        [x, y, safe_z, *orientation],
        [x, y, action_z + hover, *orientation],
        [x, y, action_z, *orientation],
    )


def approach_target(
    robot: Robot, x: float, y: float, reference: list[float], safe_z: float,
    hover: float, vel: float, acc: float, label: str, *, separate_rotation: bool = False,
) -> tuple[list[float], list[float], list[float]]:
    safe_pose, hover_pose, action_pose = target_poses(x, y, reference, safe_z, hover)
    if separate_rotation:
        _, current = robot.state()
        if not all(math.isfinite(v) for v in current) or abs(current[2] - safe_z) > 5:
            raise ValueError("회전 전에 로봇이 기록된 safe_wait 높이에 있어야 합니다.")
        # Base-Z rotation of ZYZ: Rz(delta) Rz(A) Ry(B) Rz(C).
        # Change orientation in place before translating towards the target.
        robot.movel([*current[:3], *reference[3:]], vel, acc, f"{label} 안전 높이 제자리 방향 정렬")
    robot.movel(safe_pose, vel, acc, f"{label} 안전 높이")
    robot.movel(hover_pose, vel, acc, f"{label} Hover")
    return safe_pose, hover_pose, action_pose


def add_rotation_arguments(parser):
    parser.add_argument("--rotate", action="store_true", help="검출한 박스 각도를 집기 자세에 적용")
    parser.add_argument("--reference-yaw-deg", type=float,
                        help="pick_reference에서 잘 집혔던 정방향 박스의 base yaw (05 --angles로 확인)")


def validate_rotation_options(rotate, reference_yaw):
    if rotate and (reference_yaw is None or not math.isfinite(reference_yaw)):
        raise ValueError("--rotate에는 실측한 --reference-yaw-deg 값이 필요합니다.")


def pick_reference_for_item(reference, item, *, rotate=False, reference_yaw=None):
    result = [float(v) for v in reference]
    if not rotate:
        return result
    from box_orientation import METHOD, square_delta
    validate_rotation_options(rotate, reference_yaw)
    o = item.get("orientation", {})
    values = [float(o.get(key, float('nan'))) for key in
              ("yaw_base_deg", "quality", "spread_deg", "stable_frames")]
    if (o.get("method") != METHOD or not all(math.isfinite(v) for v in values)
            or not -.001 <= values[2] <= 5 or not .68 <= values[1] <= 1.01
            or values[3] < 3 or not -45 <= values[0] < 45):
        raise ValueError("검증된 박스 각도가 없습니다. 05 --angles로 다시 촬영하세요.")
    if len(result) != 6 or not all(math.isfinite(v) for v in result):
        raise ValueError("집기 자세가 유효하지 않습니다.")
    delta = square_delta(values[0], reference_yaw)
    result[3] = (result[3] + delta + 180) % 360 - 180
    print(f"박스 yaw={values[0]:+.2f}, 기준={reference_yaw:+.2f}, base-Z 회전={delta:+.2f}deg")
    return result
