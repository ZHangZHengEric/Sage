#!/usr/bin/env python3
import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, List


def sanitize_title_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(
        r"^\s*(?:<enable_plan>\s*(?:true|false)\s*</enable_plan>\s*|<enable_deep_thinking>\s*(?:true|false)\s*</enable_deep_thinking>\s*)+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^\s*<skill>.*?</skill>\s*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(
        r"<(?:skills|active_skills|available_skills)>[\s\S]*?</(?:skills|active_skills|available_skills)>",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, list):
        text_parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return " ".join(p for p in text_parts if p).strip()
    return str(content or "").strip()


def build_title_from_messages(messages_raw: Any) -> str:
    messages = messages_raw
    if isinstance(messages_raw, str):
        try:
            messages = json.loads(messages_raw)
        except Exception:
            messages = []
    if not isinstance(messages, list):
        return ""

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        text = sanitize_title_text(extract_text_from_content(msg.get("content")))
        if text:
            return text[:50] + "..." if len(text) > 50 else text
    return ""


def looks_meaningful(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    stripped = re.sub(r"[.\u2026。\-_=,:;!?\'\"`~()\[\]{}<>/\\|]+", "", t).strip()
    return bool(stripped)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair malformed conversation titles in Sage desktop DB.")
    parser.add_argument(
        "--db-path",
        default=str(Path.home() / ".sage" / "sage.db"),
        help="Path to sqlite db (default: ~/.sage/sage.db)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print changes, do not write.")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to scan (0 = all).")
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser()
    if not db_path.exists():
        print(f"[ERROR] DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = "SELECT session_id, title, messages FROM conversations ORDER BY updated_at DESC"
    if args.limit and args.limit > 0:
        sql += f" LIMIT {int(args.limit)}"
    rows = cur.execute(sql).fetchall()

    scanned = 0
    fixed = 0
    skipped = 0

    for row in rows:
        scanned += 1
        session_id = row["session_id"]
        old_title = row["title"] or ""
        new_title = build_title_from_messages(row["messages"])
        if not new_title:
            # Fallback when messages are empty: recover directly from old title text if possible.
            from_old = sanitize_title_text(old_title)
            if looks_meaningful(from_old):
                new_title = from_old[:50] + "..." if len(from_old) > 50 else from_old

        if not new_title or new_title == old_title:
            skipped += 1
            continue

        # Prioritize malformed titles that are polluted by control tags or become "..."
        looks_malformed = (
            old_title.strip() in {"...", ""}
            or old_title.startswith("<enable_plan>")
            or old_title.startswith("<enable_deep_thinking>")
            or old_title.startswith("<skill>")
            or old_title.startswith("<skills>")
            or old_title.startswith("<active_skills>")
            or old_title.startswith("<available_skills>")
        )
        if not looks_malformed:
            skipped += 1
            continue

        print(f"[FIX] {session_id}\n  old: {old_title}\n  new: {new_title}\n")
        if not args.dry_run:
            cur.execute(
                "UPDATE conversations SET title = ? WHERE session_id = ?",
                (new_title, session_id),
            )
            fixed += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"[{mode}] scanned={scanned}, fixed={fixed}, skipped={skipped}, db={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
