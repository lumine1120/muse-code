"""会话持久化：保存/加载/列出历史会话"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION_DIR = Path.home() / ".muse" / "sessions"


def _ensure_dir() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def save_session(session_id: str, data: dict[str, Any]) -> None:
    """保存会话到磁盘"""
    _ensure_dir()
    (SESSION_DIR / f"{session_id}.json").write_text(
        json.dumps(data, indent=2, default=str, ensure_ascii=False)
    )


def load_session(session_id: str) -> dict[str, Any] | None:
    """加载指定会话"""
    path = SESSION_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def list_sessions() -> list[dict[str, Any]]:
    """列出所有会话，按时间倒序"""
    _ensure_dir()
    sessions = []
    for f in SESSION_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            sessions.append(data)
        except Exception:
            continue
    sessions.sort(key=lambda s: s.get("metadata", {}).get("startTime", ""), reverse=True)
    return sessions


def get_latest_session_id() -> str | None:
    """获取最近一次会话的 ID"""
    sessions = list_sessions()
    if not sessions:
        return None
    return sessions[0].get("metadata", {}).get("id")


def new_session_id() -> str:
    """生成新的会话 ID"""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
