from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from .command_queue import CommandBusyError, CommandQueue
from .schemas import SystemState


class InvalidStateError(RuntimeError):
    """Raised when a command is not allowed in the current state."""


class StopRequested(RuntimeError):
    """Internal control flow used to leave a mock operation safely."""


class MockCore:
    def __init__(self, *, step_delay: float = 0.55) -> None:
        self.step_delay = step_delay
        self.queue = CommandQueue()
        self.state = SystemState.OFFLINE
        self.robot_connected = False
        self.camera_connected = False
        self.model_loaded = False
        self.current_step: str | None = None
        self.progress = 0
        self.last_error: str | None = None
        self.detections: list[dict[str, Any]] = []
        self.logs: deque[dict[str, Any]] = deque(maxlen=300)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._stop_event = asyncio.Event()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "robot_connected": self.robot_connected,
            "camera_connected": self.camera_connected,
            "model_loaded": self.model_loaded,
            "live_robot": False,
            "mode": "DRY_RUN",
            "busy": self.queue.busy,
            "active_job_id": self.queue.active_job_id,
            "current_step": self.current_step,
            "progress": self.progress,
            "last_error": self.last_error,
            "updated_at": self._timestamp(),
        }

    def get_detections(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.detections]

    def get_logs(self) -> list[dict[str, Any]]:
        return list(self.logs)

    def clear_logs(self) -> None:
        self.logs.clear()
        self._publish({"type": "logs_cleared", "data": {}})

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def _publish_status(self) -> None:
        self._publish({"type": "status", "data": self.get_status()})

    def _log(self, message: str, level: str = "INFO") -> None:
        entry = {
            "timestamp": self._timestamp(),
            "level": level,
            "message": message,
        }
        self.logs.append(entry)
        self._publish({"type": "log", "data": entry})

    def _set_state(
        self,
        state: SystemState,
        *,
        step: str | None = None,
        progress: int | None = None,
    ) -> None:
        self.state = state
        self.current_step = step
        if progress is not None:
            self.progress = max(0, min(100, progress))
        self._publish_status()

    async def _pause(self, multiplier: float = 1.0) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(), timeout=self.step_delay * multiplier
            )
        except TimeoutError:
            return
        raise StopRequested

    async def _guarded(self, operation: Callable[[], Awaitable[None]]) -> None:
        try:
            await operation()
        except StopRequested:
            self._set_state(SystemState.STOPPING, step="정지 처리", progress=self.progress)
            self._log("소프트웨어 정지 요청을 처리했습니다.", "WARN")
            await asyncio.sleep(min(self.step_delay, 0.1))
            fallback = SystemState.READY if self.camera_connected else SystemState.OFFLINE
            self._set_state(fallback, step=None, progress=0)
        except Exception as exc:
            self.last_error = str(exc)
            self._set_state(SystemState.ERROR, step="오류", progress=self.progress)
            self._log(f"작업 오류: {exc}", "ERROR")

    def _ensure_idle(self) -> None:
        if self.queue.busy:
            raise CommandBusyError("다른 작업이 실행 중입니다.")

    def _require_state(self, *allowed: SystemState) -> None:
        if self.state not in allowed:
            expected = ", ".join(item.value for item in allowed)
            raise InvalidStateError(
                f"현재 상태 {self.state.value}에서는 실행할 수 없습니다. 허용 상태: {expected}"
            )

    async def initialize(self) -> str:
        self._ensure_idle()
        self._require_state(SystemState.OFFLINE, SystemState.ERROR)
        self._stop_event.clear()
        return await self.queue.submit(
            "initialize", lambda: self._guarded(self._initialize_operation)
        )

    async def _initialize_operation(self) -> None:
        self.last_error = None
        self.progress = 0
        self._set_state(SystemState.INITIALIZING, step="Mock 서비스 시작", progress=8)
        self._log("Mock 시스템 초기화를 시작합니다.")
        await self._pause()

        self.camera_connected = True
        self._set_state(SystemState.INITIALIZING, step="가상 카메라 연결", progress=38)
        self._log("가상 RealSense 연결 완료")
        await self._pause()

        self.model_loaded = True
        self._set_state(SystemState.INITIALIZING, step="Mock YOLO 모델 로드", progress=68)
        self._log("Mock YOLO 모델 로드 완료")
        await self._pause()

        self.robot_connected = True
        self._log("가상 로봇 연결 완료 — 실제 로봇 명령은 전송되지 않습니다.")
        self._set_state(SystemState.READY, step=None, progress=0)
        self._log("시스템 준비 완료 (DRY RUN 전용)")

    async def detect_scene(self) -> str:
        self._ensure_idle()
        self._require_state(SystemState.READY, SystemState.FINISHED)
        self._stop_event.clear()
        return await self.queue.submit(
            "detect", lambda: self._guarded(self._detect_operation)
        )

    async def _detect_operation(self) -> None:
        self._set_state(SystemState.OBSERVING, step="작업대 촬영", progress=12)
        self._log("가상 작업대 영상을 분석합니다.")
        await self._pause(1.2)

        self.detections = [
            {
                "id": "ingredient-tomato-01",
                "class_name": "tomato",
                "display_name": "토마토",
                "confidence": 0.94,
                "pixel": [342, 252],
                "angle_deg": 18.0,
                "depth_m": 0.61,
                "base_mm": [487.0, 143.0, 72.0],
                "box": [258, 201, 168, 102],
                "valid": True,
                "reason": None,
                "status": "대기",
            },
            {
                "id": "ingredient-cheese-01",
                "class_name": "cheese",
                "display_name": "치즈",
                "confidence": 0.89,
                "pixel": [641, 395],
                "angle_deg": 71.0,
                "depth_m": 0.64,
                "base_mm": [532.0, -46.0, 68.0],
                "box": [564, 329, 154, 132],
                "valid": True,
                "reason": None,
                "status": "대기",
            },
            {
                "id": "ingredient-berry-01",
                "class_name": "berry",
                "display_name": "블루베리",
                "confidence": 0.91,
                "pixel": [879, 238],
                "angle_deg": 132.0,
                "depth_m": 0.60,
                "base_mm": [474.0, -184.0, 75.0],
                "box": [792, 202, 174, 72],
                "valid": True,
                "reason": None,
                "status": "대기",
            },
        ]
        self.detections.append(dict(id='bowl',class_name='bowl',display_name='보울',confidence=.96,
                                    pixel=[640,360],angle_deg=0,depth_m=None,base_mm=[500,0,288],
                                    box=[520,240,240,240],valid=True,reason=None,status='보울'))
        self._publish({"type": "detections", "data": {"items": self.get_detections()}})
        self._set_state(SystemState.READY, step=None, progress=0)
        self._log("재료 3개 감지 완료")

    async def start_salad(self, recipe: dict[str, int], *, dry_run: bool) -> str:
        if not dry_run:
            raise InvalidStateError("Mock MVP에서는 실제 로봇 실행을 허용하지 않습니다.")
        self._ensure_idle()
        self._require_state(SystemState.READY)
        if not self.detections:
            raise InvalidStateError("먼저 장면 인식을 실행해야 합니다.")
        self._stop_event.clear()
        return await self.queue.submit(
            "salad",
            lambda: self._guarded(lambda: self._run_salad_operation(recipe)),
        )

    async def _run_salad_operation(self, recipe: dict[str, int]) -> None:
        requested = {name for name, count in recipe.items() if count > 0}
        targets = [item for item in self.detections if item["class_name"] in requested and item['class_name'] != 'bowl']
        if not targets:
            raise InvalidStateError('선택한 재료가 없습니다.')

        phases = [
            (SystemState.TARGET_SELECTED, "대상 선택"),
            (SystemState.APPROACHING, "접근점 이동"),
            (SystemState.GRASPING, "재료 집기"),
            (SystemState.TRANSFERRING, "보울로 이송"),
            (SystemState.RELEASING, "보울에 놓기"),
        ]
        total_steps = len(targets) * len(phases) + 2
        completed_steps = 0
        self._log(f"DRY RUN 시작 — 재료 {len(targets)}개")

        for target in targets:
            target["status"] = "처리 중"
            self._publish({"type": "detections", "data": {"items": self.get_detections()}})
            for state, label in phases:
                completed_steps += 1
                progress = round(completed_steps / total_steps * 100)
                step = f"{target['display_name']} · {label}"
                self._set_state(state, step=step, progress=progress)
                self._log(step)
                await self._pause()
            target["status"] = "완료"
            self._publish({"type": "detections", "data": {"items": self.get_detections()}})

        self._set_state(SystemState.HOMING, step="HOME 복귀", progress=94)
        self._log("HOME 복귀 시뮬레이션 — 소스병 동작 제외")
        await self._pause(1.4)

        self._set_state(SystemState.FINISHED, step="작업 완료", progress=100)
        self._log("Mock 샐러드 작업을 완료했습니다.")

    async def request_stop(self) -> None:
        if not self.queue.busy:
            self._log("실행 중인 작업이 없어 정지 요청을 건너뜁니다.", "WARN")
            return
        self._stop_event.set()
        self._set_state(SystemState.STOPPING, step="안전 정지 요청", progress=self.progress)
        self._log("소프트웨어 정지를 요청했습니다.", "WARN")

    async def move_home(self) -> str:
        self._ensure_idle()
        self._require_state(SystemState.READY, SystemState.FINISHED)
        self._stop_event.clear()
        return await self.queue.submit(
            "home", lambda: self._guarded(self._home_operation)
        )

    async def _home_operation(self) -> None:
        self._set_state(SystemState.HOMING, step="준비자세 복귀", progress=35)
        self._log("가상 로봇을 준비자세로 복귀합니다.")
        await self._pause(1.4)
        self._set_state(SystemState.READY, step=None, progress=0)
        self._log("준비자세 복귀 완료")

    async def cleanup(self) -> None:
        if self.queue.busy:
            self._stop_event.set()
            try:
                await self.queue.wait_for_idle(timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
        self.robot_connected = False
        self.camera_connected = False
        self.model_loaded = False
        self.detections = []
        self.current_step = None
        self.progress = 0
        self.state = SystemState.OFFLINE
        self._publish_status()
        self._log("Mock 자원을 정리했습니다.")

    async def shutdown(self) -> None:
        await self.cleanup()
