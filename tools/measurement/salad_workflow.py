"""Shared, non-interactive motion sequences for CLI and the web worker."""
import math

from robot_common import (OPEN_POSITION, GRIPPER_CURRENT, approach_target,
                          move_safe, pick_reference_for_item)

PLACE_Z_OFFSETS_MM = (0.0, 40.0, 80.0)


def validate_place_offsets(poses, hover, offsets=PLACE_Z_OFFSETS_MM):
    values = [float(value) for value in offsets]
    if not values or not all(math.isfinite(value) and 0 <= value <= 100 for value in values):
        raise ValueError('놓기 Z 오프셋은 0~100mm의 유한한 값이어야 합니다.')
    safe_z = float(poses['safe_wait']['posx'][2])
    place_z = float(poses['place_reference']['posx'][2])
    required_z = place_z + max(values) + float(hover)
    if safe_z <= required_z:
        raise ValueError(
            f'safe_wait Z={safe_z:.1f}가 최고 놓기 Hover Z={required_z:.1f}보다 높아야 합니다.'
        )


def pick(robot, name, snapshot, poses, hover, vel, acc, close_position, current,
         *, rotate=False, reference_yaw=None, hover_only=False, wait_s=2.0):
    item = snapshot['detections'][name]
    ref = pick_reference_for_item(poses['pick_reference']['posx'], item,
                                 rotate=rotate, reference_yaw=reference_yaw)
    move_safe(robot, poses, vel, acc)
    if not hover_only:
        robot.grip(OPEN_POSITION, GRIPPER_CURRENT, f'{name} 집기 전 열기')
        robot.wait(wait_s)
    points = approach_target(robot, float(item['robot_x_mm']), float(item['robot_y_mm']),
                             ref, float(poses['safe_wait']['posx'][2]), hover, vel, acc,
                             name, separate_rotation=rotate)
    if not hover_only:
        safe, above, action = points
        robot.movel(action, 5.0, 5.0, f'{name} 집기 Z')
        robot.grip(close_position, current, f'{name} 닫기')
        robot.wait(wait_s)
        robot.movel(above, 5.0, 5.0, f'{name} 상승')
        robot.movel(safe, vel, acc, f'{name} 안전 높이')
    return points


def return_pick(robot, points, poses, vel, acc):
    safe, above, action = points
    robot.movel(above, vel, acc, '반환 Hover')
    robot.movel(action, 5.0, 5.0, '반환 집기 Z')
    robot.grip(OPEN_POSITION, GRIPPER_CURRENT, '반환 열기')
    robot.wait(2.0)
    robot.movel(above, 5.0, 5.0, '반환 상승')
    robot.movel(safe, vel, acc, '반환 안전 높이')
    move_safe(robot, poses, vel, acc)


def bowl_hover(robot, snapshot, poses, hover, vel, acc, *, rotate=False,
               place_z_offset_mm=0.0):
    bowl = snapshot['detections']['bowl']
    reference = list(poses['place_reference']['posx'])
    offset = float(place_z_offset_mm)
    if not math.isfinite(offset) or not 0 <= offset <= 100:
        raise ValueError('놓기 Z 오프셋은 0~100mm 범위여야 합니다.')
    reference[2] += offset
    return approach_target(robot, float(bowl['robot_x_mm']), float(bowl['robot_y_mm']),
                           reference, float(poses['safe_wait']['posx'][2]), hover, vel, acc,
                           f'bowl(+{offset:.0f}mm)', separate_rotation=rotate)


def place(robot, snapshot, poses, hover, vel, acc, *, rotate=False,
          place_z_offset_mm=0.0):
    safe, above, action = bowl_hover(
        robot, snapshot, poses, hover, vel, acc, rotate=rotate,
        place_z_offset_mm=place_z_offset_mm,
    )
    robot.movel(action, 5.0, 5.0, f'보울 놓기 Z +{place_z_offset_mm:.0f}mm')
    robot.grip(OPEN_POSITION, GRIPPER_CURRENT, '보울 열기')
    robot.wait(2.0)
    robot.movel(above, 5.0, 5.0, '보울 후퇴')
    robot.movel(safe, vel, acc, '보울 안전 높이')


def home(robot, poses, vel, acc):
    move_safe(robot, poses, vel, acc)
    robot.movej(poses['home']['posj'], vel, acc, 'HOME')


def run_one(robot, name, snapshot, poses, hover, vel, acc, close_position, current,
            *, rotate=False, reference_yaw=None, place_z_offset_mm=0.0):
    pick(robot, name, snapshot, poses, hover, vel, acc, close_position, current,
         rotate=rotate, reference_yaw=reference_yaw)
    place(robot, snapshot, poses, hover, vel, acc, rotate=rotate,
          place_z_offset_mm=place_z_offset_mm)
