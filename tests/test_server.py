from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from query_engine import VIEW_COLUMNS, QueryEngine
import server


def test_catalog_exposes_every_view_and_exact_columns() -> None:
    assert {entry["view"]: entry["columns"] for entry in server.CATALOG} == VIEW_COLUMNS


def test_skill_name_rejects_traversal() -> None:
    assert server.resolve_skill("../secrets") is None
    assert server.resolve_skill("name/child") is None
    assert server.resolve_skill("") is None


def test_skill_resolution_stays_inside_roots(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "skills"
    skill = root / "safe" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Safe\n", encoding="utf-8")
    monkeypatch.setattr(server, "skill_roots", lambda: [root])
    assert server.resolve_skill("safe") == skill.resolve()


def test_proxy_visible_api_routes(monkeypatch) -> None:
    class FakeEngine:
        @staticmethod
        def dependency_status() -> dict[str, object]:
            return {"available": True, "version": "test"}

        @staticmethod
        def source_counts() -> dict[str, int]:
            return {"sessions": 1}

    monkeypatch.setattr(server, "ENGINE", FakeEngine())
    monkeypatch.setattr(server, "run_query", lambda *args, **kwargs: [{"ok": 1}])
    monkeypatch.setattr(server, "overview", lambda: {"route": "overview"})
    monkeypatch.setattr(server, "query_cost", lambda: {"route": "slow-queries"})
    monkeypatch.setattr(
        server,
        "skill_document",
        lambda name: (200, {"route": "skill", "name": name}),
    )

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    def get(path: str) -> tuple[int, dict]:
        try:
            with urlopen(base + path, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    try:
        assert get("/health")[0] == 200
        assert get("/api/status")[0] == 200
        assert get("/api/catalog")[1]["views"] == server.CATALOG
        assert get("/api/overview") == (200, {"route": "overview"})
        assert get("/api/slow-queries") == (200, {"route": "slow-queries"})
        assert get("/api/setup")[1]["ok"] is True
        assert get("/api/skill?name=lens-sql") == (
            200,
            {"route": "skill", "name": "lens-sql"},
        )
        assert get("/api/apps/lens-kiro-crew-app/overview")[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_browser_and_backend_api_contracts_are_distinct() -> None:
    manifest = json.loads((ROOT / "app.json").read_text(encoding="utf-8"))
    browser_api = "/apps/lens-kiro-crew-app/api"
    endpoints = ("status", "catalog", "overview", "slow-queries", "setup", "skill")

    assert manifest["permissions"]["api"] == [
        f"{browser_api}/{endpoint}" for endpoint in endpoints
    ]
    assert f"const API = '{browser_api}'" in (
        ROOT / "ui" / "src" / "App.tsx"
    ).read_text(encoding="utf-8")
    assert server.API == "/api"


def test_overview_counts_only_genuine_skill_read_paths(tmp_path: Path, monkeypatch) -> None:
    crew = tmp_path / "crew"
    session = crew / "sessions" / "dashboard_chat-skills.jsonl"
    session.parent.mkdir(parents=True)
    rows = [
        {"_type": "metadata", "title": "Skill reads", "created_at": "2026-01-01T00:00:00Z"},
        {
            "role": "tool",
            "content": "🔧 Reading SKILL.md:1-100",
            "ts": "2026-01-01T00:00:01Z",
            "meta": {
                "tool_call_id": "real-read",
                "input": json.dumps({"operations": [{"mode": "Line", "path": "/skills/real-skill/SKILL.md"}]}),
            },
        },
        {
            "role": "tool",
            "content": "🔧 Running a command",
            "ts": "2026-01-01T00:00:02Z",
            "meta": {
                "tool_call_id": "false-command",
                "input": json.dumps({"command": "echo /skills/fake-skill/SKILL.md"}),
            },
        },
        {
            "role": "tool",
            "content": "🔧 Searching for 'SKILL.md' in source",
            "ts": "2026-01-01T00:00:03Z",
            "meta": {
                "tool_call_id": "false-search",
                "input": json.dumps({"pattern": "{name}/SKILL.md", "path": "/source", "output_mode": "content"}),
            },
        },
    ]
    session.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(server, "ENGINE", QueryEngine(crew_home=crew, kiro_home=tmp_path / "kiro"))

    result = server.overview()

    assert [
        {**row, "last_read": str(row["last_read"])} for row in result["skill_reads"]
    ] == [{"skill": "real-skill", "reads": 1, "last_read": "2026-01-01"}]


def test_installed_sidebar_icon_asset_is_declared_and_valid() -> None:
    import xml.etree.ElementTree as ET

    manifest = json.loads((ROOT / "app.json").read_text(encoding="utf-8"))
    page = manifest["ui"]["pages"][0]
    assert page["iconUrl"] == "lens-icon.svg"

    icon_path = ROOT / "ui" / page["iconUrl"]
    root = ET.parse(icon_path).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["viewBox"] == "0 0 24 24"
    assert root.findall(".//{http://www.w3.org/2000/svg}circle")
    assert root.findall(".//{http://www.w3.org/2000/svg}path")
