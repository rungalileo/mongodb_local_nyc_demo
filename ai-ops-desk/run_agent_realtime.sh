#!/bin/bash

# Function to display usage
usage() {
    echo "Usage: $0 --log-stream <log_stream_name>"
    echo ""
    echo "Options:"
    echo "  --log-stream    Log stream name to override the .env file setting"
    echo ""
    echo "Example:"
    echo "  $0 --log-stream realtime-demo-1"
    echo ""
    echo "This script will continuously run random scenarios until you press Ctrl+C"
    exit 1
}

# Parse command line arguments
LOG_STREAM=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --log-stream)
            LOG_STREAM="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Check if log-stream parameter was provided
if [ -z "$LOG_STREAM" ]; then
    echo "Error: --log-stream parameter is required"
    usage
fi

# Get the total number of scenarios (0-6 based on the SCENARIOS dict in main.py)
MAX_SCENARIO_INDEX=6

# Function to handle Ctrl+C
cleanup() {
    echo ""
    echo "=========================================="
    echo "Stopping realtime agent execution..."
    echo "Total scenarios run: $SCENARIO_COUNT"
    echo "=========================================="
    exit 0
}

# Set up trap to catch Ctrl+C
trap cleanup SIGINT

# Initialize counter
SCENARIO_COUNT=0

echo "=========================================="
echo "AI Operations Desk - Realtime Agent Runner"
echo "=========================================="
echo "Log Stream: $LOG_STREAM"
echo "Running scenarios continuously..."
echo "Press Ctrl+C to stop"
echo "=========================================="
echo ""

# Export the log stream environment variable to override .env
export GALILEO_LOG_STREAM="$LOG_STREAM"

# Infinite loop to run scenarios
while true; do
    # Generate random scenario index (0 to MAX_SCENARIO_INDEX)
    RANDOM_INDEX=$((RANDOM % (MAX_SCENARIO_INDEX + 1)))
    
    # Increment counter
    SCENARIO_COUNT=$((SCENARIO_COUNT + 1))
    
    echo "=========================================="
    echo "Scenario #$SCENARIO_COUNT - Running index: $RANDOM_INDEX"
    echo "Log Stream: $LOG_STREAM"
    echo "=========================================="
    
    # Run the scenario
    python main.py --index $RANDOM_INDEX
    
    # Check if the python command failed
    if [ $? -ne 0 ]; then
        echo "⚠️  Scenario $RANDOM_INDEX failed, continuing with next scenario..."
    fi
    
    # Add 1 second delay after each agent run
    echo ""
    echo "✅ Agent run completed..."
    sleep 1
    echo ""
done
