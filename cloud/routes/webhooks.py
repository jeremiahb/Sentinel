"""Webhook endpoints for MDM integrations."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from cloud.services.policy_events import InMemoryPolicyEventStore
from libs.sentinel_shared.models import PolicyEvent

router = APIRouter(prefix="/webhook", tags=["webhooks"])


def get_policy_event_store(request: Request) -> InMemoryPolicyEventStore:
    return request.app.state.policy_event_store


@router.post("/intune")
async def intune_webhook(
    request: Request,
    validation_token: str | None = Query(default=None, alias="validationToken"),
    event_store: InMemoryPolicyEventStore = Depends(get_policy_event_store),
) -> Response | dict[str, int]:
    if validation_token:
        return Response(content=validation_token, media_type="text/plain")

    body = await request.json()
    notifications: list[dict[str, Any]] = body.get("value", [])

    for notification in notifications:
        event = PolicyEvent(
            external_id=notification.get("id", "unknown"),
            policy_name=notification.get("resource", "unknown"),
            policy_type="graph_change_notification",
            target_groups=notification.get("targetGroups", []),
            deployed_by=notification.get("actor"),
            deployed_at=datetime.now(UTC),
            raw_payload=notification,
        )
        event_store.insert(event)

    return Response(status_code=202)
