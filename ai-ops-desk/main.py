"""CRM Ops Desk — CLI entry point with Galileo SDK instrumentation."""

from __future__ import annotations

import asyncio
import os
import uuid

from colorama import Fore, Style, init as colorama_init
from dotenv import load_dotenv
from galileo import galileo_context
from galileo.handlers.langchain import GalileoAsyncCallback
from langchain_core.messages import HumanMessage
from opentelemetry import trace

from app.graph import build_graph

load_dotenv()
colorama_init(autoreset=True)

tracer = trace.get_tracer("crm-ops-desk", "0.1.0")


SCENARIOS = {
    "refund_bluetooth_earbuds": {
        "user_query": "I need a refund for my bluetooth electronics purchase, I don't like the product",
        "user_id": "user_001",
    },
    "refund_dryer": {
        "user_query": "I'm SICK OF ORDERING EVERYTHING and RETURNING EVERYTHING. Y'all aren't a good company. refund my tablet",
        "user_id": "user_002",
    },
    "refund_gaming_mouse": {
        "user_query": "My gaming mouse is broken, the scroll wheel stopped working after just a few days",
        "user_id": "user_003",
    },
    "refund_air_purifier": {
        "user_query": "I want to return my air purifier, I changed my mind about needing it",
        "user_id": "user_004",
    },
    "refund_coffee_maker": {
        "user_query": "My coffee maker stopped working, it won't heat water anymore",
        "user_id": "user_005",
    },
    "refund_speakers": {
        "user_query": "I'm not happy with my speaker system, the sound quality is not what I expected",
        "user_id": "user_006",
    },
    "enquire_status_of_order": {
        "user_query": "Was my costume delivered?",
        "user_id": "user_007",
    },
}


async def run_scenario(scenario_name: str, *, drift: bool = False, http_root: bool = False) -> dict:
    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {list(SCENARIOS.keys())}")

    if drift:
        os.environ["POLICY_FORCE_OLD_VERSION"] = "true"

    query = SCENARIOS[scenario_name]
    graph = build_graph()

    print(f"\n{'=' * 60}")
    print(f"{Fore.MAGENTA}SCENARIO: {scenario_name.upper()}{Style.RESET_ALL}")
    print(f"{'=' * 60}")
    print(f"User: {query['user_id']}")
    print(f"Query: {Fore.RED}{query['user_query']}{Style.RESET_ALL}")
    print(f"{'=' * 60}\n")

    session_id = f"session-{scenario_name}-{uuid.uuid4().hex[:8]}"

    invoke_input = {
        "user_query": query["user_query"],
        "user_id": query["user_id"],
        "scenario": scenario_name,
        # Seed the messages list so SDOT captures the user query
        # as gen_ai.input.messages on the root GenAI span.
        "messages": [HumanMessage(content=query["user_query"])],
    }

    with galileo_context(
        project=os.environ["GALILEO_PROJECT"],
        log_stream=os.environ.get("GALILEO_LOG_STREAM", "default"),
    ):
        callback = GalileoAsyncCallback()

        if http_root:
            # Optional HTTP root span simulates a web server request.
            # This ensures all child spans (LangGraph, pymongo, openai)
            # land on the same trace.  The auto-inferred GenAI
            # invoke_agent span (created by SDOT) sits below this.
            with tracer.start_as_current_span(
                f"POST /api/v1/chat/{scenario_name}",
                kind=trace.SpanKind.SERVER,
                attributes={
                    "http.method": "POST",
                    "http.route": f"/api/v1/chat/{scenario_name}",
                    "http.target": f"/api/v1/chat/{scenario_name}",
                    "http.scheme": "https",
                    "http.host": "crm-ops-desk.internal",
                    "user.id": query["user_id"],
                    "session.id": session_id,
                    "scenario": scenario_name,
                },
            ) as root_span:
                result = await graph.ainvoke(
                    invoke_input,
                    config={"callbacks": [callback]},
                )
                resolution = result.get("action_output", {}).get("resolution", "unknown")
                status_code = 200 if result.get("status") != "error" else 500
                root_span.set_attribute("http.status_code", status_code)
                root_span.set_attribute("crm.resolution", resolution)
                root_span.set_attribute("crm.status", result.get("status", "unknown"))
        else:
            result = await graph.ainvoke(
                invoke_input,
                config={"callbacks": [callback]},
            )

    # Display result
    print(f"\n{'=' * 60}")
    print(f"{Fore.MAGENTA}RESULT{Style.RESET_ALL}")
    print(f"{'=' * 60}")

    # User-facing summary (from summarize agent)
    summary = result.get("summary", "")
    if summary:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}Reply to customer:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{summary}{Style.RESET_ALL}\n")

    audit = result.get("audit_output", {})
    if audit:
        print(f"{Fore.BLUE}Audit: {audit.get('rationale', 'No rationale')}{Style.RESET_ALL}\n")

    action = result.get("action_output", {})
    if action:
        print(f"{Fore.GREEN}Actions Taken:{Style.RESET_ALL}")
        for receipt in action.get("tool_receipts", []):
            icon = "+" if 200 <= receipt["status"] < 300 else "x"
            print(f"  {icon} {receipt['tool'].replace('_', ' ').title()}")

        print(f"\n{Fore.GREEN}Resolution: {action.get('resolution', '?')}{Style.RESET_ALL}")

    print(f"\nStatus: {result.get('status', 'unknown').upper()}")
    print(f"{'=' * 60}\n")
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="CRM Ops Desk — LangGraph + Galileo SDK demo")
    parser.add_argument(
        "--index", type=int, default=0,
        choices=range(len(SCENARIOS)),
        help="Scenario index (0-6)",
    )
    parser.add_argument("--drift", action="store_true", help="Force expired policy (drift mode)")
    parser.add_argument("--http-root", action="store_true", help="Add a simulated HTTP server root span")
    args = parser.parse_args()

    scenario_names = list(SCENARIOS.keys())
    asyncio.run(run_scenario(scenario_names[args.index], drift=args.drift, http_root=args.http_root))


if __name__ == "__main__":
    main()
