#!/usr/bin/env python3
"""Run one guarded, read-only Lens query."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from query_engine import QueryEngine, QueryError  # noqa: E402


def main() -> int:
    sql = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not sql:
        print('usage: kc-lens "SELECT ..."', file=sys.stderr)
        return 2
    try:
        rows = QueryEngine().query(sql, caller="kc-lens")
    except QueryError as exc:
        print(f"kc-lens: {exc}", file=sys.stderr)
        return 1
    if os.environ.get("KC_LENS_JSON") == "1":
        print(json.dumps(rows, default=str))
        return 0
    if not rows:
        print("(no rows)")
        return 0
    columns = list(rows[0])
    widths = {column: max(len(column), *(len(str(row.get(column, ""))) for row in rows)) for column in columns}
    print("  ".join(column.ljust(widths[column]) for column in columns))
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
