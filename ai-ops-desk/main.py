#!/usr/bin/env python3
"""
AI Operations Desk - Multi-Agent Customer 360 Demo

A production-quality demo showcasing multi-agent AI with MongoDB Atlas RAG 
and Galileo SDK for observability, metrics, and guardrails.
"""
from dotenv import load_dotenv
load_dotenv()
import argparse
import asyncio
import sys
from typing import Dict, Any

# Now import modules that use @log decorators
from app.graph import create_ops_desk_graph
from app.toggles import ToggleManager

# Define scenario-specific queries
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
    }
}
    
async def run_scenario(scenario: str, toggles_provided: list[str]) -> Dict[str, Any]:
    """Run a specific test scenario"""
    # import pdb;pdb.set_trace()
    # Initialize ToggleManager after parsing arguments
    toggles = ToggleManager()
    
    # Configure toggles based on scenario
    if "drift" in toggles_provided:
        toggles.policy_force_old_version = True
    
    # Create the agent graph
    graph = await create_ops_desk_graph()
    
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available: {list(SCENARIOS.keys())}")
    
    query = SCENARIOS[scenario]
    
    print(f"\n{'='*60}")
    print(f"Running scenario: {scenario.upper()}")
    print(f"Query: {query['user_query']}")
    print(f"User ID: {query['user_id']}")
    print(f"{'='*60}\n")
    
    # Run the graph
    result = await graph.ainvoke({
        "user_query": query["user_query"],
        "user_id": query["user_id"],
        "scenario": scenario
    })
    
    return result


async def main():
    """Main entry point"""

    parser = argparse.ArgumentParser(description="AI Operations Desk Demo")
    parser.add_argument(
        "--index", 
        type=int,
        choices=list(range(len(SCENARIOS))),
        default=0,
        help="Index of scenario to run"
    )
    parser.add_argument(
        "--toggles",
        nargs="+",
        help="Toggles to enable"
    )
    args = parser.parse_args()
    
    
    toggles_provided = []
    if args.toggles:
        toggles_provided = args.toggles
    try:
        # Get scenario by index
        scenario_names = list(SCENARIOS.keys())
        scenario = scenario_names[args.index]
        
        result = await run_scenario(scenario, toggles_provided)
        
        # Print results
        print(f"\n{'='*60}")
        print("FINAL RESULT")
        print(f"{'='*60}")
        print(f"Status: {result.get('status', 'unknown')}")
        
        if 'resolution' in result:
            print(f"Resolution: {result['resolution']}")
        
        if 'error' in result:
            print(f"Error: {result['error']}")
        
        # Success/failure based on status
        if result.get('status') == 'completed':
            print(f"\n✅ Scenario '{scenario}' completed successfully!")
        else:
            print(f"\n❌ Scenario '{scenario}' failed!")
  
    except Exception as e:
        print(f"\n❌ Error running scenario '{scenario}': {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
