#!/usr/bin/env python3
"""
Register the AI Ops Desk agent with Agent Control and create a control that
denies any refund whose returned amount is 0.

Prerequisites:
    1. Agent Control server running (default http://localhost:8000):

        curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml | docker compose -f - up -d

    2. SDK installed: pip install -r requirements.txt

Usage:
    python setup_agent_control.py
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import sys
from datetime import datetime, UTC

from agent_control import AgentControlClient


# Hard-coded so a shell-level AGENT_CONTROL_AGENT_NAME (e.g. set for the
# Cursor IDE hook at ~/.cursor/hooks/ac_evaluate.py, which defaults to
# "cursor-agent") cannot accidentally redirect this demo's controls onto a
# different agent.
AGENT_NAME = "ai-ops-desk"
AGENT_DESCRIPTION = "AI Ops Desk multi-agent customer support demo"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# Creating/attaching controls is an admin-scoped operation on the AC server.
# We deliberately read a separate ADMIN key here so this script can be run
# against a prod server without leaking the admin credential into the
# long-running SDK process (which only ever needs the lower-privilege
# AGENT_CONTROL_API_KEY).
ADMIN_API_KEY = (
    os.getenv("AGENT_CONTROL_ADMIN_API_KEY")
    # Fall back to the SDK key for local dev where auth is usually disabled
    # and a single key (or none) is in use.
    or os.getenv("AGENT_CONTROL_API_KEY")
    or None
)

# Catalog of controls this script manages. Re-running is idempotent: if a
# control already exists (409) we look up its id and PATCH the definition so
# this file remains the source of truth.
CONTROLS: dict[str, dict] = {
    # 1. Defensive guardrail: never confirm a $0 refund.
    "block-zero-refund": {
        "description": (
            "Block create_refund_request tool calls whose returned amount is 0. "
            "A zero-dollar refund usually means the agent could not look up the "
            "original transaction and is about to confirm a useless refund to "
            "the customer."
        ),
        "enabled": True,
        "execution": "server",
        # Stage = post: evaluate the *output* of the wrapped function.
        # step_types = ["llm"]: the @control() decorator auto-classifies
        # plain async functions as llm steps. (Switch to ["tool"] if you
        # wrap a framework tool object instead.)
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {
                "name": "json",
                "config": {
                    # JSON evaluator matches when constraints FAIL, which
                    # then triggers the deny action below.
                    "field_constraints": {
                        "amount": {"min": 0.01},
                    },
                },
            },
        },
        "action": {"decision": "deny"},
        "tags": ["refund", "tool-output", "ai-ops-desk"],
    },
    # 2. Refund-compliance: the refund amount must match the receipt amount.
    # The ai-ops-desk agent computes ``amount_matches_receipt`` on each
    # create_refund_request output by comparing the refund amount to the
    # underlying order's total. When the agent uses a stale or fallback
    # amount, the boolean flips to False and this control denies the call.
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
                    # enum=[True] -> any other value (False, missing) FAILS
                    # the constraint, which is what triggers the deny.
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


async def _register_agent(client: AgentControlClient) -> None:
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


async def _upsert_control(client: AgentControlClient, name: str, definition: dict) -> int:
    """Create the control or, if it already exists, refresh its definition."""
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


async def _attach_control(client: AgentControlClient, name: str, control_id: int) -> None:
    response = await client.http_client.post(
        f"/api/v1/agents/{AGENT_NAME}/controls/{control_id}"
    )
    if response.status_code in (200, 201, 204, 409):
        print(f"✓ Control '{name}' (id={control_id}) associated with agent '{AGENT_NAME}'")
        return
    response.raise_for_status()


async def main() -> int:
    print(f"Agent Control server: {SERVER_URL}")
    print(f"Agent name:           {AGENT_NAME}")
    print(f"Controls:             {', '.join(CONTROLS.keys())}")
    print(f"Admin API key:        {'set (' + ADMIN_API_KEY[:4] + '…)' if ADMIN_API_KEY else 'not set (auth disabled)'}")
    print()

    async with AgentControlClient(base_url=SERVER_URL, api_key=ADMIN_API_KEY) as client:
        try:
            health = await client.health_check()
        except Exception as e:
            print(f"✗ Could not reach Agent Control server at {SERVER_URL}: {e}")
            print("  Start it with the docker-compose command from the README.")
            return 1
        print(f"✓ Server healthy: {health.get('status', 'unknown')}\n")

        await _register_agent(client)
        for name, definition in CONTROLS.items():
            control_id = await _upsert_control(client, name, definition)
            await _attach_control(client, name, control_id)

    print("\nDone. Run a scenario to see the controls in action:")
    print("  python main.py --index 0")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
