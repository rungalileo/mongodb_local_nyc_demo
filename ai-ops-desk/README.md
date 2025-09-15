# AI Operations Desk - Multi-Agent Demo

A sophisticated multi-agent AI system for handling customer service operations including refund requests, support tickets, and policy management.

## Overview

This demo showcases:
- **MongoDB Atlas** as a RAG store with Vector Search for policy retrieval
- **OpenAI** for LLM operations and embeddings
- **LangGraph** orchestration with 4 specialized agents
- **Structured data models** for orders, refund requests, and support tickets
- **LLM-based intent classification** and sentiment analysis

## Architecture

### Agents
- **PolicyAgent (A1)**: Retrieves relevant policies using vector search
- **RecordsAgent (A3)**: Aggregates user's refund requests and support tickets
- **ActionAgent (A5)**: Executes tools based on user intent and sentiment
- **AuditAgent (A7)**: Provides comprehensive rationale and audit trail

### Data Models
- **Orders**: Product purchases with shipping details
- **Refund Requests**: Financial transactions for returns
- **Support Tickets**: Customer service interactions with sentiment tracking
- **Policies**: Versioned policy documents with effective dates

### Tools Available
- Create/Update support tickets
- Escalate tickets (for negative sentiment)
- Create refund requests
- Explain refund request status

## Prerequisites

- Python 3.11+
- MongoDB Atlas connection string
- OpenAI API key

## Quickstart

1. **Create and activate virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp env.example .env
   # Edit .env with your MongoDB URI and OpenAI API key
   ```

4. **Set up data**
   ```bash
   python setup_policies.py
   python setup_orders.py
   python setup_refund_requests.py
   python setup_tickets.py
   ```

5. **Run scenarios**
   ```bash
   # Happy path scenario
   python main.py --scenario refund_bluetooth_earbuds
   
   # Policy drift scenario (uses expired policies)
   python main.py --scenario refund_bluetooth_earbuds --toggles drift
   ```

## Configuration

### Environment Variables
- `MONGODB_URI`: MongoDB Atlas connection string
- `OPENAI_API_KEY`: OpenAI API key for LLM operations
- `MONGODB_DATABASE`: Database name (default: ai_ops_desk)

### Feature Toggles
- `POLICY_FORCE_OLD_VERSION`: Force use of expired policies for drift simulation (enabled in "drift" scenario)
- `REFUND_API_ERROR_RATE`: Simulate API failures (0.0-1.0)

### Scenarios
- **refund_bluetooth_earbuds**: Customer requesting refund for bluetooth earbuds

### Available Toggles
- **drift**: Simulates policy drift by forcing use of expired policies

### Usage Examples
```bash
# Normal operation
python main.py --scenario refund_bluetooth_earbuds

# With policy drift
python main.py --scenario refund_bluetooth_earbuds --toggles drift

# Multiple toggles (comma-separated)
python main.py --scenario refund_bluetooth_earbuds --toggles drift,other_toggle
```

## Data Setup

The system includes comprehensive setup scripts:

- **`setup_policies.py`**: Creates policy documents with vector embeddings
- **`setup_orders.py`**: Populates order data for 2 users
- **`setup_refund_requests.py`**: Creates refund request records
- **`setup_tickets.py`**: Generates support ticket data with sentiment

Each script clears existing data before uploading new records.

## Key Features

### LLM-Based Classification
- **Intent Classification**: Uses OpenAI to determine user intent (refund, inquiry, general)
- **Sentiment Analysis**: Analyzes customer sentiment for ticket prioritization

### Policy Management
- **Vector Search**: Semantic similarity search for policy retrieval
- **Version Control**: Policies with effective_from and effective_until dates
- **Drift Simulation**: Can force use of expired policies for testing

### Data Consistency
- **Linked Records**: Orders, refund requests, and tickets are cross-referenced
- **User Consistency**: Same user IDs across all data collections
- **Status Tracking**: Comprehensive status tracking for all entities

## File Structure

```
ai-ops-desk/
├── app/
│   ├── agents/           # Agent implementations
│   ├── models/           # Pydantic data models
│   ├── rag/             # MongoDB Atlas integration
│   └── llm/             # OpenAI client
├── setup_*.py           # Data setup scripts
├── main.py              # Entry point
└── requirements.txt     # Dependencies
```

## Troubleshooting

- **MongoDB Connection**: Ensure your IP is whitelisted in Atlas
- **OpenAI API**: Verify your API key has sufficient credits
- **Vector Search**: Ensure the `policy_vectors` index is created in Atlas
- **Data Issues**: Run setup scripts to refresh data

## Development

The codebase uses:
- **Pydantic** for data validation and serialization
- **LangGraph** for agent orchestration
- **MongoDB Atlas** for data persistence and vector search
- **OpenAI** for LLM operations