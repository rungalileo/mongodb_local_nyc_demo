#!/bin/bash

# Check if at least 2 arguments are provided
if [ $# -lt 2 ]; then
    echo "Usage: $0 <start_index> <end_index> [additional_args...]"
    echo "Example: $0 0 5"
    echo "Example: $0 6 6"
    echo "Example: $0 0 2 --policy-drift"
    exit 1
fi

START_INDEX=$1
END_INDEX=$2
# Shift to remove the first two arguments, leaving any additional args
shift 2
ADDITIONAL_ARGS="$@"

# Validate indices
if [ $START_INDEX -gt $END_INDEX ]; then
    echo "Error: Start index ($START_INDEX) cannot be greater than end index ($END_INDEX)"
    exit 1
fi

echo "Running scenarios from index $START_INDEX to $END_INDEX"
echo ""

# Run main.py on the specified range
for i in $(seq $START_INDEX $END_INDEX); do
    echo "=========================================="
    echo "Running scenario index: $i"
    echo "=========================================="
    python main.py --index $i $ADDITIONAL_ARGS
    echo ""
done

echo "All scenarios completed!"
