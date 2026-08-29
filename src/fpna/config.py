import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Secrets (Telegram bot token, later a real SMTP login) live in a local
# .env file - never committed (see .gitignore) - not in code or the
# database, same reasoning send_email/SendEmail.py applies to SMTP_USER/
# SMTP_PASS. override=False: an env var already set in the real environment
# (e.g. by whoever eventually deploys this) always wins over .env.
load_dotenv(PROJECT_ROOT / ".env", override=False)

# Telegram notification target - see fpna.notify. Both unset just means
# notifications are silently skipped (logged, never raised) rather than the
# app refusing to start; day-to-day use of the canvas never required these.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

DB_PATH = PROJECT_ROOT / "db" / "fpna.duckdb"
SQL_DIR = PROJECT_ROOT / "sql"
SEED_DIR = PROJECT_ROOT / "data" / "seed"

# Uploaded step-template files (workflow_step.template_path) land under here,
# one subfolder per step_id (see workflow.save_step_template) - never an
# absolute path in the database, only a path relative to PROJECT_ROOT, so
# the database file stays portable across machines.
TEMPLATES_DIR = PROJECT_ROOT / "data" / "templates"

# A standalone, never-locked copy of DB_PATH, refreshed periodically while the
# dashboard runs - see db.sync_mirror. Point any external tool (DuckDB CLI, a
# notebook, DBeaver) at this file to inspect live data without stopping the
# dashboard, which holds an exclusive lock on DB_PATH for its entire lifetime.
MIRROR_DB_PATH = PROJECT_ROOT / "db" / "fpna.mirror.duckdb"
