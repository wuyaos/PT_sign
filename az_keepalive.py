#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron: 17 3 * * 0
new Env('AnimeZ保活');

青龙环境变量:
AZ_KEEPALIVE_CONFIG

最简配置:
{
  "rss_url": "https://animez.to/your-private-rss",
  "qbittorrent": {
    "url": "http://127.0.0.1:8080"
  }
}

按需覆盖 qB 配置:
{
  "rss_url": "https://animez.to/your-private-rss",
  "qbittorrent": {
    "url": "http://127.0.0.1:8080",
    "username": "admin",
    "password": "adminadmin",
    "category": "AnimeZ",
    "tags": "keepalive"
  }
}
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import feedparser
except ImportError:
    feedparser = None

try:
    import requests
except ImportError:
    requests = None

try:
    from torf import Torrent
except ImportError:
    Torrent = None

try:
    from notify import send as ql_send
except ImportError:
    ql_send = None


ENV_CONFIG = "AZ_KEEPALIVE_CONFIG"
DEFAULT_USER_AGENT = "AZ_KeepAlive/1.0"
DEFAULT_CATEGORY = "AnimeZ"
DEFAULT_TAGS = "keepalive"
DOWNLOAD_DIR = Path("downloads")
STATE_FILE = Path("state/downloads.json")
MAX_HISTORY_ENTRIES = 100
REQUEST_HEADERS = {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://animez.to/"}


@dataclass(frozen=True)
class FeedItem:
    title: str
    url: str
    seeders: int | None
    size_bytes: int | None
    size_text: str


@dataclass(frozen=True)
class QBittorrentSettings:
    url: str
    username: str
    password: str
    category: str
    tags: str


@dataclass(frozen=True)
class Settings:
    rss_url: str
    keepalive_interval_days: int
    refresh_interval_seconds: int
    timeout_seconds: int
    max_items_scan: int
    min_seeders: int
    qbittorrent: QBittorrentSettings


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def iso_time(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_settings() -> Settings:
    env_value = os.environ.get(ENV_CONFIG, "").strip()
    if not env_value:
        raise ValueError(
            f"Missing {ENV_CONFIG}. Set it in QingLong with rss_url and qbittorrent.url."
        )
    return load_settings_from_dict(json.loads(env_value))


def load_settings_from_dict(config: dict[str, Any]) -> Settings:
    if not isinstance(config, dict):
        raise ValueError(f"{ENV_CONFIG} must be a JSON object")

    rss_url = str(config.get("rss_url", "")).strip()
    if not rss_url:
        raise ValueError(f"{ENV_CONFIG}.rss_url is required")

    keepalive_interval_days = int(
        config.get("keepalive_interval_days", config.get("interval_days", 75))
    )
    if keepalive_interval_days <= 0 or keepalive_interval_days >= 90:
        raise ValueError("keepalive_interval_days must be between 1 and 89")

    refresh_interval_minutes = int(config.get("refresh_interval_minutes", 1440))
    if refresh_interval_minutes <= 0:
        raise ValueError("refresh_interval_minutes must be positive")

    timeout_seconds = int(config.get("timeout_seconds", 30))
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    max_items_scan = int(config.get("max_items_scan", 50))
    if max_items_scan <= 0:
        raise ValueError("max_items_scan must be positive")

    min_seeders = int(config.get("min_seeders", 5))
    if min_seeders < 0:
        raise ValueError("min_seeders must be zero or positive")

    qb_config = config.get("qbittorrent", {})
    if not isinstance(qb_config, dict):
        raise ValueError(f"{ENV_CONFIG}.qbittorrent must be a JSON object")
    qb_url = str(qb_config.get("url", "")).strip().rstrip("/")
    if not qb_url:
        raise ValueError(f"{ENV_CONFIG}.qbittorrent.url is required")

    return Settings(
        rss_url=rss_url,
        keepalive_interval_days=keepalive_interval_days,
        refresh_interval_seconds=refresh_interval_minutes * 60,
        timeout_seconds=timeout_seconds,
        max_items_scan=max_items_scan,
        min_seeders=min_seeders,
        qbittorrent=QBittorrentSettings(
            url=qb_url,
            username=str(qb_config.get("username", "")).strip(),
            password=str(qb_config.get("password", "")).strip(),
            category=str(qb_config.get("category", DEFAULT_CATEGORY)).strip()
            or DEFAULT_CATEGORY,
            tags=str(qb_config.get("tags", DEFAULT_TAGS)).strip() or DEFAULT_TAGS,
        ),
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return normalize_state({})
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"State file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"State file must contain a JSON object: {path}")
    return normalize_state(data)


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    history = state.get("history", [])
    if not isinstance(history, list):
        history = []
    state["history"] = history
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


def parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def should_parse_rss(
    state: dict[str, Any], settings: Settings, now: dt.datetime
) -> tuple[bool, str]:
    last_checked = parse_timestamp(state.get("last_checked_at"))
    if last_checked is not None:
        elapsed = now - last_checked
        if elapsed < dt.timedelta(seconds=settings.refresh_interval_seconds):
            return False, "未到 RSS 刷新间隔"

    last_success = parse_timestamp(state.get("last_success_at"))
    if last_success is None:
        return True, "无历史成功记录"

    elapsed_success = now - last_success
    if elapsed_success >= dt.timedelta(days=settings.keepalive_interval_days):
        return True, "已到保活窗口"
    return False, "未到保活窗口"


def require_requests() -> Any:
    if requests is None:
        raise RuntimeError("Missing dependency: requests. Install with: pip install requests")
    return requests


def require_feedparser() -> Any:
    if feedparser is None:
        raise RuntimeError(
            "Missing dependency: feedparser. Install with: pip install feedparser"
        )
    return feedparser


def require_torf() -> Any:
    if Torrent is None:
        raise RuntimeError("Missing dependency: torf. Install with: pip install torf")
    return Torrent


def fetch_text(url: str, settings: Settings) -> str:
    req = require_requests()
    response = req.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def fetch_bytes(url: str, settings: Settings) -> tuple[bytes, str]:
    req = require_requests()
    response = req.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    return response.content, response.headers.get("Content-Type", "")


def parse_feed(xml_text: str, max_items: int) -> list[FeedItem]:
    parser = require_feedparser()
    feed = parser.parse(xml_text)
    entries = list(feed.entries or [])[:max_items]
    items: list[FeedItem] = []
    for entry in entries:
        url = torrent_url_from_entry(entry)
        if not url:
            continue
        title = collapse_whitespace(str(entry.get("title") or "untitled"))
        size_bytes, size_text = parse_size_from_entry(entry)
        items.append(
            FeedItem(
                title=title,
                url=url,
                seeders=parse_seeders_from_entry(entry),
                size_bytes=size_bytes,
                size_text=size_text,
            )
        )
    return items


def torrent_url_from_entry(entry: Any) -> str:
    enclosures = entry.get("enclosures", []) or []
    for enclosure in enclosures:
        href = str(enclosure.get("href") or enclosure.get("url") or "").strip()
        if href:
            return href

    links = entry.get("links", []) or []
    for link in links:
        href = str(link.get("href") or "").strip()
        link_type = str(link.get("type") or "").lower()
        if href and ("bittorrent" in link_type or is_download_like_url(href)):
            return href

    link = str(entry.get("link") or "").strip()
    return link


def is_download_like_url(url: str) -> bool:
    lower = url.lower()
    return ".torrent" in lower or "download" in lower or "dl.php" in lower


def parse_seeders_from_entry(entry: Any) -> int | None:
    value = value_from_entry(entry, {"seed", "seeds", "seeder", "seeders"})
    if value is None:
        return None
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group(0)) if match else None


def parse_size_from_entry(entry: Any) -> tuple[int | None, str]:
    value = value_from_entry(
        entry, {"size", "length", "contentlength", "content_length"}
    )
    if value is None:
        for enclosure in entry.get("enclosures", []) or []:
            value = (
                enclosure.get("length")
                or enclosure.get("size")
                or enclosure.get("content_length")
            )
            if value is not None:
                break

    if value is None:
        return None, ""
    size_text = str(value).strip()
    return parse_size_bytes(size_text), size_text


def value_from_entry(entry: Any, names: set[str]) -> Any:
    normalized_targets = {normalize_key(name) for name in names}
    for key, value in entry.items():
        normalized = normalize_key(str(key))
        if normalized in normalized_targets:
            return value
        if any(normalized.endswith(f"_{target}") for target in normalized_targets):
            return value
    return None


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def parse_size_bytes(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    numeric_only = re.fullmatch(r"\d+", text.replace(",", ""))
    if numeric_only:
        return int(text.replace(",", ""))

    match = re.search(r"([\d,.]+)\s*([kmgtp]?i?b|[kmgtp])?", text, re.I)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "b").lower()
    multipliers = {
        "b": 1,
        "k": 1000,
        "kb": 1000,
        "m": 1000**2,
        "mb": 1000**2,
        "g": 1000**3,
        "gb": 1000**3,
        "t": 1000**4,
        "tb": 1000**4,
        "p": 1000**5,
        "pb": 1000**5,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "pib": 1024**5,
    }
    return int(number * multipliers.get(unit, 1))


def format_size(size_bytes: int | None, fallback: str = "") -> str:
    if size_bytes is None:
        return fallback or "未知"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return str(size_bytes)


def format_size_gb(size_bytes: int | None, fallback: str = "") -> str:
    if size_bytes is None:
        return fallback or "未知"
    return f"{size_bytes / 1024**3:.2f}GB"


def log_detail(message: str) -> None:
    print(f"[运行] {message}")


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def sorted_eligible_items(items: list[FeedItem], min_seeders: int) -> list[FeedItem]:
    eligible = [
        item
        for item in items
        if item.seeders is not None
        and item.seeders >= min_seeders
        and item.size_bytes is not None
    ]
    eligible.sort(key=lambda item: (item.size_bytes or 0, -(item.seeders or 0), item.title))
    return eligible


def safe_filename(title: str, suffix: str = ".torrent") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._-")
    return (cleaned or "animez")[:120] + suffix


def looks_like_torrent(body: bytes, content_type: str) -> bool:
    lowered_type = content_type.lower()
    stripped = body.lstrip()
    if "text/html" in lowered_type or stripped.startswith(b"<!DOCTYPE html"):
        return False
    return stripped.startswith(b"d") and b"announce" in body[:4096]


def write_torrent(settings: Settings, item: FeedItem, body: bytes) -> Path:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    path = DOWNLOAD_DIR / f"{timestamp}_{safe_filename(item.title)}"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def create_qbittorrent_session(settings: Settings) -> Any:
    qb = settings.qbittorrent
    req = require_requests()
    session = req.Session()
    if qb.username or qb.password:
        log_detail(f"登录 qBittorrent: {qb.url}")
        login_qbittorrent(session, settings)
    else:
        log_detail(f"使用无账号 qBittorrent 会话: {qb.url}")
    return session


def login_qbittorrent(session: Any, settings: Settings) -> None:
    qb = settings.qbittorrent
    response = session.post(
        f"{qb.url}/api/v2/auth/login",
        data={"username": qb.username, "password": qb.password},
        headers={"Referer": qb.url, "User-Agent": DEFAULT_USER_AGENT},
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    if response.text.strip() not in {"Ok", "Ok."}:
        raise RuntimeError(f"qBittorrent login failed: {response.text.strip() or 'empty response'}")


def submit_torrent_to_qbittorrent(
    session: Any, settings: Settings, torrent_path: Path
) -> None:
    qb = settings.qbittorrent
    data = {
        "category": qb.category,
        "tags": qb.tags,
    }

    with torrent_path.open("rb") as handle:
        response = session.post(
            f"{qb.url}/api/v2/torrents/add",
            data=data,
            files={
                "torrents": (
                    torrent_path.name,
                    handle,
                    "application/x-bittorrent",
                )
            },
            headers={"Referer": qb.url, "User-Agent": DEFAULT_USER_AGENT},
            timeout=settings.timeout_seconds,
        )
    response.raise_for_status()
    body = response.text.strip()
    if body and body != "Ok.":
        raise RuntimeError(f"qBittorrent rejected torrent: {body}")


def torrent_infohash(torrent_path: Path) -> str:
    torrent_cls = require_torf()
    torrent = torrent_cls.read(torrent_path)
    return str(torrent.infohash).lower()


def qbittorrent_has_hash(session: Any, settings: Settings, infohash: str) -> bool:
    response = session.get(
        f"{settings.qbittorrent.url}/api/v2/torrents/info",
        params={"hashes": infohash},
        headers={
            "Referer": settings.qbittorrent.url,
            "User-Agent": DEFAULT_USER_AGENT,
        },
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("qBittorrent torrents/info returned non-list response")
    return any(str(item.get("hash", "")).lower() == infohash for item in data)


def choose_downloadable_candidate(
    eligible: list[FeedItem],
    settings: Settings,
) -> tuple[FeedItem | None, Path | None, str, list[dict[str, Any]]]:
    session = create_qbittorrent_session(settings)
    skipped: list[dict[str, Any]] = []
    last_error = ""

    for index, item in enumerate(eligible, 1):
        log_detail(
            f"检查候选 {index}/{len(eligible)}: {item.title} | "
            f"体积={format_size_gb(item.size_bytes)} | 做种={item.seeders}"
        )
        body, content_type = fetch_bytes(item.url, settings)
        if not looks_like_torrent(body, content_type):
            last_error = "downloaded response is not a torrent"
            log_detail(f"跳过候选: {item.title} | {last_error}")
            skipped.append({"title": item.title, "reason": last_error})
            continue

        torrent_path = write_torrent(settings, item, body)
        infohash = torrent_infohash(torrent_path)
        log_detail(f"已下载并解析 infohash: {infohash}")
        if qbittorrent_has_hash(session, settings, infohash):
            log_detail(f"qBittorrent 已存在，跳过: {item.title}")
            skipped.append(
                {
                    "title": item.title,
                    "reason": "already exists in qBittorrent",
                    "infohash": infohash,
                }
            )
            try:
                torrent_path.unlink()
            except FileNotFoundError:
                pass
            continue

        log_detail(
            f"提交 qBittorrent: 分类={settings.qbittorrent.category} | "
            f"标签={settings.qbittorrent.tags}"
        )
        submit_torrent_to_qbittorrent(session, settings, torrent_path)
        log_detail(f"提交成功: {item.title}")
        return item, torrent_path, infohash, skipped

    if not last_error and skipped:
        last_error = "all eligible torrents already exist in qBittorrent"
    return None, None, last_error or "no downloadable torrent", skipped


def append_history(
    state: dict[str, Any],
    status: str,
    now: dt.datetime,
    reason: str = "",
    item: FeedItem | None = None,
    torrent_path: Path | None = None,
    settings: Settings | None = None,
    skipped_candidates: list[dict[str, Any]] | None = None,
    infohash: str = "",
) -> None:
    event: dict[str, Any] = {
        "time": iso_time(now),
        "status": status,
    }
    if reason:
        event["reason"] = reason
    if item is not None:
        event.update(
            {
                "title": item.title,
                "url": item.url,
                "seeders": item.seeders,
                "size_bytes": item.size_bytes,
                "size_text": format_size_gb(item.size_bytes, item.size_text),
            }
        )
    if torrent_path is not None:
        event["torrent_file"] = str(torrent_path)
    if infohash:
        event["infohash"] = infohash
    if skipped_candidates:
        event["skipped_candidates"] = skipped_candidates
    if settings is not None:
        event["qb_category"] = settings.qbittorrent.category
        event["qb_tags"] = settings.qbittorrent.tags

    history = state.setdefault("history", [])
    history.append(event)
    del history[:-MAX_HISTORY_ENTRIES]
    state["last_status"] = status
    if status == "success":
        state["last_success_at"] = iso_time(now)
        if item is not None:
            state["last_title"] = item.title
    if status in {"success", "no_candidate", "skipped"}:
        state["last_checked_at"] = iso_time(now)


def build_skip_message(
    state: dict[str, Any], settings: Settings, now: dt.datetime, reason: str
) -> str:
    last_success = parse_timestamp(state.get("last_success_at"))
    next_time = (
        iso_time(last_success + dt.timedelta(days=settings.keepalive_interval_days))
        if last_success
        else "未知"
    )
    return "\n".join(
        [
            "状态：跳过",
            f"原因：{reason}",
            f"上次成功：{state.get('last_success_at') or '无'}",
            f"下次保活窗口：{next_time}",
            f"检查时间：{iso_time(now)}",
        ]
    )


def build_no_candidate_message(
    settings: Settings,
    scanned_count: int,
    eligible_count: int,
    now: dt.datetime,
    reason: str = "",
    skipped_candidates: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        "状态：未下载",
        f"原因：{reason or f'没有找到 seeds >= {settings.min_seeders} 且带体积信息的候选种子'}",
        f"扫描条目：{scanned_count}",
        f"候选条目：{eligible_count}",
        f"检查时间：{iso_time(now)}",
    ]
    if skipped_candidates:
        lines.append("已跳过候选：")
        for candidate in skipped_candidates[:5]:
            title = candidate.get("title", "unknown")
            skip_reason = candidate.get("reason", "unknown")
            lines.append(f"- {title}: {skip_reason}")
    return "\n".join(lines)


def build_success_message(
    item: FeedItem,
    path: Path,
    settings: Settings,
    now: dt.datetime,
    skipped_candidates: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        "状态：成功",
        f"种子：{item.title}",
        f"体积：{format_size_gb(item.size_bytes, item.size_text)}",
        f"做种：{item.seeders}",
        f"qB分类：{settings.qbittorrent.category}",
        f"qB标签：{settings.qbittorrent.tags}",
        f"时间：{iso_time(now)}",
    ]
    if skipped_candidates:
        lines.append(f"qB已存在跳过：{len(skipped_candidates)} 个候选")
    return "\n".join(lines)


def build_failure_message(stage: str, reason: str, item: FeedItem | None = None) -> str:
    lines = ["状态：失败", f"阶段：{stage}", f"原因：{reason}"]
    if item is not None:
        lines.extend(
            [
                f"种子：{item.title}",
                f"体积：{format_size_gb(item.size_bytes, item.size_text)}",
                f"做种：{item.seeders}",
            ]
        )
    return "\n".join(lines)


def send_report(title: str, content: str) -> None:
    if ql_send is None:
        log_detail(f"未检测到 notify.py，跳过通知发送: {title}")
        return
    try:
        ql_send(title, content)
    except Exception as exc:
        print(f"Notification failed: {exc}", file=sys.stderr)


def emit_report(title: str, content: str, *, error: bool = False) -> None:
    if ql_send is None:
        print(content, file=sys.stderr if error else sys.stdout)
    send_report(title, content)


def run(settings: Settings) -> int:
    now = utc_now()
    log_detail(f"开始检查: {iso_time(now)}")
    state = load_state(STATE_FILE)
    log_detail(f"读取状态文件: {STATE_FILE}")
    should_parse, reason = should_parse_rss(state, settings, now)
    log_detail(f"RSS 判断: {reason}")
    if not should_parse:
        append_history(state, "skipped", now, reason=reason)
        save_state(STATE_FILE, state)
        log_detail("无需解析 RSS，本次结束")
        message = build_skip_message(state, settings, now, reason)
        emit_report("AnimeZ保活", message)
        return 0

    stage = "解析 RSS"
    selected: FeedItem | None = None
    try:
        log_detail("开始拉取 RSS")
        feed_text = fetch_text(settings.rss_url, settings)
        items = parse_feed(feed_text, settings.max_items_scan)
        log_detail(f"RSS 解析完成: 扫描条目={len(items)}")
        eligible = sorted_eligible_items(items, settings.min_seeders)
        log_detail(
            f"候选筛选完成: 符合 seeders>={settings.min_seeders} 且带体积信息={len(eligible)}"
        )
        if not eligible:
            append_history(
                state,
                "no_candidate",
                now,
                reason="no eligible torrent",
                settings=settings,
            )
            save_state(STATE_FILE, state)
            log_detail("没有可提交候选，本次结束")
            message = build_no_candidate_message(settings, len(items), len(eligible), now)
            emit_report("AnimeZ保活", message)
            return 0

        stage = "下载 torrent / 检查 qB / 提交 qB"
        selected, torrent_path, infohash, skipped_candidates = choose_downloadable_candidate(
            eligible, settings
        )
        if selected is None or torrent_path is None:
            append_history(
                state,
                "no_candidate",
                now,
                reason=infohash,
                settings=settings,
                skipped_candidates=skipped_candidates,
            )
            save_state(STATE_FILE, state)
            log_detail(f"所有候选均不可提交: {infohash}")
            message = build_no_candidate_message(
                settings,
                len(items),
                len(eligible),
                now,
                reason=infohash,
                skipped_candidates=skipped_candidates,
            )
            emit_report("AnimeZ保活", message)
            return 0

        append_history(
            state,
            "success",
            now,
            item=selected,
            torrent_path=torrent_path,
            settings=settings,
            skipped_candidates=skipped_candidates,
            infohash=infohash,
        )
        save_state(STATE_FILE, state)
        log_detail("状态文件已更新")
        message = build_success_message(
            selected, torrent_path, settings, now, skipped_candidates
        )
        emit_report("AnimeZ保活", message)
        return 0
    except Exception as exc:
        append_history(
            state,
            "failed",
            now,
            reason=f"{stage}: {exc}",
            item=selected,
            settings=settings,
        )
        save_state(STATE_FILE, state)
        log_detail(f"运行失败: {stage}: {exc}")
        message = build_failure_message(stage, str(exc), selected)
        emit_report("AnimeZ保活失败", message, error=True)
        return 2


def main() -> int:
    try:
        settings = load_settings()
        return run(settings)
    except KeyboardInterrupt:
        print("Stopped")
        return 130
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        message = str(exc)
        emit_report("AnimeZ保活失败", f"ERROR: {message}", error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
