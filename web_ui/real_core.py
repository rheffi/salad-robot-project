"""Async API facade. Hardware has exactly one owning executor thread."""
from __future__ import annotations

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

from .hardware_backend import HardwareBackend, OperationStopped, ConfigurationChanged, PICKS
from .mock_core import MockCore, InvalidStateError
from .schemas import SystemState, RunRequest


class RealCore(MockCore):
    def __init__(self, backend=None):
        super().__init__()
        self.backend = backend if backend is not None else HardwareBackend()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='salad-ros')
        self.stop = threading.Event()
        self.initialized = False
        self.attempted = False
        self.closed = False
        self.recovery_required = False
        self.restart_required = False
        self.gripper_connected = False
        self.tcp = None
        self.camera_profile = None
        self.scene = None
        self.scene_id = None
        self.scene_valid = False
        self.fingerprint = None
        self.picture = None
        self.mode = 'REAL / DRY_RUN'

    async def worker(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, function, *args)

    def get_status(self):
        return {**super().get_status(), 'live_robot': True, 'mode': self.mode,
                'gripper_connected': self.gripper_connected, 'tcp': self.tcp,
                'scene_id': self.scene_id, 'scene_valid': self.scene_valid,
                'image_available': self.picture is not None,
                'recovery_required': self.recovery_required,
                'restart_required': self.restart_required, 'camera_profile': self.camera_profile}

    def ready(self):
        self._ensure_idle()
        if self.closed or not self.initialized or self.restart_required:
            raise InvalidStateError('초기화가 필요하거나 서버 재시작이 필요합니다.')
        if self.recovery_required:
            raise InvalidStateError('동작이 중단됐습니다. 현장에서 복구한 후 웹 서버를 재시작하세요.')

    async def initialize(self):
        self._ensure_idle()
        if self.attempted or self.closed:
            raise InvalidStateError('ROS 노드 재생성을 방지합니다. 재연결하려면 서버를 재시작하세요.')
        async def operation():
            self._set_state(SystemState.INITIALIZING, step='장비 연결 점검', progress=0)
            self._log('모델·보정·카메라·ROS·그리퍼 서비스 점검 시작 (이동 없음)')
            try:
                info = await self.worker(self.backend.initialize)
                self.initialized = True
                self.robot_connected = self.camera_connected = self.model_loaded = True
                self.gripper_connected = info['gripper_connected']
                self.tcp, self.camera_profile = info['tcp'], info['camera_profile']
                self._set_state(SystemState.READY, step='연결 점검 완료', progress=0)
                self._log('그리퍼 서비스 연결 확인. 실제 파지 성공 피드백은 제공되지 않습니다.')
            except Exception as exc:
                self.restart_required = True
                self.last_error = str(exc)
                self._set_state(SystemState.ERROR, step='초기화 실패')
                self._log(str(exc),'ERROR')
        job = await self.queue.submit('initialize', operation)
        self.attempted = True
        return job

    def invalidate(self):
        self.scene_valid = False
        for item in self.detections:
            item['valid'] = False
            item['reason'] = '배치 재확인 및 재촬영 필요'
        self._publish({'type':'detections','data':{'items':self.get_detections()}})

    async def detect_scene(self, rotate=False):
        self.ready()
        if self.state == SystemState.HOLDING:
            raise InvalidStateError('집은 박스를 먼저 반환하세요.')
        self.stop.clear()
        self.invalidate()
        async def operation():
            self._set_state(SystemState.OBSERVING,step='05 장면 인식',progress=0)
            try:
                scene, picture, fingerprint = await self.worker(self.backend.capture, rotate, self.stop)
                if self.stop.is_set(): raise OperationStopped('촬영 취소')
                self.scene, self.picture, self.fingerprint = scene, picture, fingerprint
                self.scene_id = uuid.uuid4().hex
                self.scene_valid = True
                self.last_error = None
                names = {'tomato':'토마토','cheese':'치즈','berry':'블루베리','bowl':'보울'}
                self.detections = []
                # Z is a taught action height, never a fabricated depth measurement.
                for name, item in scene['detections'].items():
                    self.detections.append(dict(id=name,class_name=name,display_name=names[name],
                        confidence=item['confidence'], pixel=[round(item['pixel_u']),round(item['pixel_v'])],
                        base_mm=[item['robot_x_mm'],item['robot_y_mm']], box=[],
                        angle_deg=item.get('orientation',{}).get('yaw_base_deg'), depth_m=None,
                        valid=True, reason=None,status='보울' if name=='bowl' else '대기'))
                self._publish({'type':'detections','data':{'items':self.get_detections()}})
                self._log('사진의 중심·박스 외곽·현재 배치를 확인한 뒤 실행하세요. 물체 이동 시 재촬영합니다.')
                self._set_state(SystemState.READY,step='사진 확인 대기',progress=0)
            except Exception as exc:
                self.last_error = str(exc)
                if isinstance(exc, ConfigurationChanged):
                    self.restart_required = True
                    self.invalidate()
                self._log(str(exc),'WARN' if self.stop.is_set() else 'ERROR')
                self._set_state(SystemState.READY if self.stop.is_set() else SystemState.ERROR,step='촬영 중단')
        return await self.queue.submit('detect',operation)

    async def execute_command(self, kind, payload: RunRequest):
        self.ready()
        expected = {'home':'MOVE HOME','bowl-hover':'MOVE BOWL',
                    'pick-hover':f'HOVER {payload.class_name.upper()}',
                    'pick':f'PICK {payload.class_name.upper()}',
                    'pick-place':'RUN ONE','salad':'RUN SALAD','return':'RETURN'}
        if kind not in expected: raise InvalidStateError('지원하지 않는 작업입니다.')
        if self.state == SystemState.HOLDING and kind != 'return':
            raise InvalidStateError('박스를 들고 있습니다. RETURN으로 원위치 반환만 가능합니다.')
        if kind == 'return' and self.state != SystemState.HOLDING:
            raise InvalidStateError('반환할 박스가 없습니다.')
        if kind != 'home':
            if (not self.scene_valid and kind != 'return') or self.scene is None:
                raise InvalidStateError('장면을 다시 촬영하세요.')
            if payload.scene_id != self.scene_id:
                raise InvalidStateError('화면과 서버의 장면이 다릅니다. 새 사진을 확인하세요.')
        if not payload.dry_run and payload.confirmation != expected[kind]:
            raise InvalidStateError(f'실제 이동 확인 문구: {expected[kind]}')
        if payload.rotate and payload.reference_yaw_deg is None:
            raise InvalidStateError('회전 기준각이 필요합니다.')
        if kind == 'salad' and payload.recipe != dict.fromkeys(PICKS,1):
            raise InvalidStateError('현재 전체 실행은 tomato/cheese/berry 각 1개입니다.')
        self.stop.clear()
        loop = asyncio.get_running_loop()
        scene = copy.deepcopy(self.scene)
        previous_state = self.state
        async def operation():
            motion_started = False
            self.mode = 'REAL / DRY_RUN' if payload.dry_run else 'REAL / LIVE'
            self.last_error = None
            self._set_state(SystemState.HOMING if kind=='home' else SystemState.APPROACHING,
                            step=f'{kind} 계획 검증',progress=0)
            try:
                poses = await self.worker(self.backend.preflight,kind,payload,scene,self.fingerprint)
                if self.stop.is_set(): raise OperationStopped('시작 전 취소')
                motion_started = not payload.dry_run
                if motion_started and kind not in ('pick-hover','bowl-hover'):
                    self.invalidate()
                count = 0
                def report_on_loop(message):
                    nonlocal count
                    count += 1
                    self.current_step = message
                    self.progress = min(95,count * (2 if kind=='salad' else 4))
                    if not self.stop.is_set():
                        if 'HOME' in message or 'safe_wait' in message:
                            self.state = SystemState.HOMING
                        elif '보울 열기' in message or '놓기 Z' in message or '반환 열기' in message:
                            self.state = SystemState.RELEASING
                        elif '닫기' in message or '집기 Z' in message:
                            self.state = SystemState.GRASPING
                        elif '상승' in message or '안전 높이' in message or 'bowl' in message:
                            self.state = SystemState.TRANSFERRING
                        elif 'Hover' in message:
                            self.state = SystemState.APPROACHING
                    self._log(message)
                    self._publish_status()
                def report(message): loop.call_soon_threadsafe(report_on_loop,message)
                await self.worker(self.backend.execute,kind,payload,scene,poses,self.stop,report)
                if self.stop.is_set(): raise OperationStopped('정지 요청 처리')
                if kind=='pick' and motion_started:
                    self._set_state(SystemState.HOLDING,step='파지 상태 확인 후 RETURN',progress=100)
                else:
                    target = previous_state if kind=='return' and payload.dry_run else SystemState.READY
                    if kind in ('salad','pick-place'): target = SystemState.FINISHED
                    self._set_state(target,step='계획 확인 완료' if payload.dry_run else '명령 순서 완료',progress=100)
                self._log('실제 파지 상태는 직접 확인하세요.' if motion_started else 'DRY RUN: 이동·그리퍼 명령을 보내지 않았습니다.')
            except Exception as exc:
                self.last_error = str(exc)
                if isinstance(exc, ConfigurationChanged):
                    self.restart_required = True
                    self.invalidate()
                if motion_started:
                    self.recovery_required = True
                    self.invalidate()
                self._log(str(exc),'ERROR')
                # Holding is not cleared by a failed return/preflight.
                self._set_state(SystemState.HOLDING if previous_state==SystemState.HOLDING and not motion_started
                                else SystemState.ERROR,step='중단: 상태 확인 필요')
        return await self.queue.submit(kind,operation)

    async def start_salad(self, recipe, *, dry_run=True):
        raise InvalidStateError('REAL 작업은 scene_id/확인 문구가 있는 execute_command를 사용하세요.')

    async def move_home(self):
        raise InvalidStateError('REAL HOME은 확인 문구가 있는 execute_command를 사용하세요.')

    async def request_stop(self):
        if self.queue.busy:
            self.stop.set()
            self._set_state(SystemState.STOPPING,step='현재 호출 종료 후 다음 명령 차단')
            self._log('즉시 정지가 아닙니다. 긴급 상황은 물리 E-STOP을 사용하세요.','WARN')

    async def cleanup(self):
        self._ensure_idle()
        if self.state==SystemState.HOLDING or self.recovery_required:
            raise InvalidStateError('장비 상태 확인/복구 후 서버를 종료하세요.')
        # Only disconnect at application shutdown, avoiding stale DSR module clients.
        self.invalidate()
        self._log('장면을 폐기했습니다. ROS 연결은 서버 종료까지 유지합니다.')

    async def shutdown(self):
        if self.closed: return
        self.closed = True
        self.stop.set()
        task = self.queue._active_task
        if task is not None:
            await asyncio.shield(task)
        try:
            await self.worker(self.backend.close)
        finally:
            self.executor.shutdown(wait=True)
