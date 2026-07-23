"""IMAP fetch for Google Scholar alert mails (stdlib)."""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any

from app.services.scholar.email_settings import load_email_settings


def _decode_header(val: str | None) -> str:
    if not val:
        return ""
    try:
        return str(make_header(decode_header(val)))
    except Exception:
        return val


def _body_text(msg: Message) -> str:
    """Prefer text/html, fall back to text/plain."""
    html_parts: list[str] = []
    plain_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/html":
                html_parts.append(text)
            elif ctype == "text/plain":
                plain_parts.append(text)
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            ctype = (msg.get_content_type() or "").lower()
            if ctype == "text/html":
                html_parts.append(text)
            else:
                plain_parts.append(text)
        except Exception:
            pass
    if html_parts:
        return "\n".join(html_parts)
    return "\n".join(plain_parts)


def test_connection() -> dict[str, Any]:
    """Login + optional SELECT + peek last message subject."""
    cfg = load_email_settings(force=True)
    host = (cfg.get("host") or "").strip()
    port = int(cfg.get("port") or 993)
    user = (cfg.get("user") or "").strip()
    password = (cfg.get("password") or "").strip()
    folder = (cfg.get("folder") or "INBOX").strip() or "INBOX"
    use_ssl = bool(cfg.get("ssl", True))
    if not host or not user or not password:
        return {"ok": False, "message": "请先填写主机、账号与授权码（应用专用密码）"}
    try:
        if use_ssl:
            M = imaplib.IMAP4_SSL(host, port, timeout=30)
        else:
            M = imaplib.IMAP4(host, port, timeout=30)
        try:
            M.login(user, password)
            typ, _ = M.select(folder, readonly=True)
            if typ != "OK":
                return {"ok": False, "message": f"无法打开文件夹 {folder}"}
            typ, data = M.search(None, "ALL")
            ids = (data[0] or b"").split() if data else []
            peek = ""
            if ids:
                last = ids[-1]
                typ, msg_data = M.fetch(last, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
                if typ == "OK" and msg_data and msg_data[0]:
                    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                    if isinstance(raw, bytes):
                        hdr = email.message_from_bytes(raw)
                        peek = (
                            f"From: {_decode_header(hdr.get('From'))} | "
                            f"Subject: {_decode_header(hdr.get('Subject'))}"
                        )
            return {
                "ok": True,
                "message": f"登录成功 · {folder} 共 {len(ids)} 封" + (f" · 最近：{peek[:160]}" if peek else ""),
                "message_count": len(ids),
            }
        finally:
            try:
                M.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as e:
        return {"ok": False, "message": f"IMAP 错误：{e}"}
    except Exception as e:
        return {"ok": False, "message": f"连接失败：{e}"}


def fetch_recent_messages(
    *,
    days: int = 2,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """
    Fetch recent messages likely from Scholar Alerts.
    Returns list of {message_id, subject, from, date, body_html, uid}.
    """
    cfg = load_email_settings(force=True)
    host = (cfg.get("host") or "").strip()
    port = int(cfg.get("port") or 993)
    user = (cfg.get("user") or "").strip()
    password = (cfg.get("password") or "").strip()
    folder = (cfg.get("folder") or "INBOX").strip() or "INBOX"
    use_ssl = bool(cfg.get("ssl", True))
    sender = (cfg.get("sender_filter") or "scholaralerts@google.com").strip().lower()
    if not host or not user or not password:
        raise RuntimeError("邮箱未配置完整")

    if use_ssl:
        M = imaplib.IMAP4_SSL(host, port, timeout=60)
    else:
        M = imaplib.IMAP4(host, port, timeout=60)

    out: list[dict[str, Any]] = []
    try:
        M.login(user, password)
        typ, _ = M.select(folder, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"无法打开文件夹 {folder}")

        # Prefer SINCE + FROM; fall back to broader search
        criteria = f'(FROM "{sender}")' if sender else "ALL"
        try:
            # SINCE DD-Mon-YYYY
            from datetime import date, timedelta

            since = (date.today() - timedelta(days=max(0, days))).strftime("%d-%b-%Y")
            criteria = f'(FROM "{sender}" SINCE {since})' if sender else f"(SINCE {since})"
        except Exception:
            pass

        typ, data = M.search(None, criteria)
        if typ != "OK":
            # fallback: last N
            typ, data = M.search(None, "ALL")
        ids = (data[0] or b"").split() if data else []
        ids = ids[-limit:] if len(ids) > limit else ids

        for mid in reversed(ids):  # newest first
            try:
                typ, msg_data = M.fetch(mid, "(RFC822)")
                if typ != "OK" or not msg_data:
                    continue
                raw = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw = part[1]
                        break
                if not isinstance(raw, bytes):
                    continue
                msg = email.message_from_bytes(raw)
                subj = _decode_header(msg.get("Subject"))
                frm = _decode_header(msg.get("From"))
                date_s = msg.get("Date") or ""
                date_iso = ""
                try:
                    if date_s:
                        date_iso = parsedate_to_datetime(date_s).isoformat()
                except Exception:
                    date_iso = date_s
                body = _body_text(msg)
                # soft filter if sender_filter loose
                blob = f"{frm} {subj}".lower()
                if sender and sender not in blob and "scholar" not in blob:
                    # still allow if subject looks like alert
                    if not re.search(r"scholar|alert|学术|新结果|新引用", subj, re.I):
                        continue
                msgid = (msg.get("Message-ID") or "").strip() or f"imap-{mid.decode() if isinstance(mid, bytes) else mid}"
                out.append(
                    {
                        "message_id": msgid,
                        "uid": mid.decode() if isinstance(mid, bytes) else str(mid),
                        "subject": subj,
                        "from": frm,
                        "date": date_iso,
                        "body": body,
                    }
                )
            except Exception:
                continue
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return out
