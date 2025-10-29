# AI Customer Service Operations Desk - Multi-Agent Demo
4 Agent System who's purpose is to respond to customer enquiries, and carry out necessary operations. 


A sophisticated multi-agent AI system for handling customer service operations including refund requests, support tickets, and policy management.


<img src="image.png" alt="Multi-Agent Flow" width="600"/>



## Scenario walk through

The demo includes 7 pre-configured scenarios that test different customer service scenarios:

| Index | Scenario Name | User ID | Description |
|-------|---------------|---------|-------------|
| 0 | `refund_bluetooth_earbuds` | user_001 | Customer requests refund for bluetooth electronics, unsatisfied with product |
| 1 | `refund_dryer` | user_002 | Angry customer with strongly negative sentiment requesting tablet refund |
| 2 | `refund_gaming_mouse` | user_003 | Customer reports broken gaming mouse, defective product case |
| 3 | `refund_air_purifier` | user_004 | Change of mind refund request for air purifier |
| 4 | `refund_coffee_maker` | user_005 | Product malfunction - coffee maker won't heat water |
| 5 | `refund_speakers` | user_006 | Customer dissatisfied with speaker system sound quality |
| 6 | `enquire_status_of_order` | user_007 | Customer inquiry about delivery status (tests LLM hallucination toggle) |

### Running Scenarios

```bash
# Run a specific scenario by index
python main.py --index 0

# Run multiple scenarios
./run_scenarios.sh 0 5

# Run with toggles enabled
python main.py --index 1 --policy-drift
python main.py --index 6 --llm

# Combine multiple flags
./run_scenarios.sh 0 0 --policy-drift --llm
```


## Overview

This demo showcases:
- **Galileo** as an observability and evaluation tool
- **Rag Store** MongoDB Atlas as a RAG store with Vector Search for policy retrieval
- **LLM Use** OpenAI models for LLM operations and embeddings
- **LangGraph** orchestration with 4 specialized agents
- **Other goodies:** Sturctured data models for compliance, sentiment analysis and intent classification

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
- Galileo Account

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
   # Run a specific scenario by index (0-6)
   python main.py --index 0
   
   # Or run a range of scenarios
   ./run_scenarios.sh 0 5
   ```
   
   See the [Scenario walk through](#scenario-walk-through) section above for detailed scenario information and toggle usage.

### Available Toggles

The system includes several toggles for testing different failure scenarios:

- **`--policy-drift`**: Enables policy drift mode where refund determination uses expired policies and only the first policy from the list. When disabled, uses all active policies for refund eligibility checks.
- **`--llm`**: Enables LLM hallucination simulation (currently only active for user_007). When enabled, the system uses `fake_llm_hallucination()` instead of real LLM analysis, simulating incorrect status predictions.
- **`--toggles drift`**: Legacy toggle for policy drift (use `--policy-drift` instead)

All toggles can be set via command-line flags or environment variables (e.g., `POLICY_DRIFT=true`, `LLM_HALLUCINATION=true`).

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