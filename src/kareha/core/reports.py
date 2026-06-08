"""
Simple report system for user moderation reports.
Stores reports in a JSON file in the board root.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List, Dict


def _get_reports_file(board_dir: Path) -> Path:
    return board_dir / "reports.json"


def load_reports(board_dir: Path) -> List[Dict[str, Any]]:
    reports_file = _get_reports_file(board_dir)
    if not reports_file.exists():
        return []
    try:
        return json.loads(reports_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_reports(board_dir: Path, reports: List[Dict[str, Any]]):
    reports_file = _get_reports_file(board_dir)
    reports_file.parent.mkdir(parents=True, exist_ok=True)
    reports_file.write_text(
        json.dumps(reports, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def submit_report(
    board_dir: Path,
    thread_id: int,
    post_num: int,
    reason: str,
    ip: str = "unknown",
) -> bool:
    if not reason or not reason.strip():
        return False

    reports = load_reports(board_dir)

    report = {
        "timestamp": int(time.time()),
        "thread": thread_id,
        "post": post_num,
        "reason": reason.strip(),
        "ip": ip,
        "status": "open",   # open / handled / dismissed
    }

    reports.append(report)
    save_reports(board_dir, reports)
    return True


def get_open_reports(board_dir: Path) -> List[Dict[str, Any]]:
    return [r for r in load_reports(board_dir) if r.get("status", "open") == "open"]


def update_report_status(board_dir: Path, report_index: int, new_status: str):
    reports = load_reports(board_dir)
    if 0 <= report_index < len(reports):
        reports[report_index]["status"] = new_status
        save_reports(board_dir, reports)
        return True
    return False
