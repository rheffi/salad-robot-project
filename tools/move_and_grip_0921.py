import sys
import numpy as np
import cv2
import scipy
import pyrealsense2 as rs
import matplotlib.pyplot as plt
from dsr_gripper import gripper_open, gripper_close

import rclpy
import time

#################### move coord 로봇 세팅
ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"

import DR_init
DR_init.__dsr__id    = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

rclpy.init()
node = rclpy.create_node("vision_to_robot_notebook", namespace=ROBOT_ID)
DR_init.__dsr__node = node

import DSR_ROBOT2 as dsr
from DSR_ROBOT2 import (
    movej, movel, get_current_posj, get_current_posx,
    set_robot_mode, get_robot_mode,
    ROBOT_MODE_AUTONOMOUS, ROBOT_MODE_MANUAL,
    DR_BASE, DR_MV_MOD_ABS, DR_MV_MOD_REL,
)
from DSR_ROBOT2 import posj, posx

# 서비스가 발견될 때까지 잠깐 대기 — 노드를 만들자마자 바로 호출하면
# 요청이 유실되어 '응답 없이 무한 대기'에 빠질 수 있습니다.
assert dsr._ros2_get_robot_mode.wait_for_service(timeout_sec=10.0), (
    "로봇 서비스를 찾지 못했습니다 — bringup 실행 여부와 "
    "ROS_DOMAIN_ID(주피터 터미널 vs bringup 터미널)를 확인하세요.")

set_robot_mode(ROBOT_MODE_AUTONOMOUS)
x, sol = get_current_posx()
print("로봇이 연결되었습니다. 현재 좌표 [x,y,z,rx,ry,rz]:", [round(v, 1) for v in x])


pipeline = rs.pipeline()

modes = [((1280, 720, 30), (1280, 720, 30)),   # USB3
         ((1280, 720, 15), (848, 480, 15)),    # USB2 폴백
         ((640, 480, 30), (640, 480, 30))]
u, v = 334, 194       # CLICK_MODE=False 일 때 쓰는 값
show = False
CALIB_PATH = "/home/jaewoo/HamdEyeCal/T_base_camera.npy"

profile = None
for (cw, ch, cf), (dw, dh, df) in modes:
    try:
        config = rs.config()
        config.enable_stream(rs.stream.color, cw, ch, rs.format.bgr8, cf)
        config.enable_stream(rs.stream.depth, dw, dh, rs.format.z16, df)
        profile = pipeline.start(config)
        print(f"카메라 시작: color {cw}x{ch}@{cf} / depth {dw}x{dh}@{df}")
        break
    except RuntimeError:
        continue
assert profile is not None, "카메라 시작 실패 — USB 연결과 realsense-viewer 를 확인하세요."

align = rs.align(rs.stream.color)   # 깊이를 컬러 픽셀에 정렬
for _ in range(15):                 # 자동노출 안정화
    align.process(pipeline.wait_for_frames())

# 컬러 카메라 내부 파라미터(intrinsics) — 픽셀→3D 변환에 필요
intr = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
print(f"intrinsics: fx={intr.fx:.1f}, fy={intr.fy:.1f}, ppx={intr.ppx:.1f}, ppy={intr.ppy:.1f}")

# 가리는 것이 없게 초기 세팅
ready = posj(90, 0, 90, 0, 90, 0)
movej(ready, vel=20, acc=20)

# 새 프레임 한 장 (컬러+깊이 동시 — 이 깊이를 3장에서 그대로 사용)

frames = align.process(pipeline.wait_for_frames())
color_frame = frames.get_color_frame()
depth_frame = frames.get_depth_frame()
color = np.asanyarray(color_frame.get_data())

if show:
    print(f"선택한 픽셀: u={u}, v={v}")
    vis = color.copy()
    cv2.drawMarker(vis, (int(u), int(v)), (0, 0, 255), cv2.MARKER_CROSS, 30, 3)
    plt.figure(figsize=(10, 6))
    plt.imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    plt.title(f"selected pixel ({u}, {v})")
    plt.axis("off"); plt.show()


#################### move coord depth 계산
def pixel_to_camera_point(u, v, depth_frame, win=4):
    """(u,v) 주변 (2*win+1)^2 픽셀의 깊이 중앙값으로 카메라 좌표계 3D 점(m)을 계산."""
    d_intr = depth_frame.profile.as_video_stream_profile().get_intrinsics()
    pts = []
    for du in range(-win, win + 1):
        for dv in range(-win, win + 1):
            uu, vv = int(u) + du, int(v) + dv
            if 0 <= uu < d_intr.width and 0 <= vv < d_intr.height:
                z = depth_frame.get_distance(uu, vv)
                if 0.2 <= z <= 1.5:          # 유효 범위 밖(0이나 너무 먼 값)은 버림
                    pts.append(rs.rs2_deproject_pixel_to_point(d_intr, [float(uu), float(vv)], z))
    assert pts, ("유효한 깊이가 없습니다 — 반사가 심하거나 너무 가깝거나(0.2m 미만) "
                 "너무 먼(1.5m 초과) 지점입니다. 다른 지점을 클릭해 보세요.")
    return np.median(np.array(pts), axis=0)   # [X, Y, Z] (m)

#################### move coord 캘리브레이션
# ★ 본인 캘리브레이션 결과 파일 경로로 수정하세요

# 동차좌표 변환: 카메라 좌표(m) → base 좌표(m) → mm
def coord_uv(u, v, tip):
    T_base_camera = np.load(CALIB_PATH)

    p_cam = pixel_to_camera_point(u, v, depth_frame)
    p_base = (T_base_camera @ np.array([p_cam[0], p_cam[1], p_cam[2], 1.0]))[:3]
    target_mm = p_base * 1000.0
    print(f"\n물체의 로봇 base 좌표 (mm): x={target_mm[0]:.0f}, y={target_mm[1]:.0f}, z={target_mm[2]:.0f}")

    # 도달 가능 범위(수평거리) 확인 — e0509 작업반경은 약 900mm
    r = float(np.hypot(target_mm[0], target_mm[1]))
    print(f"base에서 수평거리: {r:.0f} mm", "(OK)" if 150 < r < 850 else " 도달범위 밖! 좌표를 다시 확인하세요")
    #################### move coord 그리퍼 확인
    new_tip = [float(target_mm[0]), float(target_mm[1]), float(tip[2])]  # z는 현재 높이 유지

    r = float(np.hypot(new_tip[0], new_tip[1]))
    assert 150 < r < 850, f"목표 수평거리 {r:.0f}mm 가 도달범위 밖 — 캘리브/좌표를 확인하세요."

    return new_tip, target_mm

#################### move coord 그리퍼 세팅
from scipy.spatial.transform import Rotation as Rot

TCP_Z_MM = 50.0     # 플랜지→그리퍼 끝 거리(mm). ★불확실하면 실제보다 '길게'(로봇이 덜 내려가서 안전)
Z_MIN_MM = 50.0      # 그리퍼 끝이 이 높이(mm) 아래로 내려가는 명령은 거부

def gripper_tip():
    """현재 그리퍼 끝의 base 좌표(mm)와 현재 posx 를 반환."""
    pose, _ = get_current_posx()
    R = Rot.from_euler("ZYZ", pose[3:6], degrees=True).as_matrix()   # ZYZ!
    tip = np.array(pose[:3]) + R @ np.array([0.0, 0.0, TCP_Z_MM])
    return tip, list(pose)

def flange_target_for_tip(tip_xyz, rxyz):
    """그리퍼 끝을 tip_xyz(base, mm)에 두려면 플랜지가 가야 할 posx."""
    R = Rot.from_euler("ZYZ", rxyz, degrees=True).as_matrix()
    f = np.array(tip_xyz) - R @ np.array([0.0, 0.0, TCP_Z_MM])
    return posx(float(f[0]), float(f[1]), float(f[2]), *[float(a) for a in rxyz])

# 특이점 회피: 먼저 준비자세로 (모든 관절 0도에서는 movel 불가)
ready = posj(0, 0, 90, 0, 90, 0)
print("준비자세로 이동 (movej)…")
movej(ready, vel=20, acc=20)
tip, pose = gripper_tip()
print(f"현재 그리퍼 끝(계산값): x={tip[0]:.0f}, y={tip[1]:.0f}, z={tip[2]:.0f} (mm)")

new_tip, target_mm = coord_uv(334, 194, tip)
new_tip2, target_mm2 = coord_uv(310, 175, tip)

CALIB_OFFSET_MM = [-100.0, 0.0, 0.0]   # [x, y, z] 캘리브 오차 보정 (mm). y로 +100mm

def move_coord_offset(offset,new_tip, pose):
    tip_fix = [new_tip[0] + offset[0],
               new_tip[1] + offset[1],
               new_tip[2] + offset[2]]
    movel(flange_target_for_tip(tip_fix, pose[3:6]), vel=20, acc=20, ref=DR_BASE, mod=DR_MV_MOD_ABS)

def check_calibration(new_tip):
    tip_fix = [new_tip[0] + CALIB_OFFSET_MM[0],
               new_tip[1] + CALIB_OFFSET_MM[1],
               new_tip[2] + CALIB_OFFSET_MM[2]]

    print(f"그리퍼 끝을 ({new_tip[0]:.0f}, {new_tip[1]:.0f}) 위로 수평 이동합니다 (높이 {tip[2]:.0f}mm 유지)")
    print(f"보정 후 목표: ({tip_fix[0]:.0f}, {tip_fix[1]:.0f})  offset={CALIB_OFFSET_MM}")
    input(" 로봇이 움직입니다! 주변 확인 후 Enter…")
    movel(flange_target_for_tip(tip_fix, pose[3:6]), vel=20, acc=20, ref=DR_BASE, mod=DR_MV_MOD_ABS)
    print("완료 — 그리퍼 끝이 물체 바로 위에 있는지 눈으로 확인하세요!")
    print("   (어긋나 있으면: 캘리브 오차입니다. 몇 mm쯤인지 관찰해 두세요)")

# check_calibration()


#################### move coord 로봇 수평 이동
def move_updown(mm, target_mm):
    STEP_MM = mm   # 한 번 실행에 내려갈 양(mm)

    tip, _ = gripper_tip()
    new_z = tip[2] - STEP_MM
    assert new_z >= Z_MIN_MM, (f"그리퍼 끝 {tip[2]:.0f}mm 에서 더 내리면 최저높이({Z_MIN_MM}mm) 보다 "
                               "낮아집니다 — 정말 필요하면 Z_MIN_MM 를 신중히 낮추세요.")
    movel(posx(0, 0, -STEP_MM, 0, 0, 0), vel=20, acc=20, ref=DR_BASE, mod=DR_MV_MOD_REL)
    tip, _ = gripper_tip()
    print(f"그리퍼 끝 z = {tip[2]:.0f} mm | 물체 z(카메라 추정) = {target_mm[2]:.0f} mm")
    print("→ 물체 높이 근처까지 왔으면 다음 셀로. 아직이면 이 셀을 다시 실행.")

    gripper(250)

    movel(posx(0, 0, STEP_MM, 0, 0, 0), vel=20, acc=20, ref=DR_BASE, mod=DR_MV_MOD_REL)

GRIP_WAIT = 1.0   # 그리퍼 개폐 대기(초) — 실측해서 조정

def move_updown1(clearance_mm, target_mm):
    gripper_open()
    time.sleep(GRIP_WAIT)          # 내려가기 전에 확실히 열어둔다

    tip, _ = gripper_tip()
    new_z = max(float(target_mm[2]) + clearance_mm, Z_MIN_MM)
    dz = new_z - tip[2]
    print(f"그리퍼 끝 z: {tip[2]:.0f} → {new_z:.0f} mm ({dz:+.0f}mm)")

    movel(posx(0, 0, dz, 0, 0, 0), vel=20, acc=20, ref=DR_BASE, mod=DR_MV_MOD_REL)

    gripper_close(current=250)
    time.sleep(GRIP_WAIT)          # 다 잡을 때까지 기다린 뒤 올라간다

    movel(posx(0, 0, -dz, 0, 0, 0), vel=20, acc=20, ref=DR_BASE, mod=DR_MV_MOD_REL)


#################### move랑 그랩
def ready_and_move(new_tip, pose):
    ready = posj(0, 0, 90, 0, 90, 0)
    movej(ready, vel=30, acc=30)

    move_coord_offset(CALIB_OFFSET_MM, new_tip, pose)

    delta = posx(50, -50, -50, 0, 0, 0)
    print("상대좌표로 이동:", list(delta))
    movel(delta, vel=30, acc=30, ref=DR_BASE, mod=DR_MV_MOD_REL)

    return ready

def gripper(current):
    gripper_open()
    print("그리퍼 열림 — 필요하면 위 '조금씩 내려가기' 셀로 몇 스텝 더 내려간 뒤,")
    print("아래 줄의 주석(#)을 지우고 실행해 잡아보세요.")
    gripper_close(current=current)
    time.sleep(3)

def endpoint():
    pipeline.stop()
    node.destroy_node()
    rclpy.shutdown()
    print("종료 완료")

ready_and_move(new_tip, pose)
move_updown(200, target_mm)

print("시작 자세로 복귀")
movej(ready, vel=30, acc=30)
print("완료")
gripper_open()

ready_and_move(new_tip2, pose)
move_updown(200, target_mm2)

print("시작 자세로 복귀")
movej(ready, vel=30, acc=30)
print("완료")
gripper_open()

endpoint()