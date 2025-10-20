#!/usr/bin/env python3
"""
Galileo Logstream Metrics Fetcher

This module provides functions to fetch and parse logstream metrics from the Galileo API.
It allows you to get all metrics for a logstream using just the project name and logstream name.
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


def get_logstream_id(project_id: str, logstream_name: str, api_key: Optional[str] = None, 
                     api_url: Optional[str] = None) -> str:
    """
    Get logstream ID from logstream name.
    
    Args:
        project_id (str): The project ID
        logstream_name (str): The logstream name
        api_key (str, optional): Galileo API key. If not provided, uses GALILEO_API_KEY env var
        api_url (str, optional): Galileo API URL. If not provided, uses GALILEO_API_URL env var
        
    Returns:
        str: Logstream ID
        
    Raises:
        ValueError: If logstream not found or required parameters are missing
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
    
    # Construct API URL for logstreams
    url = f"{api_url}/v2/projects/{project_id}/log_streams"
    headers = {"Galileo-API-Key": api_key}
    
    # Make API request
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    # Find logstream by name
    for logstream in data:
        if logstream.get("name") == logstream_name:
            return logstream["id"]
    
    raise ValueError(f"Logstream '{logstream_name}' not found in project")


def query_traces_by_logstream(project_id: str, logstream_id: str, api_key: Optional[str] = None, 
                              api_url: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """
    Query traces using logstream ID with pagination support.
    
    Args:
        project_id (str): The project ID
        logstream_id (str): The logstream ID
        api_key (str, optional): Galileo API key. If not provided, uses GALILEO_API_KEY env var
        api_url (str, optional): Galileo API URL. If not provided, uses GALILEO_API_URL env var
        limit (int): Maximum number of records per page
        
    Returns:
        Dict[str, Any]: All traces data from API (paginated results combined)
        
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
    
    # Construct API URL for traces search
    url = f"{api_url}/v2/projects/{project_id}/traces/search"
    headers = {"Galileo-API-Key": api_key}
    
    all_records = []
    starting_token = 0
    
    while True:
        # Query traces by logstream with pagination
        payload = {
            "log_stream_id": logstream_id,
            "limit": limit,
            "starting_token": starting_token
        }
        
        # Make API request
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Add records to our collection
        records = data.get("records", [])
        all_records.extend(records)
        
        # Check if we have more pages
        next_token = data.get("next_starting_token")
        if next_token is None or len(records) < limit:
            break
            
        starting_token = next_token
    
    # Return combined data
    return {
        "records": all_records,
        "num_records": len(all_records)
    }


def query_spans_by_logstream(project_id: str, logstream_id: str, api_key: Optional[str] = None, 
                            api_url: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """
    Query spans using logstream ID with pagination support.
    
    Args:
        project_id (str): The project ID
        logstream_id (str): The logstream ID
        api_key (str, optional): Galileo API key. If not provided, uses GALILEO_API_KEY env var
        api_url (str, optional): Galileo API URL. If not provided, uses GALILEO_API_URL env var
        limit (int): Maximum number of records per page
        
    Returns:
        Dict[str, Any]: All spans data from API (paginated results combined)
        
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
    
    # Construct API URL for spans search
    url = f"{api_url}/v2/projects/{project_id}/spans/search"
    headers = {"Galileo-API-Key": api_key}
    
    all_records = []
    starting_token = 0
    
    while True:
        # Query spans by logstream with pagination
        payload = {
            "log_stream_id": logstream_id,
            "limit": limit,
            "starting_token": starting_token
        }
        
        # Make API request
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Add records to our collection
        records = data.get("records", [])
        all_records.extend(records)
        
        # Check if we have more pages
        next_token = data.get("next_starting_token")
        if next_token is None or len(records) < limit:
            break
            
        starting_token = next_token
    
    # Return combined data
    return {
        "records": all_records,
        "num_records": len(all_records)
    }


def query_sessions_by_logstream(project_id: str, logstream_id: str, api_key: Optional[str] = None, 
                                api_url: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """
    Query sessions using logstream ID with pagination support.
    
    Args:
        project_id (str): The project ID
        logstream_id (str): The logstream ID
        api_key (str, optional): Galileo API key. If not provided, uses GALILEO_API_KEY env var
        api_url (str, optional): Galileo API URL. If not provided, uses GALILEO_API_URL env var
        limit (int): Maximum number of records per page
        
    Returns:
        Dict[str, Any]: All sessions data from API (paginated results combined)
        
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
    
    # Construct API URL for sessions search
    url = f"{api_url}/v2/projects/{project_id}/sessions/search"
    headers = {"Galileo-API-Key": api_key}
    
    all_records = []
    starting_token = 0
    
    while True:
        # Query sessions by logstream with pagination
        payload = {
            "log_stream_id": logstream_id,
            "limit": limit,
            "starting_token": starting_token
        }
        
        # Make API request
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Add records to our collection
        records = data.get("records", [])
        all_records.extend(records)
        
        # Check if we have more pages
        next_token = data.get("next_starting_token")
        if next_token is None or len(records) < limit:
            break
            
        starting_token = next_token
    
    # Return combined data
    return {
        "records": all_records,
        "num_records": len(all_records)
    }


def format_logstream_metrics_data(sessions_data: Dict[str, Any], traces_data: Dict[str, Any], spans_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format sessions, traces, and spans data into the desired output structure.
    
    Args:
        sessions_data (Dict[str, Any]): Raw sessions data from API
        traces_data (Dict[str, Any]): Raw traces data from API
        spans_data (Dict[str, Any]): Raw spans data from API
        
    Returns:
        Dict[str, Any]: Formatted metrics data
    """
    sessions = []
    sessions_records = sessions_data.get("records", [])
    traces_records = traces_data.get("records", [])
    spans_records = spans_data.get("records", [])
    
    # Group sessions by session ID
    session_groups = {}
    for session in sessions_records:
        session_id = session.get("id")
        if session_id not in session_groups:
            session_groups[session_id] = {
                "session_record": None,
                "traces": [],
                "spans": []
            }
        
        session_groups[session_id]["session_record"] = session
    
    # Group traces by session
    for trace in traces_records:
        session_id = trace.get("session_id")
        if session_id not in session_groups:
            session_groups[session_id] = {
                "session_record": None,
                "traces": [],
                "spans": []
            }
        
        session_groups[session_id]["traces"].append(trace)
    
    # Group spans by session
    for span in spans_records:
        session_id = span.get("session_id")
        if session_id not in session_groups:
            session_groups[session_id] = {
                "session_record": None,
                "traces": [],
                "spans": []
            }
        
        session_groups[session_id]["spans"].append(span)
    
    # Format each session
    for session_id, group in session_groups.items():
        session_data = {
            "id": session_id,
            "metrics": {},
            "traces": []
        }
        
        # Add session-level metrics
        if group["session_record"]:
            session_metrics = group["session_record"].get("metrics", {})
            session_data["metrics"] = session_metrics
        
        # Add traces
        for trace in group["traces"]:
            trace_data = {
                "id": trace.get("id"),
                "parameters": {
                    "input": trace.get("input", ""),
                    "output": trace.get("output", "")
                },
                "metrics": trace.get("metrics", {}),
                "spans": []
            }
            
            # Add spans for this trace
            trace_id = trace.get("id")
            for span in group["spans"]:
                if span.get("trace_id") == trace_id:
                    span_data = {
                        "id": span.get("id"),
                        "name": span.get("name", "unknown"),
                        "metrics": span.get("metrics", {})
                    }
                    trace_data["spans"].append(span_data)
            
            session_data["traces"].append(trace_data)
        
        sessions.append(session_data)
    
    return {"sessions": sessions}


def fetch_logstream_metrics(project_name: Optional[str] = None, logstream_name: Optional[str] = None,
                           api_key: Optional[str] = None, api_url: Optional[str] = None,
                           limit: int = 100) -> Dict[str, Any]:
    """
    Fetch all metrics for a logstream using environment variables or provided names.
    
    This is the main function that provides a simple interface to get all metrics
    for a logstream. Uses environment variables GALILEO_PROJECT and GALILEO_LOG_STREAM
    if not provided as parameters.
    
    Args:
        project_name (str, optional): The project name. If not provided, uses GALILEO_PROJECT env var
        logstream_name (str, optional): The logstream name. If not provided, uses GALILEO_LOG_STREAM env var
        api_key (str, optional): Galileo API key. If not provided, uses GALILEO_API_KEY env var
        api_url (str, optional): Galileo API URL. If not provided, uses GALILEO_API_URL env var
        limit (int): Maximum number of records per page (for pagination)
        
    Returns:
        Dict[str, Any]: Formatted metrics data with sessions, traces, and spans in the format:
        {
            "sessions": [
                {
                    "id": "session_1",
                    "metrics": {"m1": 0.5},
                    "traces": [
                        {
                            "id": "trace_1",
                            "parameters": {"input": "value", "output": "value"},
                            "metrics": {"m1": 0.5},
                            "spans": [
                                {
                                    "id": "span_1",
                                    "metrics": {"m1": 0.5}
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        
    Raises:
        ValueError: If project/logstream not found or required parameters are missing
        requests.RequestException: If API request fails
        
    Example:
        >>> # Using environment variables
        >>> metrics_data = fetch_logstream_metrics()
        >>> 
        >>> # Using explicit names
        >>> metrics_data = fetch_logstream_metrics("My Project", "My Logstream")
        >>> print(f"Found {len(metrics_data['sessions'])} sessions")
    """
    # Get project and logstream names from parameters or environment
    if project_name is None:
        project_name = os.environ.get("GALILEO_PROJECT")
    if logstream_name is None:
        logstream_name = os.environ.get("GALILEO_LOG_STREAM")
    
    if not project_name:
        raise ValueError("GALILEO_PROJECT environment variable is required")
    if not logstream_name:
        raise ValueError("GALILEO_LOG_STREAM environment variable is required")
    
    # Get project ID from name
    project_id = get_project_id(project_name, api_key, api_url)
    
    # Get logstream ID from name
    logstream_id = get_logstream_id(project_id, logstream_name, api_key, api_url)
    
    # Query sessions, traces, and spans using logstream ID (with pagination)
    sessions_data = query_sessions_by_logstream(project_id, logstream_id, api_key, api_url, limit)
    traces_data = query_traces_by_logstream(project_id, logstream_id, api_key, api_url, limit)
    spans_data = query_spans_by_logstream(project_id, logstream_id, api_key, api_url, limit)
    
    # Format the data
    return format_logstream_metrics_data(sessions_data, traces_data, spans_data)


# Example usage
if __name__ == "__main__":
    import sys
    import json
    
    # Check if project and logstream names are provided as arguments
    if len(sys.argv) == 3:
        project_name = sys.argv[1]
        logstream_name = sys.argv[2]
        metrics_data = fetch_logstream_metrics(project_name, logstream_name)
    elif len(sys.argv) == 1:
        # Use environment variables
        metrics_data = fetch_logstream_metrics()
    else:
        print("Usage:")
        print("  python fetch_logstream_metrics.py")
        print("  python fetch_logstream_metrics.py <project_name> <logstream_name>")
        print()
        print("Environment variables:")
        print("  GALILEO_PROJECT - The project name")
        print("  GALILEO_LOG_STREAM - The logstream name")
        print("  GALILEO_API_KEY - Your Galileo API key")
        print("  GALILEO_API_URL - The Galileo API URL")
        sys.exit(1)
    
    try:
        # Print JSON output
        print(json.dumps(metrics_data, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
