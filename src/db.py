"""
Thin Postgres connection helper for the FastAPI service (src/api.py).

Deliberately not a connection pool or ORM - this is a small local demo
service, not production traffic. One connection per request is simple,
correct, and easy to reason about; add pooling only if this ever needs to
handle real concurrent load.
"""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection() -> psycopg.Connection:
    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL is not set. Copy .env.example to .env and fill it in.")
    return psycopg.connect(db_url)
