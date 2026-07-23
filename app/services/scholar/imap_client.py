"""IMAP fetch for Google Scholar alert mails (stdlib)."""

from __future__ import annotations

import concurrent.futures
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


def _imap_open(
    host: str,
    port: int,
    *,
    use_ssl: bool,
    timeout: float = 15.0,
) -> imaplib.IMAP4:
    """Open IMAP with a hard socket timeout (avoid hanging on large SEARCH)."""
    # timeout is supported on Python 3.9+ for IMAP4/IMAP4_SSL
    if use_ssl:
        return imaplib.IMAP4_SSL(host, port, timeout=timeout)
    return imaplib.IMAP4(host, port, timeout=timeout)


def _folder_message_count(M: imaplib.IMAP4, folder: str) -> int | None:
    """Prefer STATUS over SEARCH ALL (SEARCH ALL is slow/hangs on large boxes)."""
    try:
        # STATUS needs mailbox name; quote if spaces
        name = folder if re.match(r"^[\w.-]+$", folder) else f'"{folder}"'
        typ, data = M.status(name, "(MESSAGES)")
        if typ == "OK" and data:
            raw = data[0]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            m = re.search(r"MESSAGES\s+(\d+)", str(raw), re.I)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    # SELECT response often has EXISTS in untagged; imaplib stores in M._mbox_size-ish
    try:
        # After select, some servers expose via noop
        typ, data = M.noop()
        void = typ, data
        del void
    except Exception:
        pass
    return None


def test_connection() -> dict[str, Any]:
    """Login + SELECT only (no SEARCH ALL). Fast fail on network hang."""
    cfg = load_email_settings(force=True)
    host = (cfg.get("host") or "").strip()
    port = int(cfg.get("port") or 993)
    user = (cfg.get("user") or "").strip()
    password = (cfg.get("password") or "").strip()
    folder = (cfg.get("folder") or "INBOX").strip() or "INBOX"
    use_ssl = bool(cfg.get("ssl", True))
    if not host or not user or not password:
        return {"ok": False, "message": "请先填写主机、账号与授权码（应用专用密码）"}

    # Overall deadline so the HTTP handler cannot stall past ~18s
    def _run() -> dict[str, Any]:
        M = _imap_open(host, port, use_ssl=use_ssl, timeout=12.0)
        try:
            M.login(user, password)
            typ, data = M.select(folder, readonly=True)
            if typ != "OK":
                return {"ok": False, "message": f"无法打开文件夹 {folder}（检查名称大小写）"}
            count = _folder_message_count(M, folder)
            # Optional light peek: only if count known and small path via UID *
            peek = ""
            try:
                # FETCH the highest recent message without SEARCH ALL
                typ2, data2 = M.fetch(b"*", "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
                if typ2 == "OK" and data2:
                    for part in data2:
                        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
                            hdr = email.message_from_bytes(part[1])
                            peek = (
                                f"From: {_decode_header(hdr.get('From'))} | "
                                f"Subject: {_decode_header(hdr.get('Subject'))}"
                            )
                            break
            except Exception:
                peek = ""
            bits = [f"登录成功 · {folder}"]
            if count is not None:
                bits.append(f"约 {count} 封")
            if peek:
                bits.append(f"最近：{peek[:140]}")
            return {
                "ok": True,
                "message": " · ".join(bits),
                "message_count": count,
            }
        finally:
            try:
                M.logout()
            except Exception:
                try:
                    M.shutdown()
                except Exception:
                    pass

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(_run)
        return fut.result(timeout=18.0)
    except concurrent.futures.TimeoutError:
        return {
            "ok": False,
            "message": (
                "IMAP 测试超时（约 18s）。请检查：① 主机/端口（Gmail: imap.gmail.com:993 SSL）；"
                "② 使用「应用专用密码」而非登录密码；③ 网络/代理是否可访问该主机；"
                "④ 企业邮箱是否需特定 IMAP 地址。"
            ),
        }
    except imaplib.IMAP4.error as e:
        err = str(e)
        hint = ""
        low = err.lower()
        if "auth" in low or "login" in low or "credentials" in low or "invalid" in low:
            hint = "（认证失败：Gmail 请用 16 位应用专用密码，并开启 IMAP）"
        return {"ok": False, "message": f"IMAP 错误：{e}{hint}"}
    except TimeoutError as e:
        return {
            "ok": False,
            "message": f"连接超时：{e}。请确认主机可达且端口未阻断。",
        }
    except OSError as e:
        return {
            "ok": False,
            "message": f"网络错误：{e}。无法连上 {host}:{port}（DNS/防火墙/代理？）",
        }
    except Exception as e:
        return {"ok": False, "message": f"连接失败：{type(e).__name__}: {e}"}
    finally:
        # Do not wait on hung sockets — wait=True would re-block after TimeoutError
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)


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

    # Fetch path: longer timeout than test, but still bounded
    M = _imap_open(host, port, use_ssl=use_ssl, timeout=45.0)

    out: list[dict[str, Any]] = []
    try:
        M.login(user, password)
        typ, _ = M.select(folder, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"无法打开文件夹 {folder}")

        # Prefer SINCE + FROM; NEVER fall back to SEARCH ALL on huge boxes
        from datetime import date, timedelta

        since = (date.today() - timedelta(days=max(0, days))).strftime("%d-%b-%Y")
        attempts = []
        if sender:
            attempts.append(f'(FROM "{sender}" SINCE {since})')
            attempts.append(f'(FROM "{sender}")')
        attempts.append(f"(SINCE {since})")
        # last resort: recent window only via UID — still avoid bare ALL
        attempts.append("RECENT")
        attempts.append("UNSEEN")

        ids: list[bytes] = []
        last_err = ""
        for criteria in attempts:
            try:
                typ, data = M.search(None, criteria)
                if typ == "OK" and data and data[0]:
                    ids = (data[0] or b"").split()
                    if ids:
                        break
            except Exception as e:
                last_err = str(e)
                continue
        if not ids:
            # Final fallback: take the last `limit` sequence numbers without SEARCH ALL
            # by probing STATUS count then FETCH range
            count = _folder_message_count(M, folder) or 0
            if count > 0:
                start = max(1, count - limit + 1)
                ids = [str(i).encode() for i in range(start, count + 1)]
            elif last_err:
                raise RuntimeError(f"邮件搜索失败：{last_err}")
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
