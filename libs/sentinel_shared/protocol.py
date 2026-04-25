"""HTTP protocol message types for agent↔cloud communication."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    registration_token: str
    hostname: str
    os_platform: Literal["windows", "macos", "ios", "android"]
    os_version: str
    mdm_device_id: str


class RegisterResponse(BaseModel):
    endpoint_id: str
    bearer_token: str


class AgentCommand(BaseModel):
    command_id: str
    command_type: Literal["run_workflow", "heartbeat_ack", "config_update", "ping"]
    payload: dict[str, Any] = Field(default_factory=dict)


class ResultUpload(BaseModel):
    run_id: str
    workflow_id: str
    result: Literal["pass", "fail", "degraded"]
    duration_ms: int | None = None
    failure_reason: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
