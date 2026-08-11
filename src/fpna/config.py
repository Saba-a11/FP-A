from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DB_PATH = PROJECT_ROOT / "db" / "fpna.duckdb"
SQL_DIR = PROJECT_ROOT / "sql"
SEED_DIR = PROJECT_ROOT / "data" / "seed"

# A standalone, never-locked copy of DB_PATH, refreshed periodically while the
# dashboard runs - see db.sync_mirror. Point any external tool (DuckDB CLI, a
# notebook, DBeaver) at this file to inspect live data without stopping the
# dashboard, which holds an exclusive lock on DB_PATH for its entire lifetime.
MIRROR_DB_PATH = PROJECT_ROOT / "db" / "fpna.mirror.duckdb"
