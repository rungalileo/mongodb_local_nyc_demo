#!/usr/bin/env python3
"""
Galileo Session Metrics Fetcher

This module provides functions to fetch and parse session metrics from the Galileo API.
"""

import os
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_project_id(project_name: str, api_key: Optional[str] = None, 
                   api_url: Optional[str] = None) -> str:
    """
    Get project ID from project name.
    
    Args:
        project_name (str): The project name
        api_key (str, optional): Galileo API key. If not provided, uses GALILEO_API_KEY env var
        api_url (str, optional): Galileo API URL. If not provided, uses GALILEO_API_URL env var
        
    Returns:
        str: Project ID
        
    Raises:
        ValueError: If project not found or required parameters are missing
        requests.RequestException: If API request fails
    """
    # Get API key and URL from parameters or environment
    if api_key is None:
        api_key = os.environ.get("GALILEO_API_KEY")
    if api_url is None:
        api_url = os.environ.get("GALILEO_API_URL")
    
    if not api_key:
        raise ValueError("GALILEO_API_KEY is required")
    if not api_url:
        raise ValueError("GALILEO_API_URL is required")
    
    # Construct API URL for projects search
    url = f"{api_url}/v2/projects/paginated"
    headers = {"Galileo-API-Key": api_key}
    
    # Search for project by name
    payload = {
        "filters": [
            {
                "name": "name",
                "operator": "eq",
                "value": project_name,
                "case_sensitive": False
            }
        ]
    }
    
    # Make API request
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    projects = data.get("projects", [])
    if not projects:
        raise ValueError(f"Project '{project_name}' not found")
    
    return projects[0]["id"]


def fetch_session_data(project_id: str, session_id: str, api_key: Optional[str] = None, 
                      api_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch raw session data from Galileo API.
    Documentation: https://v2docs.galileo.ai/api-reference/trace/get-session
    
    Args:
        project_id (str): The Galileo project ID
        session_id (str): The Galileo session ID
        api_key (str, optional): Galileo API key. If not provided, uses GALILEO_API_KEY env var
        api_url (str, optional): Galileo API URL. If not provided, uses GALILEO_API_URL env var
        
    Returns:
        Dict[str, Any]: Raw session data from API
        
    Raises:
        ValueError: If required parameters are missing
        requests.RequestException: If API request fails
    """
    # Get API key and URL from parameters or environment
    if api_key is None:
        api_key = os.environ.get("GALILEO_API_KEY")
    if api_url is None:
        api_url = os.environ.get("GALILEO_API_URL")
    
    if not api_key:
        raise ValueError("GALILEO_API_KEY is required")
    if not api_url:
        raise ValueError("GALILEO_API_URL is required")
    
    # Construct API URL
    url = f"{api_url}/v2/projects/{project_id}/sessions/{session_id}"
    headers = {"Galileo-API-Key": api_key}
    
    # Make API request
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_all_metrics(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract all metrics from session data at all levels.
    
    Args:
        session_data (Dict[str, Any]): Raw session data from API
        
    Returns:
        Dict[str, Any]: Organized metrics data
    """
    metrics_data = {
        'session_metrics': {},
        'trace_metrics': [],
        'span_metrics': [],
        'metric_info': {},
        'raw_data': session_data
    }
    
    # Extract session-level metrics
    session_metrics = session_data.get('metrics', {})
    if session_metrics:
        metrics_data['session_metrics'] = session_metrics
    
    # Extract metric_info
    metric_info = session_data.get('metric_info', {})
    if metric_info:
        metrics_data['metric_info'] = metric_info
    
    # Extract trace-level metrics
    traces = session_data.get('traces', [])
    for i, trace in enumerate(traces):
        trace_metrics = trace.get('metrics', {})
        if trace_metrics:
            metrics_data['trace_metrics'].append({
                'trace_index': i,
                'trace_id': trace.get('id'),
                'trace_type': trace.get('type'),
                'metrics': trace_metrics
            })
        
        # Extract span-level metrics
        spans = trace.get('spans', [])
        for j, span in enumerate(spans):
            span_metrics = span.get('metrics', {})
            if span_metrics:
                metrics_data['span_metrics'].append({
                    'trace_index': i,
                    'span_index': j,
                    'span_id': span.get('id'),
                    'span_type': span.get('type'),
                    'metrics': span_metrics
                })
    
    return metrics_data


def print_metrics_summary(metrics_data: Dict[str, Any]) -> None:
    """
    Print a simplified summary of metrics for demo purposes.
    
    Args:
        metrics_data (Dict[str, Any]): Organized metrics data
    """
    print("\n" + "="*50)
    print("GALILEO SESSION METRICS")
    print("="*50)
    print("\n")
    
    # Show session metrics
    session_metrics = metrics_data.get('session_metrics', {})
    if session_metrics:
        print("\n📊 SESSION METRICS:")
        for key, value in session_metrics.items():
            print(f"  {key}: {value}")
    
    # Show trace metrics (simplified)
    trace_metrics = metrics_data.get('trace_metrics', [])
    if trace_metrics:
        print(f"\n🔍 TRACE METRICS ({len(trace_metrics)} traces):")
        for trace in trace_metrics:
            print(f"  Trace {trace['trace_index'] + 1}:")
            for key, value in trace['metrics'].items():
                print(f"    {key}: {value}")
    
    # Show span metrics (simplified)
    span_metrics = metrics_data.get('span_metrics', [])
    if span_metrics:
        print(f"\n⚡ SPAN METRICS ({len(span_metrics)} spans):")
        for i, span in enumerate(span_metrics):
            print(f"  {span['span_type'].upper()} Span:")
            for key, value in span['metrics'].items():
                print(f"    {key}: {value}")
            # Add empty line between spans (except for the last one)
            if i < len(span_metrics) - 1:
                print()


def get_session_metrics(session_id: str, project_id: Optional[str] = None, 
                       project_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get session metrics (simplified for demo - no polling).
    
    Args:
        session_id (str): The Galileo session ID
        project_id (str, optional): The Galileo project ID. If not provided, uses GALILEO_PROJECT_ID env var
        project_name (str, optional): The Galileo project name. If not provided, uses GALILEO_PROJECT env var
        
    Returns:
        Dict[str, Any]: Organized metrics data
    """
    if project_id is None:
        # Try to get project ID from environment variable first
        project_id = os.environ.get("GALILEO_PROJECT_ID")
        
        # If not found, try to get project ID from project name
        if not project_id:
            if project_name is None:
                project_name = os.environ.get("GALILEO_PROJECT")
            
            if project_name:
                project_id = get_project_id(project_name)
            else:
                raise ValueError("Either GALILEO_PROJECT_ID or GALILEO_PROJECT environment variable is required")
    
    session_data = fetch_session_data(project_id, session_id)
    return extract_all_metrics(session_data)


# Example usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python fetch_session_metrics.py <session_id>")
        sys.exit(1)
    
    session_id = sys.argv[1]
    
    try:
        metrics_data = get_session_metrics(session_id)
        print_metrics_summary(metrics_data)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
