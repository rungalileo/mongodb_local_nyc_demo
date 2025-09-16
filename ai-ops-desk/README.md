# AI Operations Desk - Multi-Agent Demo

A sophisticated multi-agent AI system for handling customer service operations including refund requests, support tickets, and policy management.


<img src="image.png" alt="Multi-Agent Flow" width="600"/>


## Overview

This demo showcases:
- **Galileo** as an observability and evaluation tool
- **MongoDB Atlas** as a RAG store with Vector Search for policy retrieval
- **OpenAI** for LLM operations and embeddings
- **LangGraph** orchestration with 4 specialized agents
- **Other goodies:** Sturctured data models for compliance-y stuff, sentiment analysis and intent classification, the usual

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
   python main.py --scenario refund_bluetooth_earbuds

   # OR to run the scenario by its number

   python main.py --index 0->6
   ```
   We also have a toggle manager to activate different failure states, but more on that later

### Available Toggles
- **drift**: Simulates policy drift by forcing use of expired policies

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