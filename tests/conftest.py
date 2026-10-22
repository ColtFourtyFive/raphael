"""Test settings are fixed before anything reads them (settings are cached)."""

import os

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://atp:atp@localhost:5432/atp_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["WORKER_ACK_WAIT_S"] = "3"
os.environ["WORKER_MAX_DELIVER"] = "5"
os.environ["AI_MODEL_OVERRIDE"] = ""
os.environ["ALLOW_LIVE_TRADING"] = "false"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ALERT_WEBHOOK_URL"] = ""
