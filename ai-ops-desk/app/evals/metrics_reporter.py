"""
Metrics Reporter for Galileo Evals

Fetches and displays evaluation metrics after agent workflow completion.
Polls for metrics with timeout and displays them in a formatted report.
"""

import time
import os
from typing import Dict, Any, Optional, List
from colorama import Fore, Style
from fetch_logstream_metrics import fetch_logstream_metrics


def should_display_metric(value: Any) -> bool:
    """
    Determine if a metric should be displayed.

    Args:
        value: Metric value

    Returns:
        True if metric should be displayed, False otherwise
    """
    # Filter out None and "not_applicable"
    if value is None:
        return False

    if isinstance(value, str) and value.lower() == "not_applicable":
        return False

    return True


def count_total_metrics(metrics_data: Dict[str, Any]) -> int:
    """
    Count total number of displayable metrics across all sessions, traces, and spans.
    Excludes None and "not_applicable" values.

    Args:
        metrics_data: Metrics data in logstream format

    Returns:
        Total count of displayable metrics
    """
    total = 0
    sessions = metrics_data.get('sessions', [])

    for session in sessions:
        # Count session metrics
        session_metrics = session.get('metrics', {})
        total += len([v for v in session_metrics.values() if should_display_metric(v)])

        # Count trace metrics
        traces = session.get('traces', [])
        for trace in traces:
            trace_metrics = trace.get('metrics', {})
            total += len([v for v in trace_metrics.values() if should_display_metric(v)])

            # Count span metrics
            spans = trace.get('spans', [])
            for span in spans:
                span_metrics = span.get('metrics', {})
                total += len([v for v in span_metrics.values() if should_display_metric(v)])

    return total


def poll_for_metrics(project_name: Optional[str] = None,
                    logstream_name: Optional[str] = None,
                    timeout_seconds: int = 60,
                    poll_interval_seconds: int = 2) -> Dict[str, Any]:
    """
    Poll for metrics until they are calculated or timeout is reached.

    Args:
        project_name: Galileo project name (optional, will use env var if not provided)
        logstream_name: Galileo logstream name (optional, will use env var if not provided)
        timeout_seconds: Maximum time to wait for metrics (default: 60)
        poll_interval_seconds: Time between polling attempts (default: 2)

    Returns:
        Dict with metrics data from the logstream
    """
    start_time = time.time()
    last_metrics_count = 0

    print(f"{Fore.CYAN}⏳ Waiting for metrics to calculate (timeout: {timeout_seconds}s)...{Style.RESET_ALL}")

    while True:
        elapsed = time.time() - start_time

        if elapsed >= timeout_seconds:
            print(f"{Fore.YELLOW}⚠️  Timeout reached after {timeout_seconds}s{Style.RESET_ALL}")
            break

        try:
            # Fetch metrics from logstream
            metrics_data = fetch_logstream_metrics(project_name, logstream_name)

            # Count total metrics available across all sessions
            total_metrics = count_total_metrics(metrics_data)

            # Check if we have new metrics
            if total_metrics > last_metrics_count:
                last_metrics_count = total_metrics

            # If we have metrics, wait a bit more to ensure all are calculated
            # then return
            if total_metrics > 0 and elapsed >= 5:  # Wait at least 5 seconds
                print(f"{Fore.GREEN}✓ Metrics ready after {elapsed:.1f}s{Style.RESET_ALL}")
                return metrics_data

        except Exception as e:
            print(f"{Fore.YELLOW}  Polling error: {e}{Style.RESET_ALL}")

        # Wait before next poll
        time.sleep(poll_interval_seconds)

    # Return whatever we have after timeout
    try:
        return fetch_logstream_metrics(project_name, logstream_name)
    except Exception as e:
        print(f"{Fore.RED}Failed to fetch final metrics: {e}{Style.RESET_ALL}")
        return {'sessions': []}


def format_metric_name(name: str) -> str:
    """
    Format metric name for display (convert snake_case to Title Case).

    Args:
        name: Metric name in snake_case

    Returns:
        Formatted metric name
    """
    # Handle special cases
    special_cases = {
        'policy_drift': 'Policy Drift',
        'context_adherence': 'Context Adherence',
        'pii_detection': 'PII Detection',
        'toxicity': 'Toxicity',
        'prompt_injection': 'Prompt Injection',
    }

    if name in special_cases:
        return special_cases[name]

    # Default: convert snake_case to Title Case
    return name.replace('_', ' ').title()


def format_metric_value(value: Any, metric_name: str = "") -> str:
    """
    Format metric value for display.

    Args:
        value: Metric value (can be float, int, bool, string, etc.)
        metric_name: Name of the metric (used to determine formatting)

    Returns:
        Formatted string representation
    """
    if value is None:
        return "N/A"

    if isinstance(value, bool):
        return "✓" if value else "✗"

    if isinstance(value, float):
        # Special handling for specific metric types
        metric_lower = metric_name.lower()

        # Cost metrics should show as dollar amounts
        if "cost" in metric_lower:
            return f"${value:.4f}"

        # Count/number metrics should show as integers or plain numbers
        if any(word in metric_lower for word in ["num", "number", "count", "duration", "latency"]):
            if value == int(value):  # If it's a whole number
                return str(int(value))
            return f"{value:.2f}"

        # Rate/percentage metrics (between 0-1) should show as percentage
        if 0 <= value <= 1 and any(word in metric_lower for word in ["rate", "score", "accuracy", "precision", "recall"]):
            return f"{value:.2%}"

        # For other floats, use appropriate precision
        if value == int(value):  # If it's a whole number
            return str(int(value))
        elif abs(value) < 0.01:  # Very small numbers
            return f"{value:.6f}"
        else:
            return f"{value:.4f}"

    if isinstance(value, (int, str)):
        # Truncate rationale metrics to 200 characters
        if isinstance(value, str) and "rationale" in metric_name.lower():
            if len(value) > 200:
                return value[:200] + "..."
        return str(value)

    # For complex types, use repr
    return repr(value)


def print_metrics_report(metrics_data: Dict[str, Any]) -> None:
    """
    Print a minimal formatted evaluation metrics report.

    Args:
        metrics_data: Metrics data from fetch_logstream_metrics (should contain 1 session)
    """
    sessions = metrics_data.get('sessions', [])

    if not sessions:
        print(f"{Fore.YELLOW}No sessions found with metrics{Style.RESET_ALL}")
        return

    # Get the first session (should only be one after filtering)
    session = sessions[0]
    session_id = session.get('id', 'unknown')
    session_metrics = session.get('metrics', {})
    traces = session.get('traces', [])

    # Separate metrics by level
    session_metrics_display = {}
    trace_metrics_display = {}
    span_metrics_display = {}

    # Add session metrics
    displayable_session_metrics = {k: v for k, v in session_metrics.items() if should_display_metric(v)}
    for metric_name, value in displayable_session_metrics.items():
        if metric_name not in session_metrics_display:
            session_metrics_display[metric_name] = []
        session_metrics_display[metric_name].append(value)

    # Collect trace and span metrics
    all_spans = []
    for trace in traces:
        trace_metrics = trace.get('metrics', {})
        displayable_trace_metrics = {k: v for k, v in trace_metrics.items() if should_display_metric(v)}
        for metric_name, value in displayable_trace_metrics.items():
            if metric_name not in trace_metrics_display:
                trace_metrics_display[metric_name] = []
            trace_metrics_display[metric_name].append(value)

        spans = trace.get('spans', [])
        all_spans.extend(spans)
        for span in spans:
            span_metrics = span.get('metrics', {})
            displayable_span_metrics = {k: v for k, v in span_metrics.items() if should_display_metric(v)}
            for metric_name, value in displayable_span_metrics.items():
                if metric_name not in span_metrics_display:
                    span_metrics_display[metric_name] = []
                span_metrics_display[metric_name].append(value)

    if not session_metrics_display and not trace_metrics_display and not span_metrics_display:
        print(f"{Fore.YELLOW}No metrics available{Style.RESET_ALL}")
        return

    # Print compact header
    print(f"\n{Fore.MAGENTA}METRICS [{session_id[:8]}...] {len(traces)}T {len(all_spans)}S{Style.RESET_ALL}")

    # Helper to format metric line
    def format_metric_line(metric_name: str, values: List[Any]) -> str:
        formatted_name = format_metric_name(metric_name)

        # Check if values are numeric for aggregation
        numeric_values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]

        if numeric_values and len(numeric_values) == len(values):
            # Aggregate numeric metrics
            avg_val = sum(numeric_values) / len(numeric_values)
            min_val = min(numeric_values)
            max_val = max(numeric_values)

            formatted_avg = format_metric_value(avg_val, metric_name)
            if min_val != max_val and len(values) > 1:
                formatted_min = format_metric_value(min_val, metric_name)
                formatted_max = format_metric_value(max_val, metric_name)
                return f"{formatted_name:.<30} {formatted_avg} ({formatted_min}-{formatted_max})"
            else:
                return f"{formatted_name:.<30} {formatted_avg}"
        else:
            # For non-numeric values, show the value if uniform
            if len(set(str(v) for v in values)) == 1:
                formatted_val = format_metric_value(values[0], metric_name)
                return f"{formatted_name:.<30} {formatted_val}"
            else:
                return f"{formatted_name:.<30} [mixed values: {len(values)}]"

    # Print session metrics
    if session_metrics_display:
        print(f"{Fore.CYAN}Session:{Style.RESET_ALL}")
        for metric_name in sorted(session_metrics_display.keys()):
            print(f"  {format_metric_line(metric_name, session_metrics_display[metric_name])}")

    # Print trace metrics
    if trace_metrics_display:
        print(f"{Fore.CYAN}Traces:{Style.RESET_ALL}")
        for metric_name in sorted(trace_metrics_display.keys()):
            print(f"  {format_metric_line(metric_name, trace_metrics_display[metric_name])}")

    # Print span metrics
    if span_metrics_display:
        print(f"{Fore.CYAN}Spans:{Style.RESET_ALL}")
        for metric_name in sorted(span_metrics_display.keys()):
            print(f"  {format_metric_line(metric_name, span_metrics_display[metric_name])}")


def filter_metrics_by_session(metrics_data: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """
    Filter metrics data to only include the specified session.

    Args:
        metrics_data: Full metrics data from logstream
        session_id: Session ID to filter for

    Returns:
        Filtered metrics data with only the specified session
    """
    sessions = metrics_data.get('sessions', [])

    for session in sessions:
        if session.get('id') == session_id:
            return {'sessions': [session]}

    # Session not found
    return {'sessions': []}


def generate_evals_report(session_id: Optional[str] = None, timeout_seconds: int = 60) -> None:
    """
    Main function to generate evaluation metrics report.
    Fetches metrics from the logstream, polls until ready, and prints report.

    Args:
        session_id: Optional Galileo session ID to filter for (shows only this session's metrics)
        timeout_seconds: Maximum time to wait for metrics (default: 60)
    """
    try:
        # Get project and logstream info from environment
        project_name = os.environ.get("GALILEO_PROJECT")
        logstream_name = os.environ.get("GALILEO_LOG_STREAM")

        if not project_name:
            print(f"{Fore.RED}✗ GALILEO_PROJECT environment variable not set{Style.RESET_ALL}")
            return

        if not logstream_name:
            print(f"{Fore.RED}✗ GALILEO_LOG_STREAM environment variable not set{Style.RESET_ALL}")
            return

        if session_id:
            print(f"\n{Fore.CYAN}📋 Fetching metrics for session: {session_id}{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.CYAN}📋 Fetching metrics from project: {project_name}, logstream: {logstream_name}{Style.RESET_ALL}")

        # Poll for metrics
        metrics_data = poll_for_metrics(
            project_name=project_name,
            logstream_name=logstream_name,
            timeout_seconds=timeout_seconds
        )

        # Filter by session ID if provided
        if session_id:
            metrics_data = filter_metrics_by_session(metrics_data, session_id)

            if not metrics_data.get('sessions'):
                print(f"{Fore.YELLOW}⚠️  Session {session_id} not found in metrics data{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}    This could mean metrics haven't been calculated yet{Style.RESET_ALL}")
                return

        # Print report
        print_metrics_report(metrics_data)

    except Exception as e:
        print(f"{Fore.RED}✗ Failed to generate metrics report: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
