from __future__ import annotations

import base64
import json
import mimetypes
import re
import secrets
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

from workers import Response, WorkerEntrypoint

import db
from admin_ui import ADMIN_HTML
from bazi_adapter import BAZI_ENGINE_COMMIT, ProfileInput, build_chart, profile_fingerprint
from divination import auxiliary_context
from minimax import chat as minimax_chat
from minimax import stream_chat as minimax_stream_chat
from prompts import attachment_instruction, build_case_context, build_system_prompt
from security import (
    constant_time_equals,
    hash_password,
    ip_hash,
    new_csrf_token,
    new_session_token,
    token_hash,
    validate_password,
    validate_username,
    verify_password,
)
from ui import APP_HTML

COOKIE_NAME = "buqiuren_session"
ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VIDEOS = {"video/mp4", "video/webm", "video/quicktime"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 8


def _env(env, name: str, default: str = "") -> str:
    try:
        value = getattr(env, name)
        return str(value)
    except Exception:
        return default


def _json(data, status=200, headers=None):
    h = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
    if headers:
        h.update(headers)
    return Response(json.dumps(data, ensure_ascii=False, separators=(",", ":")), status=status, headers=h)


def _error(message: str, status=400):
    return _json({"error": message}, status=status)


def _html(text: str, status=200, headers=None):
    h = {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    }
    if headers:
        h.update(headers)
    return Response(text, status=status, headers=h)


def _cookie_value(request, name: str) -> str | None:
    raw = request.headers.get("Cookie") or ""
    for part in raw.split(";"):
        if "=" not in part:
            continue
        k, v = part.strip().split("=", 1)
        if k == name:
            return v
    return None


def _session_cookie(token: str, days: int) -> str:
    return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={days * 86400}"


def _clear_cookie() -> str:
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"


def _client_ip(request) -> str:
    return request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For") or "unknown"


def _origin(request) -> str:
    u = urlparse(request.url)
    return f"{u.scheme}://{u.netloc}"


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix or "") else ""


def _profile_public(row):
    if not row:
        return None
    return {
        "display_name": row["display_name"],
        "gender": row["gender"],
        "calendar_type": row["calendar_type"],
        "birth_year": row["birth_year"],
        "birth_month": row["birth_month"],
        "birth_day": row["birth_day"],
        "birth_hour": row.get("birth_hour"),
        "birth_hour_unknown": bool(row.get("birth_hour_unknown")),
        "leap_month": bool(row.get("leap_month")),
    }


def _validate_profile(payload: dict) -> dict:
    display_name = str(payload.get("display_name") or "").strip()
    if not display_name or len(display_name) > 30:
        raise ValueError("称呼需为 1–30 个字符")
    gender = payload.get("gender")
    if gender not in ("male", "female"):
        raise ValueError("性别参数无效")
    calendar_type = payload.get("calendar_type")
    if calendar_type not in ("solar", "lunar"):
        raise ValueError("历法参数无效")
    try:
        year = int(payload.get("birth_year"))
        month = int(payload.get("birth_month"))
        day = int(payload.get("birth_day"))
    except Exception as exc:
        raise ValueError("出生年月日必须完整") from exc
    if not 1850 <= year <= 2100:
        raise ValueError("出生年份当前支持 1850–2100")
    if not 1 <= month <= 12:
        raise ValueError("月份必须为 1–12")
    if calendar_type == "solar":
        try:
            datetime(year, month, day)
        except ValueError as exc:
            raise ValueError("公历日期无效") from exc
    elif not 1 <= day <= 30:
        raise ValueError("农历日期必须为 1–30")

    unknown = bool(payload.get("birth_hour_unknown"))
    hour = payload.get("birth_hour")
    if unknown:
        hour = None
    else:
        try:
            hour = int(hour)
        except Exception as exc:
            raise ValueError("请选择出生时辰，或明确选择未知") from exc
        if not 0 <= hour <= 23:
            raise ValueError("出生小时必须为 0–23")
    leap = bool(payload.get("leap_month")) if calendar_type == "lunar" else False
    return {
        "display_name": display_name,
        "gender": gender,
        "calendar_type": calendar_type,
        "birth_year": year,
        "birth_month": month,
        "birth_day": day,
        "birth_hour": hour,
        "birth_hour_unknown": unknown,
        "leap_month": leap,
    }


class Default(WorkerEntrypoint):
    @property
    def pepper(self):
        return _env(self.env, "SESSION_PEPPER")

    async def _session(self, request):
        token = _cookie_value(request, COOKIE_NAME)
        if not token or not self.pepper:
            return None
        session = await db.get_session(self.env.DB, token_hash(token, self.pepper))
        if session:
            await db.touch_session(self.env.DB, int(session["id"]))
        return session

    async def _require_session(self, request, csrf=False):
        session = await self._session(request)
        if not session:
            return None, _error("请先登录", 401)
        if csrf and not constant_time_equals(request.headers.get("X-CSRF-Token") or "", session.get("csrf_token") or ""):
            return None, _error("请求校验失败，请刷新页面后重试", 403)
        return session, None

    def _admin_ok(self, request) -> bool:
        password = _env(self.env, "ADMIN_PASSWORD")
        if not password:
            return False
        header = request.headers.get("Authorization") or ""
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:]).decode("utf-8")
            username, supplied = raw.split(":", 1)
        except Exception:
            return False
        return username == "admin" and constant_time_equals(supplied, password)

    def _admin_unauthorized(self):
        return Response("Authentication required", status=401, headers={"WWW-Authenticate": 'Basic realm="Buqiuren Internal", charset="UTF-8"', "Cache-Control": "no-store"})

    def _media_url(self, request, attachment: dict, ttl=900) -> str:
        expires = int(time.time()) + ttl
        sig = token_hash(f"media:{attachment['id']}:{expires}", self.pepper)
        name = quote(attachment.get("original_name") or "media", safe="")
        return f"{_origin(request)}/media/{attachment['id']}/{name}?e={expires}&s={sig}"

    async def _handle_auth(self, request, action: str):
        try:
            body = await request.json()
        except Exception:
            return _error("请求格式无效")
        try:
            username = validate_username(str(body.get("username") or ""))
            password = str(body.get("password") or "")
            validate_password(password)
        except ValueError as exc:
            return _error(str(exc))

        iph = ip_hash(_client_ip(request), self.pepper)
        if await db.too_many_auth_attempts(self.env.DB, iph):
            return _error("尝试次数过多，请稍后再试", 429)

        if action == "register":
            recent = await db.first(self.env.DB, "SELECT COUNT(*) AS c FROM login_attempts WHERE ip_hash=? AND action='register' AND created_at>=datetime('now','-1 hour')", iph)
            if recent and int(recent.get("c", 0)) >= 5:
                return _error("当前网络注册过于频繁，请稍后再试", 429)
            if await db.get_user_by_username(self.env.DB, username):
                await db.record_login_attempt(self.env.DB, iph, username, action, False)
                return _error("用户名已存在", 409)
            user_id = await db.create_user(self.env.DB, username, hash_password(password, self.pepper))
            await db.audit(self.env.DB, user_id, "user.registered", "user", str(user_id))
        else:
            user = await db.get_user_by_username(self.env.DB, username)
            if not user or not verify_password(password, user.get("password_hash", ""), self.pepper):
                await db.record_login_attempt(self.env.DB, iph, username, action, False)
                return _error("用户名或密码错误", 401)
            user_id = int(user["id"])
            await db.touch_login(self.env.DB, user_id)

        await db.record_login_attempt(self.env.DB, iph, username, action, True)
        token = new_session_token()
        csrf = new_csrf_token()
        days = int(_env(self.env, "SESSION_DAYS", "30"))
        await db.create_session(self.env.DB, user_id, token_hash(token, self.pepper), csrf, days, request.headers.get("User-Agent") or "", iph)
        return _json({"ok": True, "csrf": csrf}, headers={"Set-Cookie": _session_cookie(token, days)})

    async def _upload(self, request, session, params):
        filename = (params.get("filename") or [""])[0][:240]
        mime = ((params.get("mime") or [request.headers.get("Content-Type") or ""])[0]).split(";", 1)[0].lower()
        try:
            declared = int((params.get("size") or ["0"])[0])
        except Exception:
            declared = 0
        if mime in ALLOWED_IMAGES:
            kind, limit = "image", MAX_IMAGE_BYTES
        elif mime in ALLOWED_VIDEOS:
            kind, limit = "video", MAX_VIDEO_BYTES
        else:
            return _error("当前附件仅支持 JPEG/PNG/WebP/GIF 图片与 MP4/WebM/MOV 视频", 415)
        if declared <= 0 or declared > limit:
            return _error("附件大小不符合限制：图片 ≤10MB，视频 ≤50MB", 413)

        conversation_id = None
        raw_conversation = (params.get("conversation_id") or [None])[0]
        if raw_conversation:
            try:
                conversation_id = int(raw_conversation)
            except Exception:
                return _error("会话参数无效")
            if not await db.get_conversation(self.env.DB, conversation_id, int(session["user_id"])):
                return _error("会话不存在", 404)

        aid = secrets.token_urlsafe(12)
        suffix = _safe_suffix(filename) or (mimetypes.guess_extension(mime) or "")
        key = f"u/{session['user_id']}/{aid}{suffix}"
        obj = await self.env.MEDIA.put(key, request.body)
        if obj is None:
            return _error("附件上传失败", 500)
        actual = int(obj.size)
        if actual > limit:
            await self.env.MEDIA.delete(key)
            return _error("附件超过大小限制", 413)
        await db.create_attachment(self.env.DB, aid, int(session["user_id"]), conversation_id, key, filename or f"attachment{suffix}", mime, kind, actual, None)
        await db.audit(self.env.DB, int(session["user_id"]), "attachment.uploaded", "attachment", aid, {"kind": kind, "size": actual})
        return _json({"id": aid, "name": filename, "kind": kind, "size": actual}, 201)

    async def _serve_media(self, request, path, params):
        parts = path.strip("/").split("/")
        if len(parts) < 2:
            return Response("Not found", status=404)
        aid = parts[1]
        try:
            expires = int((params.get("e") or ["0"])[0])
        except Exception:
            expires = 0
        supplied = (params.get("s") or [""])[0]
        if expires < int(time.time()) or not constant_time_equals(supplied, token_hash(f"media:{aid}:{expires}", self.pepper)):
            return Response("Forbidden", status=403)
        attachment = await db.first(self.env.DB, "SELECT id,storage_key,mime_type,original_name FROM attachments WHERE id=?", aid)
        if not attachment:
            return Response("Not found", status=404)
        obj = await self.env.MEDIA.get(attachment["storage_key"])
        if obj is None or not hasattr(obj, "body"):
            return Response("Not found", status=404)
        return Response(obj.body, headers={"Content-Type": attachment["mime_type"], "Cache-Control": "private, max-age=120", "X-Content-Type-Options": "nosniff"})

    async def _chat(self, request, session):
        profile = await db.get_profile(self.env.DB, int(session["user_id"]))
        if not profile:
            return _error("请先完成称呼、性别和出生信息，再开始推演", 428)
        try:
            body = await request.json()
        except Exception:
            return _error("请求格式无效")
        text = str(body.get("text") or "").strip()
        wants_stream = bool(body.get("stream"))
        attachment_ids = body.get("attachment_ids") or []
        if not isinstance(attachment_ids, list) or len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
            return _error("单次最多 8 个附件")
        attachment_ids = [str(x) for x in attachment_ids]
        if len(text) > 12000:
            return _error("单次文字过长，请拆成几轮")
        if not text and not attachment_ids:
            return _error("请输入问题或添加附件")

        recent = await db.first(self.env.DB, "SELECT COUNT(*) AS c FROM messages WHERE user_id=? AND role='user' AND created_at>=datetime('now','-1 minute')", int(session["user_id"]))
        if recent and int(recent.get("c", 0)) >= 8:
            return _error("推演过于频繁，请稍后再继续", 429)

        try:
            conversation_id = int(body.get("conversation_id"))
        except Exception:
            return _error("会话参数无效")
        conversation = await db.get_conversation(self.env.DB, conversation_id, int(session["user_id"]))
        if not conversation:
            return _error("会话不存在", 404)

        attachments = await db.get_attachments(self.env.DB, int(session["user_id"]), attachment_ids)
        if len(attachments) != len(set(attachment_ids)):
            return _error("存在无效附件", 400)
        if any(a.get("message_id") is not None for a in attachments):
            return _error("附件已经用于其他消息", 409)

        p = ProfileInput.from_row(profile)
        fingerprint = profile_fingerprint(p)
        chart = await db.get_chart_cache(self.env.DB, int(session["user_id"]), fingerprint, BAZI_ENGINE_COMMIT)
        if chart is None:
            chart = build_chart(p)
            await db.put_chart_cache(self.env.DB, int(session["user_id"]), fingerprint, BAZI_ENGINE_COMMIT, chart)

        timezone = _env(self.env, "DIVINATION_TIMEZONE", "Asia/Shanghai")
        try:
            now = datetime.now(ZoneInfo(timezone))
        except Exception:
            now = datetime.now().astimezone()
        auxiliary = auxiliary_context(text, now, f"{session['user_id']}:{conversation_id}:{text[:120]}")
        history = await db.history(self.env.DB, conversation_id, int(session["user_id"]), int(_env(self.env, "MAX_HISTORY_MESSAGES", "24")))

        # Rehydrate historical media so follow-up questions like “第二张图” still work.
        for row in history:
            old_media = await db.rows(self.env.DB, "SELECT id,original_name,mime_type,media_kind,byte_size,storage_key FROM attachments WHERE message_id=? ORDER BY created_at", int(row["id"]))
            for a in old_media:
                a["signed_url"] = self._media_url(request, a)
            row["attachments"] = old_media

        media = []
        for a in attachments:
            item = dict(a)
            item["signed_url"] = self._media_url(request, item)
            media.append(item)

        user_content = text or "请分析本轮上传的材料。"
        if attachments:
            user_content += "\n\n[本轮附件：" + "、".join(a["original_name"] for a in attachments) + "]"
        message_id = await db.add_message(self.env.DB, conversation_id, int(session["user_id"]), "user", user_content)
        await db.bind_attachments_to_message(self.env.DB, int(session["user_id"]), message_id, conversation_id, attachment_ids)
        await db.rename_conversation_if_default(self.env.DB, conversation_id, (text[:36] if text else attachments[0]["original_name"]) or "新对话")

        model_kwargs = {
            "api_key": _env(self.env, "MINIMAX_API_KEY"),
            "base_url": _env(self.env, "MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
            "model": _env(self.env, "MINIMAX_MODEL", "MiniMax-M3"),
            "system_prompt": build_system_prompt(),
            "case_context": build_case_context(dict(profile), chart, auxiliary),
            "history": history,
            "user_text": text or "请分析本轮上传的材料。",
            "media": media,
            "attachment_note": attachment_instruction(attachments),
        }

        if wants_stream:
            from js import ReadableStream, TextEncoder
            from pyodide.ffi import create_proxy, to_js

            encoder = TextEncoder.new()

            async def start(controller):
                async def emit(payload):
                    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
                    controller.enqueue(encoder.encode(line))

                try:
                    await emit({"type": "start", "conversation_id": conversation_id})
                    async for event in minimax_stream_chat(**model_kwargs):
                        kind = event.get("type")
                        if kind in ("reasoning", "content"):
                            await emit({"type": kind, "delta": event.get("delta") or ""})
                            continue
                        if kind == "done":
                            result = event["result"]
                            assistant_id = await db.add_message(
                                self.env.DB,
                                conversation_id,
                                int(session["user_id"]),
                                "assistant",
                                result.content,
                                result.model,
                                result.prompt_tokens,
                                result.completion_tokens,
                                result.reasoning,
                            )
                            await db.audit(
                                self.env.DB,
                                int(session["user_id"]),
                                "chat.completed",
                                "message",
                                str(assistant_id),
                                {"model": result.model, "attachments": len(attachments), "usage": result.raw_usage, "stream": True},
                            )
                            await emit({
                                "type": "done",
                                "message": {"id": assistant_id, "role": "assistant", "content": result.content, "reasoning": result.reasoning},
                                "model": result.model,
                                "usage": result.raw_usage,
                            })
                except Exception as exc:
                    await db.audit(self.env.DB, int(session["user_id"]), "chat.failed", "conversation", str(conversation_id), {"error": str(exc)[:1200], "stream": True})
                    await emit({"type": "error", "error": "模型推演失败：" + str(exc)[:500]})
                finally:
                    controller.close()

            stream = ReadableStream.new(to_js({"start": create_proxy(start)}))
            return Response(
                stream,
                headers={
                    "Content-Type": "application/x-ndjson; charset=utf-8",
                    "Cache-Control": "no-store, no-transform",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        try:
            result = await minimax_chat(**model_kwargs)
        except Exception as exc:
            await db.audit(self.env.DB, int(session["user_id"]), "chat.failed", "conversation", str(conversation_id), {"error": str(exc)[:1200]})
            return _error("模型推演失败：" + str(exc)[:500], 502)

        assistant_id = await db.add_message(
            self.env.DB,
            conversation_id,
            int(session["user_id"]),
            "assistant",
            result.content,
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.reasoning,
        )
        await db.audit(self.env.DB, int(session["user_id"]), "chat.completed", "message", str(assistant_id), {"model": result.model, "attachments": len(attachments), "usage": result.raw_usage})
        return _json({"message": {"id": assistant_id, "role": "assistant", "content": result.content, "reasoning": result.reasoning}, "model": result.model, "usage": result.raw_usage})

    async def fetch(self, request):
        url = urlparse(request.url)
        path = url.path
        params = parse_qs(url.query)
        method = request.method.upper()

        if path.startswith("/media/") and method == "GET":
            return await self._serve_media(request, path, params)
        if path == "/" and method == "GET":
            return _html(APP_HTML)
        if path == "/health" and method == "GET":
            return _json({"ok": True, "service": "buqiuren", "bazi_engine_commit": BAZI_ENGINE_COMMIT, "multimodal": ["image", "video"], "streaming": True})
        if path == "/wotamade" and method == "GET":
            if not self._admin_ok(request):
                return self._admin_unauthorized()
            return _html(ADMIN_HTML)
        if path.startswith("/api/admin/"):
            if not self._admin_ok(request):
                return self._admin_unauthorized()
            if path == "/api/admin/users" and method == "GET":
                return _json({"items": await db.admin_users(self.env.DB)})
            if path == "/api/admin/user" and method == "GET":
                try:
                    user_id = int((params.get("id") or [""])[0])
                except Exception:
                    return _error("用户参数无效")
                return _json(await db.admin_user_dump(self.env.DB, user_id))
            return _error("Not found", 404)

        if path == "/api/register" and method == "POST":
            return await self._handle_auth(request, "register")
        if path == "/api/login" and method == "POST":
            return await self._handle_auth(request, "login")

        session, auth_error = await self._require_session(request, csrf=method in ("POST", "PUT", "PATCH", "DELETE"))
        if auth_error:
            return auth_error

        if path == "/api/me" and method == "GET":
            return _json({"user": await db.get_user(self.env.DB, int(session["user_id"])), "profile": _profile_public(await db.get_profile(self.env.DB, int(session["user_id"]))), "csrf": session["csrf_token"]})
        if path == "/api/logout" and method == "POST":
            raw = _cookie_value(request, COOKIE_NAME)
            if raw:
                await db.delete_session(self.env.DB, token_hash(raw, self.pepper))
            return _json({"ok": True}, headers={"Set-Cookie": _clear_cookie()})
        if path == "/api/change-password" and method == "POST":
            try:
                body = await request.json()
            except Exception:
                return _error("请求格式无效")
            user = await db.get_user_by_username(self.env.DB, session["username"])
            if not verify_password(str(body.get("old_password") or ""), user.get("password_hash", ""), self.pepper):
                return _error("当前密码不正确", 403)
            try:
                validate_password(str(body.get("new_password") or ""))
            except ValueError as exc:
                return _error(str(exc))
            await db.set_password(self.env.DB, int(session["user_id"]), hash_password(str(body["new_password"]), self.pepper))
            await db.delete_user_sessions(self.env.DB, int(session["user_id"]))
            await db.audit(self.env.DB, int(session["user_id"]), "user.password_changed", "user", str(session["user_id"]))
            return _json({"ok": True}, headers={"Set-Cookie": _clear_cookie()})
        if path == "/api/profile" and method == "PUT":
            try:
                payload = _validate_profile(await request.json())
            except ValueError as exc:
                return _error(str(exc))
            await db.upsert_profile(self.env.DB, int(session["user_id"]), payload)
            await db.invalidate_chart(self.env.DB, int(session["user_id"]))
            await db.audit(self.env.DB, int(session["user_id"]), "profile.updated", "user", str(session["user_id"]), {"calendar_type": payload["calendar_type"], "hour_unknown": payload["birth_hour_unknown"]})
            return _json({"ok": True, "profile": payload})
        if path == "/api/conversations" and method == "GET":
            return _json({"items": await db.list_conversations(self.env.DB, int(session["user_id"]))})
        if path == "/api/conversations" and method == "POST":
            cid = await db.create_conversation(self.env.DB, int(session["user_id"]))
            return _json({"id": cid}, 201)
        if path == "/api/conversation" and method == "GET":
            try:
                cid = int((params.get("id") or [""])[0])
            except Exception:
                return _error("会话参数无效")
            if not await db.get_conversation(self.env.DB, cid, int(session["user_id"])):
                return _error("会话不存在", 404)
            return _json({"messages": await db.history(self.env.DB, cid, int(session["user_id"]), 300)})
        if path == "/api/attachments" and method == "POST":
            return await self._upload(request, session, params)
        if path == "/api/chat" and method == "POST":
            return await self._chat(request, session)

        return _error("Not found", 404)
