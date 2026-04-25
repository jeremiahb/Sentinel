"""Policy-event service abstraction for webhook ingestion."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import uuid4

from libs.sentinel_shared.models import PolicyEvent


@dataclass
class InMemoryPolicyEventStore:
    _events: list[PolicyEvent] = field(default_factory=list)

    def insert(self, event: PolicyEvent) -> PolicyEvent:
        saved = event.model_copy(update={"id": event.id or str(uuid4())})
        self._events.append(saved)
        return saved

    def list(self) -> Sequence[PolicyEvent]:
        return tuple(self._events)
