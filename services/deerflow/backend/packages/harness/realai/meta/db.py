"""SQLite metadata store under {dataRoot}/config/realai_meta.sqlite."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from realai.paths import ensure_data_layout, get_data_root

_lock = threading.Lock()
_initialized = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_calls (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  task_id TEXT,
  purpose TEXT,
  model TEXT,
  provider TEXT,
  latency_ms REAL,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  success INTEGER NOT NULL DEFAULT 1,
  degraded INTEGER NOT NULL DEFAULT 0,
  fallback_model TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS writing_tasks (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  goal TEXT NOT NULL,
  status TEXT NOT NULL,
  step_confirm INTEGER NOT NULL DEFAULT 0,
  outline_json TEXT,
  progress_json TEXT,
  result_json TEXT,
  error TEXT,
  artifact_ids_json TEXT,
  meta_json TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  kind TEXT NOT NULL,
  title TEXT,
  content_json TEXT NOT NULL,
  evidence_ids_json TEXT,
  source_task TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  name TEXT NOT NULL,
  aliases_json TEXT,
  formula TEXT,
  unit TEXT,
  dimensions_json TEXT,
  authority_table TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS eval_suites (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  kind TEXT
);

CREATE TABLE IF NOT EXISTS eval_cases (
  id TEXT PRIMARY KEY,
  suite_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL,
  version INTEGER NOT NULL DEFAULT 1,
  question TEXT NOT NULL,
  expect_keywords_json TEXT,
  expect_evidence INTEGER NOT NULL DEFAULT 1,
  expect_number REAL,
  number_tolerance REAL,
  expect_answer TEXT,
  answer_match_mode TEXT DEFAULT 'contains',
  expect_unit TEXT,
  expect_table_json TEXT,
  expect_source_paths_json TEXT,
  rubric_json TEXT,
  fixture_json TEXT,
  tags_json TEXT,
  difficulty TEXT DEFAULT 'medium',
  intent TEXT,
  category TEXT,
  mode TEXT DEFAULT 'light',
  expect_evidence_kinds_json TEXT,
  expect_min_rows INTEGER,
  skip_if TEXT,
  notes TEXT,
  FOREIGN KEY(suite_id) REFERENCES eval_suites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval_runs (
  id TEXT PRIMARY KEY,
  suite_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  finished_at REAL,
  heartbeat_at REAL,
  status TEXT NOT NULL,
  passed INTEGER,
  total INTEGER,
  results_json TEXT,
  mode TEXT DEFAULT 'light',
  web_search_enabled INTEGER NOT NULL DEFAULT 0,
  model_override TEXT,
  skill_overrides_json TEXT,
  snapshot_json TEXT,
  progress_json TEXT,
  compare_base_run_id TEXT,
  category_stats_json TEXT,
  metrics_json TEXT,
  options_json TEXT,
  error TEXT,
  worker_id TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(suite_id) REFERENCES eval_suites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS import_jobs (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  status TEXT NOT NULL,
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  stage TEXT,
  progress INTEGER NOT NULL DEFAULT 0,
  current_file TEXT,
  message TEXT,
  error TEXT,
  items_json TEXT
);

CREATE TABLE IF NOT EXISTS graph_nodes (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  path TEXT,
  type TEXT,
  props_json TEXT,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges (
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  rel TEXT NOT NULL DEFAULT 'link',
  weight REAL NOT NULL DEFAULT 1,
  PRIMARY KEY (src, dst, rel)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  intent TEXT,
  meta_json TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS table_catalog (
  path TEXT PRIMARY KEY,
  category TEXT,
  columns_json TEXT NOT NULL,
  types_json TEXT,
  row_count INTEGER,
  sample_json TEXT,
  mtime REAL,
  updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_calls_created ON model_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_writing_updated ON writing_tasks(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_cases_suite ON eval_cases(suite_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON graph_edges(src);
CREATE INDEX IF NOT EXISTS idx_graph_edges_dst ON graph_edges(dst);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);
"""


def db_path() -> Path:
    ensure_data_layout()
    return get_data_root() / "config" / "realai_meta.sqlite"


def connect() -> sqlite3.Connection:
    path = db_path()
    con = sqlite3.connect(str(path), check_same_thread=False, timeout=60.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=60000")
    except sqlite3.Error:
        pass
    return con


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def _ensure_column(con: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _table_columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def migrate_schema(con: sqlite3.Connection) -> None:
    """Additive migrations for existing portable DBs."""
    if "eval_cases" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        _ensure_column(con, "eval_cases", "updated_at", "updated_at REAL")
        _ensure_column(con, "eval_cases", "version", "version INTEGER NOT NULL DEFAULT 1")
        _ensure_column(con, "eval_cases", "category", "category TEXT")
        _ensure_column(con, "eval_cases", "mode", "mode TEXT DEFAULT 'light'")
        _ensure_column(con, "eval_cases", "expect_evidence_kinds_json", "expect_evidence_kinds_json TEXT")
        _ensure_column(con, "eval_cases", "expect_min_rows", "expect_min_rows INTEGER")
        _ensure_column(con, "eval_cases", "skip_if", "skip_if TEXT")
        _ensure_column(con, "eval_cases", "notes", "notes TEXT")
        _ensure_column(con, "eval_cases", "expect_answer", "expect_answer TEXT")
        _ensure_column(con, "eval_cases", "answer_match_mode", "answer_match_mode TEXT DEFAULT 'contains'")
        _ensure_column(con, "eval_cases", "expect_unit", "expect_unit TEXT")
        _ensure_column(con, "eval_cases", "expect_table_json", "expect_table_json TEXT")
        _ensure_column(con, "eval_cases", "expect_source_paths_json", "expect_source_paths_json TEXT")
        _ensure_column(con, "eval_cases", "rubric_json", "rubric_json TEXT")
        _ensure_column(con, "eval_cases", "fixture_json", "fixture_json TEXT")
        _ensure_column(con, "eval_cases", "tags_json", "tags_json TEXT")
        _ensure_column(con, "eval_cases", "difficulty", "difficulty TEXT DEFAULT 'medium'")
    if "eval_runs" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        _ensure_column(con, "eval_runs", "heartbeat_at", "heartbeat_at REAL")
        _ensure_column(con, "eval_runs", "mode", "mode TEXT DEFAULT 'light'")
        _ensure_column(con, "eval_runs", "web_search_enabled", "web_search_enabled INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "eval_runs", "model_override", "model_override TEXT")
        _ensure_column(con, "eval_runs", "skill_overrides_json", "skill_overrides_json TEXT")
        _ensure_column(con, "eval_runs", "snapshot_json", "snapshot_json TEXT")
        _ensure_column(con, "eval_runs", "progress_json", "progress_json TEXT")
        _ensure_column(con, "eval_runs", "compare_base_run_id", "compare_base_run_id TEXT")
        _ensure_column(con, "eval_runs", "category_stats_json", "category_stats_json TEXT")
        _ensure_column(con, "eval_runs", "metrics_json", "metrics_json TEXT")
        _ensure_column(con, "eval_runs", "options_json", "options_json TEXT")
        _ensure_column(con, "eval_runs", "error", "error TEXT")
        _ensure_column(con, "eval_runs", "worker_id", "worker_id TEXT")
        _ensure_column(con, "eval_runs", "cancel_requested", "cancel_requested INTEGER NOT NULL DEFAULT 0")
    if "table_catalog" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        _ensure_column(con, "table_catalog", "types_json", "types_json TEXT")
    if "eval_suites" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        _ensure_column(con, "eval_suites", "kind", "kind TEXT")
    if "writing_tasks" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        _ensure_column(con, "writing_tasks", "meta_json", "meta_json TEXT")
    if "import_jobs" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        _ensure_column(con, "import_jobs", "stage", "stage TEXT")
        _ensure_column(con, "import_jobs", "progress", "progress INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "import_jobs", "current_file", "current_file TEXT")
        _ensure_column(con, "import_jobs", "message", "message TEXT")
        _ensure_column(con, "import_jobs", "error", "error TEXT")


def init_db() -> None:
    global _initialized
    with _lock:
        if _initialized and db_path().is_file():
            return
        con = connect()
        try:
            con.executescript(SCHEMA)
            migrate_schema(con)
            con.commit()
        finally:
            con.close()
        _initialized = True


def ensure_eval_schema() -> None:
    """Force additive migrations (safe to call from evaluation module)."""
    init_db()
    con = connect()
    try:
        migrate_schema(con)
        con.commit()
    finally:
        con.close()


def get_db() -> sqlite3.Connection:
    init_db()
    return connect()
