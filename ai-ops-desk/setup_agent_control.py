#!/usr/bin/env python3
"""
Agent Control setup for the AI Ops Desk demo.

Dispatches on the AGENT_CONTROL_MODE env var:

  - enterprise (default): VERIFY-only. Controls live in Galileo Console.
    This script:
      * confirms the SDK can authenticate to ACE
      * registers / refreshes the demo agent against the resolved log stream
      * lists the controls bound to that log stream so you can sanity-check them
    Console setup steps:
      1. Console -> Dev Tools -> External Flags -> toggle "Agent Control" on.
      2. Console -> Controls -> Create New Control. Create both:
            - block-zero-refund      (deny on amount<0.01 in create_refund_request output)
            - refund-compliance      (deny on amount_matches_receipt != true)
      3. Open the log stream you set as GALILEO_LOG_STREAM, go to its Controls
         tab, and "Add" each control so they're bound to that log stream.

  - oss: CREATE-and-ATTACH. Talks to a self-hosted Agent Control server,
    registers the demo agent, and upserts the two demo controls (block-zero-refund,
    refund-compliance), attaching each to the agent. Idempotent.

Usage:
    python setup_agent_control.py
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import sys
from datetime import UTC, datetime

import httpx


AGENT_NAME = os.environ.get("AGENT_CONTROL_AGENT_NAME", "ai-ops-desk")
AGENT_DESCRIPTION = "AI Ops Desk multi-agent customer support demo"
SERVER_URL = os.environ.get("AGENT_CONTROL_URL", "").rstrip("/")
TARGET_TYPE = os.environ.get("AGENT_CONTROL_TARGET_TYPE", "log_stream")
API_KEY_HEADER = os.environ.get("AGENT_CONTROL_API_KEY_HEADER", "Galileo-API-Key")
API_KEY = os.environ.get("AGENT_CONTROL_API_KEY") or os.environ.get("GALILEO_API_KEY")

GALILEO_PROJECT = os.environ.get("GALILEO_PROJECT")
GALILEO_LOG_STREAM = os.environ.get("GALILEO_LOG_STREAM")

EXPECTED_CONTROLS = ("block-zero-refund", "refund-compliance")


def _mode() -> str:
    raw = os.environ.get("AGENT_CONTROL_MODE", "enterprise").strip().lower()
    if raw in ("oss", "open-source", "open_source", "standalone", "self-hosted", "self_hosted"):
        return "oss"
    return "enterprise"


def _bail(msg: str) -> int:
    print(f"\033[31m✗ {msg}\033[0m")
    return 1


# =============================================================================
# Enterprise (ACE) flow: verify only.
# =============================================================================

async def _resolve_log_stream() -> tuple[str | None, str | None]:
    if not (GALILEO_PROJECT and GALILEO_LOG_STREAM):
        print("Missing GALILEO_PROJECT or GALILEO_LOG_STREAM.")
        return None, None
    try:
        from galileo.logger.logger import GalileoLogger
    except ImportError as e:
        print(f"galileo SDK is missing GalileoLogger ({e}).")
        return None, None
    gl = GalileoLogger(project=GALILEO_PROJECT, log_stream=GALILEO_LOG_STREAM)
    return gl.project_id, gl.log_stream_id


async def _ent_get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    return await client.get(path, headers={API_KEY_HEADER: API_KEY or ""})


async def _ent_post(client: httpx.AsyncClient, path: str, json: dict) -> httpx.Response:
    return await client.post(path, json=json, headers={API_KEY_HEADER: API_KEY or ""})


async def _run_enterprise() -> int:
    print(f"Mode:                 enterprise (ACE)")
    print(f"Agent Control:        {SERVER_URL}")
    print(f"Auth header:          {API_KEY_HEADER}={'set' if API_KEY else 'MISSING'}")
    print(f"Galileo project:      {GALILEO_PROJECT}")
    print(f"Galileo log stream:   {GALILEO_LOG_STREAM}")
    print(f"Agent:                {AGENT_NAME}")
    print()

    if not SERVER_URL:
        return _bail("AGENT_CONTROL_URL is not set.")
    if not API_KEY:
        return _bail("Neither AGENT_CONTROL_API_KEY nor GALILEO_API_KEY is set.")

    project_id, log_stream_id = await _resolve_log_stream()
    if not log_stream_id:
        return _bail(
            "Could not resolve Galileo log_stream_id. "
            "Check GALILEO_API_URL / GALILEO_API_KEY / GALILEO_PROJECT / GALILEO_LOG_STREAM."
        )
    print(f"✓ Resolved project_id={project_id} log_stream_id={log_stream_id}")

    async with httpx.AsyncClient(base_url=SERVER_URL, timeout=15.0) as client:
        try:
            health = await client.get("/health")
            health.raise_for_status()
            print(f"✓ AC server healthy: {health.json().get('status', 'unknown')}")
        except Exception as e:  # noqa: BLE001
            return _bail(f"AC /health failed: {e}")

        try:
            init_resp = await _ent_post(
                client,
                "/api/v1/agents/initAgent",
                {
                    "agent": {
                        "agent_name": AGENT_NAME,
                        "agent_description": AGENT_DESCRIPTION,
                        "agent_created_at": datetime.now(UTC).isoformat(),
                    },
                    "steps": [],
                    "target_type": TARGET_TYPE,
                    "target_id": log_stream_id,
                },
            )
            init_resp.raise_for_status()
            created = init_resp.json().get("created", False)
            print(f"✓ {'Created' if created else 'Found'} agent '{AGENT_NAME}' on ACE")
        except Exception as e:  # noqa: BLE001
            return _bail(f"initAgent failed: {e}")

        try:
            ctrl_resp = await _ent_get(
                client, f"/api/v1/agents/{AGENT_NAME}/controls"
            )
            ctrl_resp.raise_for_status()
            controls = ctrl_resp.json().get("controls", [])
        except Exception as e:  # noqa: BLE001
            return _bail(f"Listing controls failed: {e}")

        print()
        print(f"Controls bound to {TARGET_TYPE}:{log_stream_id}:")
        if not controls:
            print("  (none)")
        for c in controls:
            print(f"  - {c.get('name')} (id={c.get('id') or c.get('control_id')}, "
                  f"enabled={c.get('enabled', '?')})")

        bound_names = {c.get("name") for c in controls}
        missing = [name for name in EXPECTED_CONTROLS if name not in bound_names]
        if missing:
            print()
            print("\033[33m! Expected controls not bound to this log stream:\033[0m")
            for name in missing:
                print(f"    - {name}")
            print(
                "\n  Create them in Console -> Controls, then attach them to "
                f"the '{GALILEO_LOG_STREAM}' log stream's Controls tab."
            )
            return 2

    print("\nDone. Run a scenario to see the controls in action:")
    print("  python main.py --index 0")
    return 0


# =============================================================================
# OSS flow: register agent + upsert controls + attach controls to agent.
# =============================================================================

# Catalog of controls this script manages in OSS mode. Re-running is
# idempotent: if a control already exists (409) we look up its id and PATCH
# the definition so this file remains the source of truth.
OSS_CONTROLS: dict[str, dict] = {
    "block-zero-refund": {
        "description": (
            "Block create_refund_request tool calls whose returned amount is 0. "
            "A zero-dollar refund usually means the agent could not look up the "
            "original transaction and is about to confirm a useless refund to "
            "the customer."
        ),
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {
                "name": "json",
                "config": {
                    "field_constraints": {
                        "amount": {"min": 0.01},
                    },
                },
            },
        },
        "action": {"decision": "deny"},
        "tags": ["refund", "tool-output", "ai-ops-desk"],
    },
    "refund-compliance": {
        "description": (
            "Refund amount must match the receipt total for the order being "
            "refunded. Triggered when the agent's create_refund_request output "
            "reports amount_matches_receipt=false, which indicates the agent "
            "used a stale, fallback, or otherwise mis-sourced amount."
        ),
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {
                "name": "json",
                "config": {
                    "field_constraints": {
                        "amount_matches_receipt": {"enum": [True]},
                    },
                },
            },
        },
        "action": {"decision": "deny"},
        "tags": ["refund", "compliance", "tool-output", "ai-ops-desk"],
    },
}


async def _run_oss() -> int:
    # OSS uses AGENT_CONTROL_ADMIN_API_KEY for control mgmt if set, else falls
    # back to AGENT_CONTROL_API_KEY (auth disabled / single-key local dev).
    admin_key = (
        os.environ.get("AGENT_CONTROL_ADMIN_API_KEY")
        or os.environ.get("AGENT_CONTROL_API_KEY")
        or None
    )

    print(f"Mode:                 oss (self-hosted)")
    print(f"Agent Control:        {SERVER_URL or 'http://localhost:8000'}")
    print(f"Agent:                {AGENT_NAME}")
    print(f"Admin API key:        {'set' if admin_key else 'not set (auth disabled)'}")
    print(f"Controls:             {', '.join(OSS_CONTROLS.keys())}")
    print()

    server_url = SERVER_URL or "http://localhost:8000"

    try:
        from agent_control import AgentControlClient
    except ImportError as e:
        return _bail(f"agent_control SDK not installed: {e}")

    async with AgentControlClient(base_url=server_url, api_key=admin_key) as client:
        try:
            health = await client.health_check()
        except Exception as e:  # noqa: BLE001
            return _bail(
                f"Could not reach Agent Control server at {server_url}: {e}\n"
                "  Start it with the docker-compose command from the README."
            )
        print(f"✓ Server healthy: {health.get('status', 'unknown')}\n")

        await _oss_register_agent(client)
        for name, definition in OSS_CONTROLS.items():
            control_id = await _oss_upsert_control(client, name, definition)
            await _oss_attach_control(client, name, control_id)

    print("\nDone. Run a scenario to see the controls in action:")
    print("  python main.py --index 0")
    return 0


async def _oss_register_agent(client) -> None:
    response = await client.http_client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {
                "agent_name": AGENT_NAME,
                "agent_description": AGENT_DESCRIPTION,
                "agent_created_at": datetime.now(UTC).isoformat(),
            },
            "steps": [],
        },
    )
    response.raise_for_status()
    created = response.json().get("created", False)
    print(f"{'✓ Created' if created else '✓ Found'} agent: {AGENT_NAME}")


async def _oss_upsert_control(client, name: str, definition: dict) -> int:
    create_response = await client.http_client.put(
        "/api/v1/controls",
        json={"name": name, "data": definition},
    )

    if create_response.status_code == 409:
        list_response = await client.http_client.get("/api/v1/controls")
        list_response.raise_for_status()
        controls = list_response.json().get("controls", [])
        match = next((c for c in controls if c.get("name") == name), None)
        if not match:
            raise RuntimeError(
                f"Server returned 409 for control '{name}' but it was not "
                "found in the controls listing."
            )
        control_id = match.get("id") or match.get("control_id")
        print(f"✓ Control '{name}' already exists (id={control_id}); updating definition…")
        update_response = await client.http_client.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": definition},
        )
        update_response.raise_for_status()
        return int(control_id)

    create_response.raise_for_status()
    control_id = int(create_response.json()["control_id"])
    print(f"✓ Created control '{name}' (id={control_id})")
    return control_id


async def _oss_attach_control(client, name: str, control_id: int) -> None:
    response = await client.http_client.post(
        f"/api/v1/agents/{AGENT_NAME}/controls/{control_id}"
    )
    if response.status_code in (200, 201, 204, 409):
        print(f"✓ Control '{name}' (id={control_id}) associated with agent '{AGENT_NAME}'")
        return
    response.raise_for_status()


# =============================================================================
# Dispatch
# =============================================================================

async def main() -> int:
    if _mode() == "oss":
        return await _run_oss()
    return await _run_enterprise()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
