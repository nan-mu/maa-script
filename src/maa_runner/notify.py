from __future__ import annotations

from pathlib import Path

import requests

from maa_runner.config import Config
from maa_runner.net import requests_proxies

TG_LIMIT = 4096
API_TIMEOUT = 30


class NotifyError(Exception):
    """Telegram API failure."""


def _proxies(cfg: Config) -> dict[str, str] | None:
    return requests_proxies(cfg.network.proxy)


def _api(cfg: Config, method: str) -> str:
    return f"https://api.telegram.org/bot{cfg.telegram.bot_token}/{method}"


def _call(cfg: Config, method: str, payload: dict | None = None) -> dict:
    try:
        response = requests.post(
            _api(cfg, method),
            json=payload or {},
            proxies=_proxies(cfg),
            timeout=API_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        raise NotifyError(str(exc)) from exc
    if not body.get("ok"):
        raise NotifyError(body.get("description") or f"{method} failed")
    return body.get("result") or {}


def get_me(cfg: Config) -> dict:
    return _call(cfg, "getMe")


def get_chat(cfg: Config) -> dict:
    return _call(cfg, "getChat", {"chat_id": cfg.telegram.chat_id})


def verify(cfg: Config) -> str:
    if not cfg.telegram.enabled:
        raise NotifyError("telegram.enabled must be true")
    if not cfg.telegram.bot_token.strip() or not cfg.telegram.chat_id.strip():
        raise NotifyError("bot_token and chat_id are required")
    me = get_me(cfg)
    chat = get_chat(cfg)
    username = me.get("username") or me.get("id")
    chat_id = chat.get("id") or cfg.telegram.chat_id
    title = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
    extra = f" {title}".rstrip()
    return f"@{username} chat={chat_id}{extra}"


def chunk_text(text: str, limit: int = TG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return chunks


def send_message(cfg: Config, text: str) -> None:
    if not text:
        raise NotifyError("refusing to send empty message")
    _call(
        cfg,
        "sendMessage",
        {
            "chat_id": cfg.telegram.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def send_text(cfg: Config, text: str) -> None:
    for part in chunk_text(text):
        send_message(cfg, part)


def send_document(cfg: Config, path: Path, *, caption: str | None = None) -> None:
    if not path.is_file():
        raise NotifyError(f"document not found: {path}")
    data = {
        "chat_id": cfg.telegram.chat_id,
    }
    if caption:
        data["caption"] = caption[:1024]
    try:
        with path.open("rb") as fh:
            response = requests.post(
                _api(cfg, "sendDocument"),
                data=data,
                files={"document": (path.name, fh)},
                proxies=_proxies(cfg),
                timeout=120,
            )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        raise NotifyError(str(exc)) from exc
    if not body.get("ok"):
        raise NotifyError(body.get("description") or "sendDocument failed")


def send_report(
    cfg: Config,
    text: str,
    *,
    summary_path: Path | None = None,
    attach_summary: bool = False,
    maa_log_path: Path | None = None,
    attach_maa_log: bool = False,
) -> None:
    send_text(cfg, text)
    if attach_summary and summary_path is not None and summary_path.is_file() and summary_path.stat().st_size > 0:
        send_document(cfg, summary_path, caption="MAA summary")
    if attach_maa_log and maa_log_path is not None and maa_log_path.is_file():
        send_document(cfg, maa_log_path, caption="MAA log")
