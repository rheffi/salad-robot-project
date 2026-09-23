"""Only the dedicated RealCore worker may use this hardware adapter."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
PICKS = ('tomato', 'cheese', 'berry')


class OperationStopped(RuntimeError):
    pass


class ConfigurationChanged(ValueError):
    pass


class RobotSteps:
    """Check stop before/after every blocking call; report commanded steps only."""
    def __init__(self, robot, poses, stop, report, dry_run):
        self.robot, self.poses = robot, poses
        self.stop, self.report, self.dry_run = stop, report, dry_run
        self.pose = list(poses['safe_wait']['posx'])

    def check(self):
        if self.stop.is_set():
            raise OperationStopped('정지 요청: 다음 명령을 보내지 않습니다.')

    def call(self, name, *args):
        self.check()
        label = str(args[-1]) if name != 'wait' else f'대기 {args[0]}초'
        self.report(f"{'[DRY] ' if self.dry_run else ''}{label}: {args[:-1] if name != 'wait' else args}")
        if not self.dry_run:
            getattr(self.robot, name)(*args)
        if name == 'movel': self.pose = list(args[0])
        if name == 'movej':
            self.pose = list(self.poses['safe_wait']['posx'])
        self.check()

    def state(self):
        self.check()
        return ([0]*6, self.pose) if self.dry_run else self.robot.state()

    def movel(self, *args): self.call('movel', *args)
    def movej(self, *args): self.call('movej', *args)
    def grip(self, *args): self.call('grip', *args)
    def wait(self, *args): self.call('wait', *args)


class HardwareBackend:
    def __init__(self):
        self.robot = None
        self.model = None
        self.lock = None
        self.owner = None
        self.camera = os.environ.get('SALAD_CAMERA', 'auto')
        self.correction_path = ROOT / 'config/xy_correction.json'
        self.poses_path = ROOT / 'config/robot_measurements.yaml'
        self.model_path = ROOT / 'ml/models/best.pt'
        self.holding = None

    def _thread(self):
        if self.owner is None: self.owner = threading.get_ident()
        if self.owner != threading.get_ident():
            raise RuntimeError('ROS 소유 스레드가 다릅니다.')

    def fingerprint(self):
        digest = hashlib.sha256()
        for p in (self.correction_path, self.poses_path):
            digest.update(p.read_bytes())
        stat = self.model_path.stat()
        digest.update(f'{stat.st_size}:{stat.st_mtime_ns}:{self.camera}'.encode())
        return digest.hexdigest()

    def settings(self):
        from robot_common import load_poses
        from scene_common import load_json, validate_correction
        correction = load_json(self.correction_path)
        validate_correction(correction)
        poses, tcp = load_poses(self.poses_path, ('home','safe_wait','pick_reference','place_reference'))
        return correction, poses, tcp

    def initialize(self):
        self._thread()
        import fcntl
        self.lock = open('/tmp/salad-robot-dsr01-domain15.lock', 'a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('다른 REAL 웹 서버가 장비를 사용 중입니다.') from exc
        scripts = str(ROOT / 'tools/measurement')
        if scripts not in sys.path: sys.path.insert(0, scripts)
        from robot_common import Robot
        from scene_common import YOLO, SCENE_CLASSES, find_camera
        import cv2
        correction, _, tcp = self.settings()
        self.model = YOLO(str(self.model_path))
        names = self.model.names.values() if isinstance(self.model.names, dict) else self.model.names
        if not set(SCENE_CLASSES).issubset(set(names)):
            raise ValueError('YOLO 필수 클래스가 없습니다.')
        cap = cv2.VideoCapture(find_camera(self.camera), cv2.CAP_V4L2)
        try:
            width, height = correction['camera']['width'], correction['camera']['height']
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, frame = cap.read()
            if not ok or frame.shape[:2] != (height,width):
                raise RuntimeError('RealSense 프레임/보정 해상도 확인 실패')
        finally:
            cap.release()
        self.robot = Robot(tcp, gripper=True, web_worker=True)
        self.robot.__enter__()
        self.health(tcp)
        self.initial_fingerprint = self.fingerprint()
        return {'tcp': tcp, 'gripper_connected': True, 'camera_profile': correction['camera']}

    def health(self, tcp):
        from dsr_gripper.gripper_api import _client
        if self.robot.api['get_tcp']() != tcp:
            raise RuntimeError('활성 TCP가 기록 TCP와 다릅니다.')
        if not _client().wait_for_service(timeout_sec=3):
            raise RuntimeError('그리퍼 서비스가 없습니다. 별도 터미널에서 gripper_service_a를 실행하세요.')
        names = self.robot.node.get_node_names()
        if names.count('gripper_service_a') != 1 or 'gripper_service' in names:
            raise RuntimeError('gripper_service_a 하나만 실행하세요. 기본 서비스 또는 중복 실행이 감지됐습니다.')

    def capture(self, rotate, stop):
        self._thread()
        from scene_common import capture_scene, save_snapshot
        import cv2
        correction, _, _ = self.settings()
        fingerprint = self.fingerprint()
        if fingerprint != self.initial_fingerprint:
            raise ConfigurationChanged('설정/모델이 변경됐습니다. 웹 서버를 재시작하세요.')
        snapshot, image = capture_scene(self.model_path, correction, self.camera, .5, 5,
                                        angles=rotate, display=False, should_stop=stop.is_set,
                                        loaded_model=self.model)
        if stop.is_set(): raise OperationStopped('촬영 취소')
        if fingerprint != self.fingerprint(): raise ConfigurationChanged('촬영 중 설정이 변경됐습니다. 서버를 재시작하세요.')
        save_snapshot(snapshot,image,ROOT/'records/web_scene_snapshot.json',ROOT/'records/web_scene_snapshot.jpg')
        ok, encoded = cv2.imencode('.jpg', image)
        if not ok: raise RuntimeError('장면 이미지 인코딩 실패')
        return snapshot, encoded.tobytes(), fingerprint

    def preflight(self, kind, payload, snapshot, fingerprint):
        self._thread()
        from robot_common import validate_settings, pick_reference_for_item
        from scene_common import validate_target, pixel_to_robot_xy
        correction, poses, tcp = self.settings()
        if self.fingerprint() != self.initial_fingerprint:
            raise ConfigurationChanged('설정/모델 변경: 웹 서버를 재시작하고 다시 촬영하세요.')
        if kind != 'home' and fingerprint != self.fingerprint():
            raise ValueError('장면 촬영 후 설정이 바뀌었습니다. 다시 촬영하세요.')
        validate_settings(poses, payload.hover_height_mm, payload.vel, payload.acc)
        if kind == 'salad':
            import salad_workflow as flow
            flow.validate_place_offsets(poses, payload.hover_height_mm)
        if kind != 'home':
            for name in (*PICKS,'bowl'):
                item = snapshot['detections'][name]
                u,v,x,y = [float(item[k]) for k in ('pixel_u','pixel_v','robot_x_mm','robot_y_mm')]
                validate_target(u,v,x,y,correction)
                computed = pixel_to_robot_xy(u,v,correction)
                if max(abs(computed[0]-x),abs(computed[1]-y)) > .01:
                    raise ValueError('장면 XY와 현재 보정 불일치')
            if payload.rotate:
                for name in PICKS:
                    pick_reference_for_item(poses['pick_reference']['posx'],snapshot['detections'][name],
                                            rotate=True,reference_yaw=payload.reference_yaw_deg)
        if not payload.dry_run:
            self.health(tcp)
        return poses

    def execute(self, kind, payload, snapshot, poses, stop, report):
        self._thread()
        import salad_workflow as flow
        from robot_common import move_safe
        robot = RobotSteps(self.robot, poses, stop, report, payload.dry_run)
        robot.check()
        if not payload.dry_run:
            self.robot.autonomous()
        robot.check()
        options = dict(rotate=payload.rotate, reference_yaw=payload.reference_yaw_deg)
        args = (payload.hover_height_mm,payload.vel,payload.acc)
        if kind == 'home':
            flow.home(robot,poses,payload.vel,payload.acc)
        elif kind == 'bowl-hover':
            move_safe(robot,poses,payload.vel,payload.acc)
            flow.bowl_hover(robot,snapshot,poses,*args,rotate=payload.rotate)
        elif kind in ('pick','pick-hover'):
            points = flow.pick(robot,payload.class_name,snapshot,poses,*args,430,200,
                               **options,hover_only=kind=='pick-hover')
            if kind == 'pick' and not payload.dry_run:
                self.holding = (points,copy.deepcopy(poses))
        elif kind == 'return':
            if self.holding is None: raise ValueError('반환할 집기 기록이 없습니다.')
            points, held_poses = self.holding
            flow.return_pick(robot,points,held_poses,payload.vel,payload.acc)
            if not payload.dry_run: self.holding = None
        else:
            targets = PICKS if kind == 'salad' else (payload.class_name,)
            for index, name in enumerate(targets):
                place_offset = flow.PLACE_Z_OFFSETS_MM[index] if kind == 'salad' else 0.0
                flow.run_one(robot,name,snapshot,poses,*args,430,200,**options,
                             place_z_offset_mm=place_offset)
            flow.home(robot,poses,payload.vel,payload.acc)

    def close(self):
        self._thread()
        try:
            if self.robot is not None:
                self.robot.__exit__(None,None,None)
                self.robot = None
        finally:
            if self.lock is not None:
                self.lock.close()
                self.lock = None
