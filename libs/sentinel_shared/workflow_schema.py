"""Workflow definition schema consumed by the agent executor."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class RetryPolicy(BaseModel):
    on_failure: Literal["none", "once"] = "none"


class WorkflowStep(BaseModel):
    id: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    capture_metric: str | None = None
    timeout_seconds: int | None = None


class WorkflowDefinition(BaseModel):
    slug: str
    version: int
    name: str
    platform: list[str]
    timeout_seconds: int = 180
    steps: list[WorkflowStep] = Field(default_factory=list)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
