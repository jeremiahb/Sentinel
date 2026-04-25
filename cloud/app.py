"""FastAPI entrypoint for Sentinel cloud prototype."""

from fastapi import FastAPI

from cloud.routes.webhooks import router as webhook_router
from cloud.services.policy_events import InMemoryPolicyEventStore


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel Cloud", version="0.1.0")
    app.state.policy_event_store = InMemoryPolicyEventStore()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(webhook_router)
    return app


app = create_app()
