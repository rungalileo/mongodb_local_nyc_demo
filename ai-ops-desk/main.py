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
import os
import sys
from typing import Dict, Any
from dotenv import load_dotenv


# Initialize Galileo BEFORE importing modules that use @log decorators
try:
    from galileo import galileo_context
    
    # Get configuration from environment variables
    project_name = os.getenv('GALILEO_PROJECT', 'ai_ops_desk')
    log_stream = os.getenv('GALILEO_LOG_STREAM', 'dev-1')
    
    # Initialize Galileo context
    galileo_context.init(project=project_name, log_stream=log_stream)
    print(f"✅ Galileo initialized - Project: {project_name}, Log Stream: {log_stream}")
except ImportError:
    print("⚠️  Galileo SDK not installed. Logging will be disabled.")
except Exception as e:
    print(f"⚠️  Failed to initialize Galileo: {e}. Logging will be disabled.")

# Now import modules that use @log decorators
from app.graph import create_ops_desk_graph
from app.toggles import ToggleManager


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
    
    # Define scenario-specific queries
    queries = {
        "refund_bluetooth_earbuds": {
            "user_query": "I need a refund for my bluetooth electronics purchase, I don't like the product",
            "user_id": "user_001",
        }, 
        "refund_dryer": {
            "user_query": "I need a refund for my dryer purchase, I accidentally bought it in the wrong size",
            "user_id": "user_002",
        }
    }
    
    if scenario not in queries:
        raise ValueError(f"Unknown scenario: {scenario}. Available: {list(queries.keys())}")
    
    query = queries[scenario]
    
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
        "--scenario", 
        choices=["refund_bluetooth_earbuds", "refund_dryer"],
        default="refund_bluetooth_earbuds",
        help="Test scenario to run"
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
        # Run the scenario
        result = await run_scenario(args.scenario, toggles_provided)
        
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
            print(f"\n✅ Scenario '{args.scenario}' completed successfully!")
            return 0
        else:
            print(f"\n❌ Scenario '{args.scenario}' failed!")
            return 1
            
    except Exception as e:
        print(f"\n❌ Error running scenario '{args.scenario}': {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
