#!/bin/bash

# Check if start and end indices are provided
if [ $# -ne 2 ]; then
    echo "Usage: $0 <start_index> <end_index>"
    echo "Example: $0 0 5"
    echo "Example: $0 6 6"
    exit 1
fi

START_INDEX=$1
END_INDEX=$2

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
    python main.py --index $i
    echo ""
done

echo "All scenarios completed!"
