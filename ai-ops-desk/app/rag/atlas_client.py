from __future__ import annotations

import os

from pymongo import MongoClient
from pymongo.server_api import ServerApi

_mongo_client: MongoClient | None = None


def get_db():
    """Return the ai_ops_desk database, creating the client on first call."""
    global _mongo_client
    if _mongo_client is None:
        uri = os.environ["MONGODB_URI"]
        _mongo_client = MongoClient(uri, server_api=ServerApi("1"))
        _mongo_client.admin.command("ping")
    return _mongo_client.ai_ops_desk


def embed(texts: list[str]) -> list[list[float]]:
    """Generate embeddings via OpenAI."""
    import openai

    client = openai.OpenAI()
    resp = client.embeddings.create(input=texts, model="text-embedding-3-small")
    return [d.embedding for d in resp.data]
