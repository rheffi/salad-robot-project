from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SystemState(str, Enum):
    OFFLINE = "OFFLINE"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    OBSERVING = "OBSERVING"
    TARGET_SELECTED = "TARGET_SELECTED"
    APPROACHING = "APPROACHING"
    GRASPING = "GRASPING"
    TRANSFERRING = "TRANSFERRING"
    RELEASING = "RELEASING"
    POURING = "POURING"
    HOMING = "HOMING"
    STOPPING = "STOPPING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


class CommandAccepted(BaseModel):
    accepted: bool = True
    job_id: str | None = None
    message: str


class RunRequest(BaseModel):
    recipe: dict[str, int] = Field(
        default_factory=lambda: {"tomato": 1, "lettuce": 1, "carrot": 1}
    )
    dry_run: bool = True


class Detection(BaseModel):
    id: str
    class_name: str
    display_name: str
    confidence: float
    pixel: list[int]
    angle_deg: float
    depth_m: float
    base_mm: list[float]
    box: list[int]
    valid: bool = True
    reason: str | None = None
    status: str = "대기"


class StatusSnapshot(BaseModel):
    state: SystemState
    robot_connected: bool
    camera_connected: bool
    model_loaded: bool
    live_robot: bool = False
    mode: str = "DRY_RUN"
    busy: bool
    active_job_id: str | None
    current_step: str | None
    progress: int
    last_error: str | None
    updated_at: str


class EventMessage(BaseModel):
    type: str
    data: dict[str, Any]
