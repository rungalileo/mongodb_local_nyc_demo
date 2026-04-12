"""CRM Ops Desk — CLI entry point with Galileo SDK instrumentation."""

from __future__ import annotations

import asyncio
import os

from colorama import Fore, Style, init as colorama_init
from dotenv import load_dotenv
from galileo import galileo_context
from galileo.handlers.langchain import GalileoAsyncCallback

from app.graph import build_graph

load_dotenv()
colorama_init(autoreset=True)


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


async def run_scenario(scenario_name: str, *, drift: bool = False) -> dict:
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

    with galileo_context(
        project=os.environ["GALILEO_PROJECT"],
        log_stream=os.environ.get("GALILEO_LOG_STREAM", "default"),
    ):
        callback = GalileoAsyncCallback()
        result = await graph.ainvoke(
            {
                "user_query": query["user_query"],
                "user_id": query["user_id"],
                "scenario": scenario_name,
            },
            config={"callbacks": [callback]},
        )

    # Display result
    print(f"\n{'=' * 60}")
    print(f"{Fore.MAGENTA}RESULT{Style.RESET_ALL}")
    print(f"{'=' * 60}")

    audit = result.get("audit_output", {})
    if audit:
        print(f"\n{Fore.WHITE}{audit.get('rationale', 'No rationale')}{Style.RESET_ALL}\n")

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
    args = parser.parse_args()

    scenario_names = list(SCENARIOS.keys())
    asyncio.run(run_scenario(scenario_names[args.index], drift=args.drift))


if __name__ == "__main__":
    main()
