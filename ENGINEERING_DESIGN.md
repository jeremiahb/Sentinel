# Engineering Design: Sentinel (Claude-Code Build Edition)

**Product:** Endpoint Policy UAT Agent  
**Document version:** 0.2  
**Status:** Draft — optimized for Claude-Code-as-builder  
**Builder profile:** Jeremiah (human in the loop) + Claude Code  
**Starting scope:** Intune + Windows 11, three workflows, single tenant, local dev  
**Roadmap:** Jamf for Mac, then Intune for mobile (iOS/Android)

---

## 1. Purpose of This Document

This is a rewrite of the v0.1 design doc for a different builder — Claude Code rather than a team of engineers. The architectural calls, language choices, and scope have been revised accordingly. The goal is a prototype that proves the product works end-to-end, written in code clean enough to evolve into production without a from-scratch rewrite.

### What changed from v0.1

| v0.1 (engineering team) | v0.2 (Claude Code + Jeremiah) |
|------------------------|-------------------------------|
| Go agent | Python agent (faster iteration with Claude Code, rewrite later if perf demands) |
| Kafka event bus | Postgres-backed job queue (no Kafka in prototype) |
| Kubernetes deployment | Single VM or Fly.io/Railway for cloud; native binaries for agent |
| Multi-tenant from day one | Single-tenant; designed for multi-tenant later |
| TimescaleDB for metrics | Postgres with partitioned tables, add Timescale later |
| Kafka, Vault, Redis, K8s | Postgres, local file storage, one runtime |
| 5 workflows, 2 OSes, 2 MDMs | 3 workflows, 1 OS, 1 MDM |
| SOC 2 in scope | Deferred until first paying customer |

The v1 north star hasn't changed. The path to it has.

---

## 2. Build Principles

These are the ground rules for every decision in this doc.

1. **Boring stack, boring choices.** Python, Postgres, FastAPI, htmx or Next.js for UI. Every component should be one Claude Code can reason about cleanly and debug from logs alone.
2. **Single codebase, monorepo.** Everything in one repo — cloud service, agent, workflow definitions, shared schema. No microservices in the prototype. Claude Code works better across a single well-structured codebase than across many.
3. **Decoupled components, not distributed components.** Clear module boundaries, dependency injection, testable units. But everything runs in one or two processes, not ten.
4. **Interfaces first.** Before Claude Code writes a component, the interface it implements is defined. This is how you keep the codebase coherent when most of it is being generated.
5. **Tests are not optional.** Every component ships with tests. Claude Code writes tests as part of every feature. The test suite is how you trust the codebase you didn't type.
6. **Logging is a first-class concern.** Structured logging everywhere, because when something breaks at 11pm you need to reason about it from logs, not a debugger you don't have time to attach.
7. **Evolution path, not rewrite path.** Every architectural choice has an answer to the question "what does this look like when we have 10 paying customers?" If the answer is "rewrite it," rethink the choice now.

---

## 3. Architecture Overview

### 3.1 Runtime topology (prototype)

```text
┌─────────────────────────────────────────────────────────────┐
│  CUSTOMER ENV (initially: your own test environment)        │
│                                                              │
│   ┌───────────────────────────────┐                         │
│   │  Windows 11 Reference VM      │                         │
│   │  ┌──────────────────────────┐ │                         │
│   │  │  Sentinel Agent (Python) │ │                         │
│   │  │  - executes workflows    │ │                         │
│   │  │  - captures artifacts    │ │                         │
│   │  │  - HTTPS out only        │ │                         │
│   │  └────────────┬─────────────┘ │                         │
│   └───────────────┼───────────────┘                         │
└───────────────────┼─────────────────────────────────────────┘
                    │ HTTPS (mTLS later; bearer token now)
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  SENTINEL CLOUD (single process during prototype)            │
│                                                              │
│   ┌────────────────────────────────────────────────────┐    │
│   │  FastAPI app                                       │    │
│   │   - /webhook/intune  (Graph notifications)         │    │
│   │   - /agent/{id}/next  (agent long-poll)            │    │
│   │   - /agent/{id}/result (result upload)             │    │
│   │   - /api/runs, /api/endpoints, /api/workflows      │    │
│   │   - /ui (web console)                              │    │
│   └──────────────┬─────────────────────────────────────┘    │
│                  │                                            │
│                  ▼                                            │
│   ┌──────────────────────────┐     ┌─────────────────────┐  │
│   │  Background Workers      │     │  Postgres            │  │
│   │  - policy event handler  │◄───►│  - entities          │  │
│   │  - run scheduler         │     │  - job queue         │  │
│   │  - result analyzer       │     │  - time-series       │  │
│   │  - notification sender   │     │    (partitioned)     │  │
│   └──────────────────────────┘     └─────────────────────┘  │
│                                                              │
│   ┌──────────────────────────┐                              │
│   │  Local object storage    │                              │
│   │  (prototype)             │                              │
│   │  S3 in production        │                              │
│   └──────────────────────────┘                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Why this shape

- **FastAPI + Postgres + background workers in one process**: a proven pattern for solo builds. Claude Code writes FastAPI fluently. Postgres as both database and job queue removes an entire category of moving parts (Kafka, Redis, separate queue service).
- **Long-poll agent protocol instead of persistent gRPC streams**: agent makes HTTPS call to `/agent/{id}/next`, server holds for up to 30 seconds returning any pending command. Simple. Works through corporate proxies. Easy to debug.
- **Local object storage first**: the agent uploads screenshots/videos to the cloud, which writes to local disk initially. S3 adapter is a one-file change when you outgrow local disk.
- **No message bus**: background work happens via a Postgres-backed job queue (e.g., `procrastinate` or hand-rolled with `SELECT FOR UPDATE SKIP LOCKED`). Adequate for well past 100 customers.

### 3.3 What this deliberately defers

- Kubernetes, containers beyond a single Dockerfile
- Kafka, Redis, Vault
- mTLS between agent and cloud (shared-secret bearer tokens in v1, mTLS before first external customer)
- Multi-tenant data isolation at the row-level (single-tenant first; multi-tenant uses the same schema with a tenant_id added and RLS enabled before shipping to second customer)
- LLM-based vision fallback (rule-based retry only in v1)
- LLM-based failure explanation (simple error-code lookup table in v1)

Each of these is additive later. None of them require rewriting the product.

---

## 4. Tech Stack

| Layer | Choice | Why | Upgrade path |
|-------|--------|-----|--------------|
| Agent language | Python 3.12 | Claude Code is fluent; automation libraries are mature; single-binary packaging via PyInstaller works for Windows | Rewrite agent in Go or Rust if/when perf or footprint becomes an issue post-PMF |
| Cloud language | Python 3.12 (FastAPI) | Same codebase, shared models | Same |
| Database | Postgres 16 | Handles metadata, job queue, and time-series data (partitioned tables) | Add TimescaleDB extension for metrics; shard later |
| Object store | Local filesystem → S3 | Interface-based, swap when needed | One-line swap |
| Windows UI automation | `pywinauto` (UIA backend) + Playwright (for browser) | pywinauto is Python-native, handles Outlook/Teams; Playwright for web | Add vision-model fallback later |
| Config | Pydantic Settings + `.env` | Simple, typed | Same |
| Background jobs | Postgres-backed queue (`procrastinate`) | No extra infra | Same for a long time |
| Deployment (cloud) | Single Dockerfile, deploy to Fly.io or Railway | Cheap, fast, easy | K8s if we grow that much |
| Agent packaging | PyInstaller → signed .exe | Standard Python-to-Windows-binary path | Same or Go rewrite |
| Monitoring | structlog + Sentry | Easy setup, good enough | Add Prometheus+Grafana later |
| Tests | pytest, playwright for integration | Standard Python stack | Same |

### 4.1 One notable choice to flag

Python for the agent is a compromise. It's the right choice *for a prototype built with Claude Code*. It's the wrong choice for a production agent that needs to run on 10,000 customer endpoints — Python's startup time, footprint, and dependency management are painful at that scale. Rewriting the agent in Go is a real future task. I'm explicit about this so you don't discover it later and feel like you made a mistake. You didn't. The prototype agent's job is to prove the product works, not to scale.

---

## 5. Repository Structure

```text
sentinel/
├── README.md
├── pyproject.toml
├── docker-compose.yml              # postgres for local dev
├── Dockerfile.cloud
├── Dockerfile.agent                # Windows build image
│
├── libs/
│   └── sentinel_shared/            # models, protocols, workflow schema
│       ├── models.py               # Pydantic models shared by agent + cloud
│       ├── workflow_schema.py      # workflow JSON structure
│       └── protocol.py             # agent↔cloud message types
│
├── cloud/
│   ├── app.py                      # FastAPI app entry
│   ├── routes/
│   │   ├── agent.py                # agent endpoints (next, result, register)
│   │   ├── webhooks.py             # Intune webhook receiver
│   │   ├── api.py                  # UI-facing REST API
│   │   └── ui.py                   # web console (htmx or Next.js later)
│   ├── workers/
│   │   ├── policy_event_handler.py # consumes webhook events, decides what to run
│   │   ├── scheduler.py            # queues workflow commands for agents
│   │   ├── analyzer.py             # processes results, baseline comparison
│   │   └── notifier.py             # sends Slack/email notifications
│   ├── db/
│   │   ├── schema.sql
│   │   ├── migrations/             # alembic
│   │   └── queries.py
│   ├── integrations/
│   │   ├── intune.py               # Graph API client, webhook auth
│   │   ├── slack.py
│   │   └── email.py
│   └── tests/
│
├── agent/
│   ├── main.py                     # agent entry
│   ├── transport.py                # long-poll client to cloud
│   ├── executor.py                 # runs a workflow from JSON
│   ├── actions/
│   │   ├── app.py                  # launch_app, wait_for_element, etc.
│   │   ├── browser.py              # Playwright-backed web actions
│   │   ├── email.py                # Outlook-specific actions
│   │   ├── network.py              # VPN, DNS, HTTP checks
│   │   └── __init__.py             # action registry
│   ├── capture.py                  # screenshots, video, logs
│   ├── self_heal.py                # retry logic, later: vision fallback
│   └── tests/
│
├── workflows/                      # JSON workflow library, version-controlled
│   ├── std-outlook-auth-v1.json
│   ├── std-vpn-connect-v1.json
│   └── std-sso-login-v1.json
│
└── scripts/
    ├── dev_up.sh                   # local postgres + cloud + agent
    ├── build_agent.ps1             # Windows build
    └── seed_demo.py                # seeds demo tenant, endpoint, workflows
```

### 5.1 Why this structure

- `libs/sentinel_shared` is the contract between cloud and agent. Models, schemas, message types all live here. Both sides import from it. Nothing in this module has side effects.
- `cloud/` and `agent/` each depend on `libs/sentinel_shared` but not on each other. This is the architectural seam that will later become two separate repos or two separate deploy targets if needed.
- Workflows are data, not code. They live in `/workflows` as JSON files and get loaded into the database on startup. This is the thing that makes standard workflows upgradeable without agent releases.

---

## 6. Core Data Model

Single tenant for now. Every table gets a `tenant_id` column added when we go multi-tenant — schema is designed to accommodate this cleanly.

```sql
-- Reference endpoints registered and managed by this Sentinel instance
CREATE TABLE endpoints (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname        TEXT NOT NULL,
    os_platform     TEXT NOT NULL CHECK (os_platform IN ('windows','macos','ios','android')),
    os_version      TEXT NOT NULL,
    mdm_platform    TEXT NOT NULL CHECK (mdm_platform IN ('intune','jamf')),
    mdm_device_id   TEXT NOT NULL,
    registration_token_hash TEXT,   -- one-time token hashed at rest
    bearer_token_hash TEXT,         -- ongoing auth token, rotated
    agent_version   TEXT,
    last_heartbeat  TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'provisioning',  -- provisioning|active|offline|retired
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (mdm_platform, mdm_device_id)
);

-- Workflow definitions, loaded from /workflows JSON files
CREATE TABLE workflows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT NOT NULL UNIQUE,            -- 'std-outlook-auth'
    version         INT NOT NULL,
    name            TEXT NOT NULL,
    platform        TEXT[] NOT NULL,                 -- ['windows']
    definition      JSONB NOT NULL,                  -- full workflow JSON
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (slug, version)
);

-- Raw policy deployment events from MDM webhooks
CREATE TABLE policy_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mdm_platform    TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    policy_name     TEXT NOT NULL,
    policy_type     TEXT NOT NULL,
    target_groups   TEXT[] NOT NULL,
    deployed_by     TEXT,
    deployed_at     TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_payload     JSONB NOT NULL,
    processed_at    TIMESTAMPTZ
);

-- A Run = one workflow suite execution on one endpoint, usually triggered by a policy event
CREATE TABLE runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id     UUID NOT NULL REFERENCES endpoints(id),
    trigger_type    TEXT NOT NULL,       -- 'policy_event'|'manual'|'scheduled'
    policy_event_id UUID REFERENCES policy_events(id),
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued|running|complete|timed_out|failed
    aggregate_result TEXT,                -- pass|fail|degraded (null until complete)
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_runs_endpoint_status ON runs(endpoint_id, status) WHERE status != 'complete';

-- Per-workflow result within a Run
CREATE TABLE workflow_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    workflow_id     UUID NOT NULL REFERENCES workflows(id),
    result          TEXT NOT NULL,        -- pass|fail|degraded
    duration_ms     INT,
    failure_reason  TEXT,
    failure_details JSONB,
    artifact_paths  TEXT[],                -- paths in object store
    metrics         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Time-series metrics, partitioned by month for easy retention
CREATE TABLE workflow_metrics (
    time            TIMESTAMPTZ NOT NULL,
    workflow_id     UUID NOT NULL,
    os_platform     TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           DOUBLE PRECISION NOT NULL
) PARTITION BY RANGE (time);

-- Agent command queue: the cloud writes here, agent long-polls
CREATE TABLE agent_commands (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id     UUID NOT NULL REFERENCES endpoints(id),
    command_type    TEXT NOT NULL,        -- 'run_workflow'|'heartbeat_ack'|'config_update'
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',   -- pending|delivered|acked|expired
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_agent_commands_pending ON agent_commands(endpoint_id, status) WHERE status = 'pending';

-- Background job queue managed by procrastinate; schema provided by library
```

### 6.1 Notes

- `endpoints` carries both MDM identity and Sentinel identity. One-time registration tokens bootstrap the trust; ongoing bearer tokens rotate.
- `agent_commands` is deliberately simple. The agent's long-poll reads from this with `SELECT ... FOR UPDATE SKIP LOCKED`, marks delivered, and returns the command. No Kafka, no Redis, no pub/sub.
- Partitioning `workflow_metrics` by month sets up for clean retention (drop old partitions) and a future migration to Timescale hypertables.

---

## 7. Agent Protocol

### 7.1 Registration (one-time)

```text
POST /agent/register
Body: { registration_token, hostname, os_platform, os_version, mdm_device_id }
Response: { endpoint_id, bearer_token }
```

Registration token is generated by an admin in the cloud console, printed to the admin, and entered on the endpoint at first boot. Single-use, 24-hour expiry. Bearer token returned is stored in the Windows Credential Manager on the endpoint and used for all subsequent calls.

### 7.2 Command poll

```text
GET /agent/{endpoint_id}/next
Header: Authorization: Bearer <token>
(long-poll up to 30s)

Response (command available):
{
  "command_id": "...",
  "command_type": "run_workflow",
  "payload": { "workflow_id": "...", "workflow_def": {...}, "run_id": "...", "timeout_s": 180 }
}

Response (no command):
204 No Content
```

Agent loops: poll → execute → report → poll. When idle, the 30-second long-poll keeps the agent present but cheap.

### 7.3 Result upload

```text
POST /agent/{endpoint_id}/result
Body: {
  "run_id": "...",
  "workflow_id": "...",
  "result": "pass|fail|degraded",
  "duration_ms": 4212,
  "failure_reason": "...",
  "metrics": { "launch_time_ms": 3400, "auth_time_ms": 812 }
}

// Artifacts uploaded separately
POST /agent/{endpoint_id}/artifact
Multipart: artifact_type, run_id, workflow_id, file
Response: { "artifact_path": "..." }
```

### 7.4 Heartbeat

```text
POST /agent/{endpoint_id}/heartbeat
Body: { agent_version, os_version, resource_stats }
```

Every 5 minutes. Updates `last_heartbeat`. Endpoints with no heartbeat for 15 minutes are marked `offline`.

---

## 8. Workflow Definition and Execution

### 8.1 Workflow JSON (example)

```json
{
  "slug": "std-outlook-auth",
  "version": 1,
  "name": "Outlook Authentication",
  "platform": ["windows"],
  "timeout_seconds": 180,
  "steps": [
    {
      "id": "launch",
      "action": "launch_app",
      "params": { "windows_path": "outlook.exe" },
      "capture_metric": "launch_time_ms",
      "timeout_seconds": 30
    },
    {
      "id": "wait_inbox",
      "action": "wait_for_element",
      "params": {
        "backend": "uia",
        "selector": { "control_type": "List", "name": "Inbox" },
        "timeout_seconds": 60
      },
      "capture_metric": "inbox_load_ms"
    },
    {
      "id": "send_test",
      "action": "compose_email",
      "params": {
        "to": "{{TEST_EMAIL_RECIPIENT}}",
        "subject": "Sentinel test {{RUN_ID}}",
        "body": "automated"
      }
    },
    {
      "id": "verify_delivery",
      "action": "verify_email_received",
      "params": {
        "mailbox": "{{TEST_EMAIL_RECIPIENT}}",
        "subject_contains": "Sentinel test {{RUN_ID}}",
        "timeout_seconds": 120
      },
      "capture_metric": "end_to_end_delivery_ms"
    }
  ],
  "retry": { "on_failure": "once" }
}
```

### 8.2 Action registry

In `agent/actions/__init__.py`, a registry maps `action` names to Python functions. Each function has the signature:

```python
def action_fn(params: dict, context: ExecutionContext) -> ActionResult: ...
```

New actions are added by writing a function and registering it. Claude Code can add actions without touching the executor or schema.

### 8.3 Executor loop

```python
async def execute_workflow(wf: WorkflowDef, ctx: ExecutionContext) -> WorkflowResult:
    ctx.log.info("workflow.start", workflow=wf.slug)
    for step in wf.steps:
        result = await run_step(step, ctx)
        if not result.ok:
            if wf.retry.on_failure == "once" and not ctx.already_retried:
                ctx.already_retried = True
                return await execute_workflow(wf, ctx.reset())
            await ctx.capture_failure_artifacts(step, result)
            return WorkflowResult(status="fail", failed_step=step.id, reason=result.reason)
        ctx.record_metric(step, result)
    return WorkflowResult(status="pass", metrics=ctx.metrics)
```

Intentionally boring. Predictable. Testable.

### 8.4 Variable substitution

`{{TEST_EMAIL_RECIPIENT}}` and similar placeholders are filled at run-time from endpoint-scoped secrets fetched via a separate endpoint (`GET /agent/{id}/secrets`). Secrets are never stored in the workflow JSON or in Run records.

---

## 9. Intune Integration

The Intune integration is the single most important connector in v1, so I'll be specific.

### 9.1 Webhook subscription (Microsoft Graph change notifications)

Microsoft Graph supports change notifications for device management resources. The subscription is created by the cloud via the Graph API at tenant onboarding:

```text
POST https://graph.microsoft.com/v1.0/subscriptions
{
  "changeType": "updated",
  "notificationUrl": "https://sentinel.example.com/webhook/intune",
  "resource": "/deviceManagement/deviceConfigurations",
  "expirationDateTime": "2026-05-01T00:00:00Z",
  "clientState": "<tenant-scoped-secret>"
}
```

Graph subscriptions are short-lived (max ~3 days for most resources) and must be renewed. A background job renews them daily.

### 9.2 Resources to subscribe to

v1 subscribes to changes on:
- `deviceConfigurations` — configuration profiles
- `deviceCompliancePolicies` — compliance policies
- `mobileAppAssignments` — app deployments
- `deviceManagementScripts` — platform scripts (Windows)

v2 adds Conditional Access, update rings, and enrollment profiles.

### 9.3 Webhook receiver behavior

```python
@router.post("/webhook/intune")
async def intune_webhook(request: Request):
    body = await request.json()
    # Validate clientState matches tenant secret
    # Verify validationToken if Graph is doing subscription handshake
    for notification in body.get("value", []):
        event = normalize_intune_notification(notification)
        await db.insert_policy_event(event)
        await enqueue("handle_policy_event", event.id)
    return Response(status_code=202)
```

Return within 3 seconds always. Do the actual work in the background.

### 9.4 Polling fallback

A background job runs every 60 seconds and queries `deviceConfigurations` for items with `lastModifiedDateTime` since last check. If a notification was missed, polling backfills. This is the safety net that lets us trust we won't miss a deployment.

### 9.5 Graph API auth

Standard client credentials flow with an app registration in the customer's Entra tenant. Permissions needed:
- `DeviceManagementConfiguration.Read.All`
- `DeviceManagementApps.Read.All`
- `DeviceManagementManagedDevices.Read.All`

These are read-only. Sentinel never mutates the customer's MDM state.

### 9.6 Determining affected endpoints

When a policy event arrives, we need to know which reference endpoints are affected:

```python
async def affected_endpoints(event: PolicyEvent) -> list[Endpoint]:
    # For each target_group in the policy assignment,
    # query Graph for members of that group
    # Intersect with known reference endpoints
    target_mdm_ids = set()
    for group_id in event.target_groups:
        members = await intune.get_group_members(group_id)
        target_mdm_ids.update(m.device_id for m in members)
    return await db.endpoints_by_mdm_id(target_mdm_ids)
```

This is an expensive call and gets cached for 5 minutes per group.

---

## 10. Windows Agent Details

### 10.1 Runtime model

- Runs as a Windows Service (uses `pywin32` for service wrapper)
- Service runs as LocalSystem but spawns workflow execution processes into the logged-in user session via `CreateProcessAsUser`
- Workflow execution processes run as the test user account, not as SYSTEM
- Separation matters: Outlook, Teams, and most real apps only work in a user session with a visible desktop

### 10.2 UI automation backends

- **Primary: `pywinauto` with UIA backend.** Works for modern Windows apps, accessibility-first, scriptable from Python.
- **Secondary: Playwright for browser interactions.** Handles Edge and Chrome well, including SSO flows and SAML redirects.
- **Tertiary (v2): Vision fallback.** When a selector fails, send screenshot + step intent to a vision LLM, get pixel coordinates, click those. Deferred to later iteration.

### 10.3 Artifact capture

- Screenshot at every step transition (full desktop)
- Continuous video capture during workflow, retained only if workflow fails (rolling 60-second buffer)
- Windows Event Log excerpt (last 5 minutes of System and Application logs) captured on failure
- Agent log (last 500 lines) attached to every failure result

### 10.4 Packaging

- PyInstaller builds a single `sentinel-agent.exe`
- Code-signed with an EV certificate (you'll need to buy one; ~$300-500/year)
- MSI wrapper built with WiX for clean install/uninstall
- Initial distribution: manually install on your own reference VMs. MDM-driven deployment is a v2 concern.

### 10.5 Install footprint

- `C:\Program Files\Sentinel\` for binary
- `C:\ProgramData\Sentinel\` for config, logs, state
- Service name: `SentinelAgent`
- Network: outbound HTTPS only, no inbound listener

---

## 11. Cloud Service Details

### 11.1 FastAPI app layout

Standard FastAPI app with router composition. Async everywhere. `uvicorn` as the ASGI server.

Auth on agent endpoints: bearer token in header, validated against `endpoints.bearer_token_hash`. Auth on UI/API endpoints: session cookie for the prototype, OAuth/SSO later.

### 11.2 Background workers

Using `procrastinate` (Postgres-backed, Python-native job queue):
- `handle_policy_event(event_id)` — decides which endpoints + workflows to run, creates Run records, queues commands
- `check_run_timeout(run_id)` — scheduled 15 minutes after Run start, marks timed out if incomplete
- `renew_graph_subscriptions()` — daily, renews Intune subscriptions
- `poll_intune_changes()` — every 60 seconds, fallback polling
- `compute_baselines()` — hourly, recomputes rolling baselines per workflow

Workers run in-process with the API in the prototype. Split into separate processes when scale demands it. `procrastinate` supports both.

### 11.3 Web console

Prototype: server-rendered Jinja + htmx. Adequate for a dozen screens. No JavaScript framework needed.

Screens needed in v1:
- Login
- Endpoint list (status, last heartbeat, OS)
- Workflow list (active, version)
- Run history (filter by endpoint, by status, by policy)
- Run detail (per-workflow results, artifacts, failure explanation)
- Policy event log
- Settings (Intune connection, Slack webhook, notification routing)

If and when the console grows past what htmx comfortably supports, migrate to Next.js. The FastAPI API is already there.

### 11.4 Notifications (v1 simple)

Slack incoming webhook per configured channel. On Run complete, post a message:

```text
:white_check_mark: Run complete on endpoint WIN11-TEST-01
Policy: CA-BlockNonCompliant-v3 (Microsoft Entra)
Workflows: 3 passed, 0 failed, 0 degraded
Duration: 4m 12s
Details: https://sentinel.example.com/runs/<id>
```

Failed runs get `:x:` and a brief failure summary. Email is the same content via SMTP.

---

## 12. Security (Prototype Adequate, Production-Ready)

| Concern | v1 Approach | Production Evolution |
|---------|-------------|---------------------|
| Agent auth | Bearer tokens (Argon2-hashed at rest), rotated every 30 days | mTLS with customer-scoped client certs |
| Cloud auth | Session cookie + password | SSO via WorkOS/Auth0, MFA required |
| Secrets storage | Encrypted fields in Postgres using `cryptography.fernet` + env-provided key | HashiCorp Vault or cloud KMS |
| Transport | TLS 1.3 everywhere; HSTS; no HTTP allowed | Same + mTLS for agent |
| Artifact redaction | Rule-based regex scrubbing for common patterns (SSN, credit card, email) | Computer-vision redaction of password fields in screenshots |
| Audit log | Append-only Postgres table, every admin action logged | Same + SIEM forwarding |
| Agent code signing | Required before any external install | Same |
| Pen test | Skip for prototype | Required before first paying customer |
| SOC 2 | Skip for prototype | Type I before GA, Type II within 12 months |

The principle: we don't ship insecure code, but we don't over-engineer security for a system that isn't yet talking to customers. Every shortcut above has a clear upgrade path.

---

## 13. Testing Strategy

### 13.1 Unit tests
- Every action in `agent/actions/` has unit tests with mocked UI automation
- Every service in `cloud/workers/` has unit tests with mocked DB
- Every API route has unit tests with `httpx.AsyncClient`
- Target: 80%+ coverage on `libs/sentinel_shared` and workers, 60%+ elsewhere

### 13.2 Integration tests
- Cloud: spin up ephemeral Postgres, run full request flow
- Agent: spin up test Windows VM via Vagrant/Packer, run real workflows against a sandbox Entra tenant with test users

### 13.3 End-to-end test suite
- "Deploy a policy, observe a run, verify notification" — driven by Playwright against a real Intune sandbox tenant
- Runs nightly in CI
- Failures block release

### 13.4 Claude Code test discipline
- Every feature PR includes tests Claude Code generates alongside the feature
- Test files live next to code files (`foo.py`, `test_foo.py`)
- Running `pytest` is the first thing you do when a feature feels done. If it's not green, it's not done.

---

## 14. Observability

### 14.1 Logging
- `structlog` configured JSON output
- Every log line has: `timestamp`, `level`, `service`, `run_id` (when applicable), `endpoint_id` (when applicable), `event`, plus event-specific fields
- Rotating file in dev, stdout in production (containers)

### 14.2 Error tracking
- Sentry for exceptions (free tier adequate for prototype)
- Every unhandled exception hits Sentry with full context

### 14.3 Metrics
- Prometheus instrumentation via `prometheus_client`, scraped by Fly metrics or Grafana Cloud free tier
- Key metrics: runs started/completed/failed, policy events received, agent heartbeat latency, workflow duration p50/p95

### 14.4 Agent observability
- Agent ships its own logs on request (debug endpoint)
- Agent logs last 1000 lines to local file, rotates at 10MB
- Failure artifacts always include recent agent logs

---

## 15. Deployment

### 15.1 Local dev
- `docker compose up` brings up Postgres
- `uvicorn cloud.app:app --reload` runs cloud with hot reload
- `python -m agent.main` runs agent locally (on a Windows VM)

### 15.2 Cloud deployment (prototype)
- Single `Dockerfile.cloud`
- Deploy to Fly.io or Railway for ~$20-40/month
- Postgres: managed via Fly Postgres or Neon (free tier)
- Local filesystem for artifacts in v1; add S3 when usage grows

### 15.3 Agent deployment (prototype)
- Build MSI locally, install manually on test VMs
- For first paying customer, provide signed MSI for their EUC team to push via Intune

---

## 16. Phased Build Plan (Realistic for Claude Code + You)

Each phase is roughly a week of focused work. Given your bandwidth (10-15 hrs/week), scale each phase to 2-4 calendar weeks.

### Phase 0 — Foundation
- Repo, pyproject, CI, basic Dockerfile
- Postgres schema and migrations
- `libs/sentinel_shared` with models and message types
- FastAPI app skeleton with health check
- One end-to-end test: POST a fake policy event, see it in the DB

### Phase 1 — Agent MVP (no workflows yet)
- Agent binary that registers, polls, heartbeats
- One dummy command ("ping") that agent executes and reports back
- End-to-end demo: cloud tells agent to ping, agent responds, run completes

### Phase 2 — First real workflow
- Action registry
- Three actions: `launch_app`, `wait_for_element`, `capture_screenshot`
- First workflow: launch Notepad, wait for it, screenshot, close. Trivial but real.
- Run this workflow on command from cloud, see results in DB

### Phase 3 — Intune webhook + run triggering
- Graph subscription and webhook handler
- Policy event → affected endpoints → Run → agent command → result
- Manually create an Intune policy, watch the flow fire

### Phase 4 — Real workflows
- Add actions for SSO login (Playwright), Outlook automation, VPN connect
- Build out three production workflows: Identity, Email, VPN
- Baseline computation and Degraded detection

### Phase 5 — Notifications and console
- Slack integration
- Web console for Runs, Endpoints, Workflows
- Failure artifacts viewable in console

### Phase 6 — Polish and scale to a design partner
- Error tracking, monitoring, metrics
- Documentation
- Packaging for deployment to a design partner's environment

### Roadmap after v1
- Phase 7: macOS agent + Jamf integration
- Phase 8: iOS/Android via Intune mobile
- Phase 9: Vision-model self-healing
- Phase 10: LLM failure explanations
- Phase 11: Multi-tenant isolation
- Phase 12: SOC 2 Type I

---

## 17. How to Work with Claude Code on This

A few practical notes since Claude Code is the builder.

### 17.1 Scope a session tightly
Each Claude Code session should produce one coherent thing: "implement the action registry," "add the Intune webhook handler," "wire the workflow JSON loader." Don't ask for "phase 3" in one shot. Claude Code works better when the unit of work fits in a few hundred lines.

### 17.2 Write the interface first
For each component, write the Python module's docstring and function signatures first (or have Claude Code draft them from this doc). Review and commit. Then have Claude Code fill in the implementation. This keeps the architecture consistent.

### 17.3 Commit early and often
Small commits. Claude Code can lose track of intent in a large branch. Frequent commits give you clean rollback points.

### 17.4 Tests first when practical
"Write the tests for this module based on the design doc, then implement until they pass." This is a forcing function that surfaces ambiguity in the spec.

### 17.5 The things you still do
- Buy the code signing certificate
- Register the Azure app and grant Graph permissions
- Stand up the Windows reference VM
- Test workflows manually before trusting automation
- Decide when "good enough" is good enough
- Talk to prospective design partners
- Make the architectural calls that this doc didn't predetermine

---

## 18. Open Questions

Things to resolve as you build, not before.

1. **Video capture overhead.** Continuous recording of a Windows desktop is not free. May need to drop to screenshot-only during workflows, full video only on failure replay.
2. **pywinauto reliability on Windows 11 24H2 and beyond.** Known edge cases with Fluent UI controls. May need MS UIA COM interop for some apps.
3. **Graph API throttling.** Large tenants can hit 429s. Need exponential backoff and per-tenant rate limiting.
4. **MSI vs. MSIX packaging.** MSIX is the modern path but has install-path restrictions that complicate background service model. Stick with MSI for v1.
5. **Secrets for test accounts.** A dedicated Entra service account per workflow? Service principals? User accounts with app passwords? Needs a decision before running real SSO workflows.

---

*End of design doc v0.2.*
