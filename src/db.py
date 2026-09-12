from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_py(value):
    if value is None:
        return None
    try:
        return value.to_py()
    except Exception:
        return value


async def first(db, sql: str, *params) -> dict[str, Any] | None:
    row = await db.prepare(sql).bind(*params).first()
    row = _to_py(row)
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return row


async def rows(db, sql: str, *params) -> list[dict[str, Any]]:
    result = await db.prepare(sql).bind(*params).run()
    data = _to_py(result.results)
    if data is None:
        return []
    return [dict(x) if not isinstance(x, dict) else x for x in data]


async def execute(db, sql: str, *params):
    return await db.prepare(sql).bind(*params).run()


async def get_user_by_username(db, username: str):
    return await first(db, "SELECT * FROM users WHERE username = ? COLLATE NOCASE LIMIT 1", username)


async def get_user(db, user_id: int):
    return await first(db, "SELECT id, username, role, created_at, updated_at, last_login_at FROM users WHERE id = ?", user_id)


async def create_user(db, username: str, password_hash: str) -> int:
    now = iso()
    result = await execute(
        db,
        "INSERT INTO users(username,password_hash,role,created_at,updated_at) VALUES(?,?, 'user', ?, ?)",
        username,
        password_hash,
        now,
        now,
    )
    meta = _to_py(result.meta)
    return int(meta.get("last_row_id") if isinstance(meta, dict) else meta.last_row_id)


async def set_password(db, user_id: int, password_hash: str):
    await execute(db, "UPDATE users SET password_hash=?, updated_at=? WHERE id=?", password_hash, iso(), user_id)


async def touch_login(db, user_id: int):
    now = iso()
    await execute(db, "UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", now, now, user_id)


async def create_session(db, user_id: int, token_hash: str, csrf: str, days: int, user_agent: str, ip_hash: str):
    now_dt = utcnow()
    await execute(
        db,
        "INSERT INTO sessions(user_id,token_hash,csrf_token,created_at,expires_at,last_seen_at,user_agent,ip_hash) VALUES(?,?,?,?,?,?,?,?)",
        user_id,
        token_hash,
        csrf,
        iso(now_dt),
        iso(now_dt + timedelta(days=days)),
        iso(now_dt),
        (user_agent or "")[:300],
        ip_hash,
    )


async def get_session(db, token_hash: str):
    return await first(
        db,
        """SELECT s.*, u.username, u.role
           FROM sessions s JOIN users u ON u.id=s.user_id
           WHERE s.token_hash=? AND s.expires_at>? LIMIT 1""",
        token_hash,
        iso(),
    )


async def touch_session(db, session_id: int):
    await execute(db, "UPDATE sessions SET last_seen_at=? WHERE id=?", iso(), session_id)


async def delete_session(db, token_hash: str):
    await execute(db, "DELETE FROM sessions WHERE token_hash=?", token_hash)


async def delete_user_sessions(db, user_id: int):
    await execute(db, "DELETE FROM sessions WHERE user_id=?", user_id)


async def record_login_attempt(db, ip_hash: str, username: str, action: str, succeeded: bool):
    await execute(
        db,
        "INSERT INTO login_attempts(ip_hash,username,action,succeeded,created_at) VALUES(?,?,?,?,?)",
        ip_hash,
        (username or "")[:64],
        action,
        1 if succeeded else 0,
        iso(),
    )


async def too_many_auth_attempts(db, ip_hash: str, minutes: int = 15, limit: int = 12) -> bool:
    since = iso(utcnow() - timedelta(minutes=minutes))
    row = await first(
        db,
        "SELECT COUNT(*) AS c FROM login_attempts WHERE ip_hash=? AND created_at>=? AND succeeded=0",
        ip_hash,
        since,
    )
    return bool(row and int(row.get("c", 0)) >= limit)


async def get_profile(db, user_id: int):
    return await first(db, "SELECT * FROM profiles WHERE user_id=?", user_id)


async def upsert_profile(db, user_id: int, p: dict[str, Any]):
    await execute(
        db,
        """INSERT INTO profiles(user_id,display_name,gender,calendar_type,birth_year,birth_month,birth_day,birth_hour,birth_hour_unknown,leap_month,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             display_name=excluded.display_name,
             gender=excluded.gender,
             calendar_type=excluded.calendar_type,
             birth_year=excluded.birth_year,
             birth_month=excluded.birth_month,
             birth_day=excluded.birth_day,
             birth_hour=excluded.birth_hour,
             birth_hour_unknown=excluded.birth_hour_unknown,
             leap_month=excluded.leap_month,
             updated_at=excluded.updated_at""",
        user_id,
        p["display_name"],
        p["gender"],
        p["calendar_type"],
        p["birth_year"],
        p["birth_month"],
        p["birth_day"],
        p.get("birth_hour"),
        1 if p.get("birth_hour_unknown") else 0,
        1 if p.get("leap_month") else 0,
        iso(),
    )


async def invalidate_chart(db, user_id: int):
    await execute(db, "DELETE FROM chart_cache WHERE user_id=?", user_id)


async def get_chart_cache(db, user_id: int, fingerprint: str, engine_commit: str):
    row = await first(
        db,
        "SELECT * FROM chart_cache WHERE user_id=? AND profile_fingerprint=? AND engine_commit=?",
        user_id,
        fingerprint,
        engine_commit,
    )
    if not row:
        return None
    try:
        return json.loads(row["chart_digest"])
    except Exception:
        return None


async def put_chart_cache(db, user_id: int, fingerprint: str, engine_commit: str, chart: dict[str, Any]):
    payload = json.dumps(chart, ensure_ascii=False, separators=(",", ":"))
    await execute(
        db,
        """INSERT INTO chart_cache(user_id,profile_fingerprint,engine_commit,chart_mode,chart_digest,raw_output,generated_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             profile_fingerprint=excluded.profile_fingerprint,
             engine_commit=excluded.engine_commit,
             chart_mode=excluded.chart_mode,
             chart_digest=excluded.chart_digest,
             raw_output=excluded.raw_output,
             generated_at=excluded.generated_at""",
        user_id,
        fingerprint,
        engine_commit,
        chart.get("mode", "unknown"),
        payload,
        None,
        iso(),
    )


async def create_conversation(db, user_id: int, title: str = "新对话") -> int:
    now = iso()
    result = await execute(
        db,
        "INSERT INTO conversations(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
        user_id,
        (title or "新对话")[:80],
        now,
        now,
    )
    meta = _to_py(result.meta)
    return int(meta.get("last_row_id") if isinstance(meta, dict) else meta.last_row_id)


async def get_conversation(db, conversation_id: int, user_id: int):
    return await first(db, "SELECT * FROM conversations WHERE id=? AND user_id=?", conversation_id, user_id)


async def list_conversations(db, user_id: int, limit: int = 40):
    return await rows(
        db,
        "SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
        user_id,
        limit,
    )


async def rename_conversation_if_default(db, conversation_id: int, title: str):
    await execute(
        db,
        "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND title='新对话'",
        (title or "新对话")[:80],
        iso(),
        conversation_id,
    )


async def add_message(db, conversation_id: int, user_id: int, role: str, content: str, model: str | None = None, prompt_tokens: int | None = None, completion_tokens: int | None = None) -> int:
    result = await execute(
        db,
        """INSERT INTO messages(conversation_id,user_id,role,content,model,prompt_tokens,completion_tokens,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        conversation_id,
        user_id,
        role,
        content,
        model,
        prompt_tokens,
        completion_tokens,
        iso(),
    )
    await execute(db, "UPDATE conversations SET updated_at=? WHERE id=?", iso(), conversation_id)
    meta = _to_py(result.meta)
    return int(meta.get("last_row_id") if isinstance(meta, dict) else meta.last_row_id)


async def history(db, conversation_id: int, user_id: int, limit: int = 24):
    data = await rows(
        db,
        """SELECT id,role,content,model,created_at FROM messages
           WHERE conversation_id=? AND user_id=? ORDER BY id DESC LIMIT ?""",
        conversation_id,
        user_id,
        limit,
    )
    return list(reversed(data))


async def create_attachment(db, attachment_id: str, user_id: int, conversation_id: int | None, storage_key: str, original_name: str, mime_type: str, media_kind: str, byte_size: int, sha256: str | None):
    await execute(
        db,
        """INSERT INTO attachments(id,user_id,conversation_id,storage_key,original_name,mime_type,media_kind,byte_size,sha256,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        attachment_id,
        user_id,
        conversation_id,
        storage_key,
        original_name[:240],
        mime_type[:120],
        media_kind,
        byte_size,
        sha256,
        iso(),
    )


async def get_attachments(db, user_id: int, attachment_ids: list[str]):
    if not attachment_ids:
        return []
    placeholders = ",".join("?" for _ in attachment_ids)
    return await rows(
        db,
        f"SELECT * FROM attachments WHERE user_id=? AND id IN ({placeholders}) ORDER BY created_at",
        user_id,
        *attachment_ids,
    )


async def bind_attachments_to_message(db, user_id: int, message_id: int, conversation_id: int, attachment_ids: list[str]):
    for aid in attachment_ids:
        await execute(
            db,
            "UPDATE attachments SET message_id=?, conversation_id=? WHERE id=? AND user_id=? AND message_id IS NULL",
            message_id,
            conversation_id,
            aid,
            user_id,
        )


async def audit(db, actor_user_id: int | None, event_type: str, target_type: str | None = None, target_id: str | None = None, detail: Any = None):
    detail_text = None if detail is None else json.dumps(detail, ensure_ascii=False)[:4000]
    await execute(
        db,
        "INSERT INTO audit_logs(actor_user_id,event_type,target_type,target_id,detail,created_at) VALUES(?,?,?,?,?,?)",
        actor_user_id,
        event_type,
        target_type,
        target_id,
        detail_text,
        iso(),
    )


async def admin_users(db):
    return await rows(
        db,
        """SELECT u.id,u.username,u.role,u.created_at,u.last_login_at,
                  p.display_name,p.gender,p.calendar_type,p.birth_year,p.birth_month,p.birth_day,p.birth_hour,p.birth_hour_unknown,p.leap_month,
                  (SELECT COUNT(*) FROM conversations c WHERE c.user_id=u.id) AS conversation_count,
                  (SELECT COUNT(*) FROM messages m WHERE m.user_id=u.id) AS message_count,
                  (SELECT COUNT(*) FROM attachments a WHERE a.user_id=u.id) AS attachment_count
           FROM users u LEFT JOIN profiles p ON p.user_id=u.id ORDER BY u.id DESC"""
    )


async def admin_user_dump(db, user_id: int):
    return {
        "user": await get_user(db, user_id),
        "profile": await get_profile(db, user_id),
        "conversations": await rows(db, "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC", user_id),
        "messages": await rows(db, "SELECT id,conversation_id,role,content,model,prompt_tokens,completion_tokens,created_at FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 1000", user_id),
        "attachments": await rows(db, "SELECT id,conversation_id,message_id,original_name,mime_type,media_kind,byte_size,sha256,created_at FROM attachments WHERE user_id=? ORDER BY created_at DESC", user_id),
        "chart_cache": await first(db, "SELECT user_id,profile_fingerprint,engine_commit,chart_mode,generated_at FROM chart_cache WHERE user_id=?", user_id),
        "audit": await rows(db, "SELECT * FROM audit_logs WHERE actor_user_id=? ORDER BY id DESC LIMIT 300", user_id),
    }
