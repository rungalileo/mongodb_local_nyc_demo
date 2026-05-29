#!/usr/bin/env python3
"""
AI Operations Desk - Multi-Agent Customer 360 Demo (CLI entry point)

A production-quality demo showcasing multi-agent AI with MongoDB Atlas RAG
and Galileo SDK for observability, metrics, and guardrails.
"""
from dotenv import load_dotenv
load_dotenv(override=True)

import argparse
import asyncio
import sys
from typing import Any, Dict
from colorama import Fore, Style, init

from app.runner import run_query
from app.scenarios import SCENARIOS
from app.evals import generate_evals_report
from app.agent_control_setup import shutdown_agent_control

# Initialize colorama
init(autoreset=True)


async def run_scenario(scenario: str, toggles_provided: list[str]) -> Dict[str, Any]:
    """Run a specific test scenario via the shared runner."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available: {list(SCENARIOS.keys())}")

    query = SCENARIOS[scenario]

    print(f"\n{'='*60}")
    print(f"{Fore.MAGENTA}SCENARIO: {scenario.upper()}{Style.RESET_ALL}")
    print(f"{'='*60}")
    print(f"User: {query['user_id']}")
    print(f"Query: {Fore.RED}{query['user_query']}{Style.RESET_ALL}")
    print(f"{'='*60}\n")

    result = await run_query(
        user_query=query["user_query"],
        user_id=query["user_id"],
        toggles=toggles_provided,
        scenario=scenario,
    )

    if result.get("galileo_session_id"):
        print(f"{Fore.CYAN}Galileo Session ID: {result['galileo_session_id']}{Style.RESET_ALL}")

    return result


async def main():
    """Entry point"""

    parser = argparse.ArgumentParser(
        description="AI Operations Desk - Multi-Agent Customer 360 Demo",
        epilog="""
            Examples:
            # Run the first scenario (refund_bluetooth_earbuds)
            python main.py

            # Run a scenario by index
            python main.py --index 2

            # Run with drift enabled
            python main.py --index 1 --toggles drift

            Available Scenarios:
            0: refund_bluetooth_earbuds - Wants a refund
            1: refund_dryer - Angry customer
            2: refund_gaming_mouse - Reporting broken mouse
            3: refund_air_purifier - Return air purifier
            4: refund_coffee_maker - Reporting a broken coffee maker
            5: refund_speakers - Not happy with speaker quality
            6: enquire_status_of_order - Asking about costume delivery

            Available Toggles:
            drift - Force old version of policy agent for testing drift detection
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--index",
        type=int,
        choices=list(range(len(SCENARIOS))),
        default=0,
        help="Index of scenario to run (0-6). Default: 0 (refund_bluetooth_earbuds)"
    )
    parser.add_argument(
        "--toggles",
        nargs="+",
        help="Feature toggles to enable. Available: drift (forces old policy version)"
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip fetching and displaying evaluation metrics after workflow completion"
    )
    args = parser.parse_args()

    toggles_provided = args.toggles or []
    try:
        scenario_names = list(SCENARIOS.keys())
        scenario = scenario_names[args.index]

        result = await run_scenario(scenario, toggles_provided)

        # Display final agent response to user
        print(f"\n{'='*60}")
        print(f"{Fore.MAGENTA}AGENT RESPONSE TO USER{Style.RESET_ALL}")
        print(f"{'='*60}")

        if result.get('status') == 'completed' and 'audit_output' in result:
            audit = result['audit_output']

            if audit and hasattr(audit, 'rationale'):
                print(f"\n{Fore.WHITE}{audit.rationale}{Style.RESET_ALL}\n")
            else:
                print(f"\n{Fore.YELLOW}No audit rationale available{Style.RESET_ALL}\n")

            if 'action_output' in result:
                action = result['action_output']
                print(f"{Fore.GREEN}Actions Taken:{Style.RESET_ALL}")
                for receipt in action.tool_receipts:
                    status_icon = "✓" if 200 <= receipt.status < 300 else "✗"
                    tool_name = receipt.tool.replace('_', ' ').title()
                    print(f"  {status_icon} {tool_name}")

                    if receipt.tool == "create_refund_request":
                        refund_id = receipt.response.get("refund_request_id", "unknown")
                        amount = receipt.response.get("amount", 0)
                        currency = receipt.response.get("currency", "USD")
                        print(f"    → Refund Request ID: {refund_id}")
                        print(f"    → Amount: {currency} {amount}")
                    elif receipt.tool == "escalate_ticket":
                        ticket_id = receipt.response.get("ticket_id", "unknown")
                        level = receipt.response.get("escalation_level", "unknown")
                        print(f"    → Ticket ID: {ticket_id}")
                        print(f"    → Escalation Level: {level}")
                    elif receipt.tool in ["create_ticket", "update_ticket"]:
                        ticket_id = receipt.response.get("ticket_id", "unknown")
                        sentiment = receipt.response.get("customer_sentiment", "unknown")
                        print(f"    → Ticket ID: {ticket_id}")
                        print(f"    → Sentiment: {sentiment}")
                    elif receipt.tool == "explain_refund_state":
                        explanation = receipt.response.get("explanation", "")
                        if explanation:
                            print(f"    → {explanation[:150]}{'...' if len(explanation) > 150 else ''}")
                    elif receipt.tool == "explain_order_state":
                        explanation = receipt.response.get("explanation", "")
                        if explanation:
                            print(f"    → {explanation[:150]}{'...' if len(explanation) > 150 else ''}")

                print(f"\n{Fore.GREEN}Final Status: {action.resolution.replace('_', ' ').title()}{Style.RESET_ALL}")

        print(f"\n{'='*60}")
        print(f"SYSTEM STATUS: {result.get('status', 'unknown').upper()}")
        print(f"{'='*60}")

        if 'error' in result:
            print(f"{Fore.RED}Error: {result['error']}{Style.RESET_ALL}")

        if result.get('status') == 'completed':
            print(f"{Fore.GREEN}✓ Scenario completed successfully{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}✗ Scenario failed{Style.RESET_ALL}")
        print(f"{'='*60}\n")

        if not args.skip_metrics:
            session_id = result.get('galileo_session_id')
            generate_evals_report(session_id=session_id, timeout_seconds=60)

    except Exception as e:
        print(f"\n✗ Exception: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await shutdown_agent_control()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
