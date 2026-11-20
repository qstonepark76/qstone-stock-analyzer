#!/usr/bin/env python3
"""Read-only hourly Telegram public-channel collector for Q Stone Park.

Required environment:
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION
Optional:
  TELEGRAM_CHANNELS (comma-separated usernames; defaults to the three approved channels)
The collector stores text/captions and metadata only; it does not download media.
"""
import asyncio
import json
import os
import hashlib
import datetime as dt
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

OUT = Path("data")
OUT.mkdir(exist_ok=True)
MESSAGES_FILE = OUT / "telegram_messages.json"
STATE_FILE = OUT / "telegram_state.json"
DEFAULT_CHANNELS = ["bumgore", "globalmktinsight", "HanaResearch"]


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def main():
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    session = os.getenv("TELEGRAM_SESSION", "").strip()
    if not (api_id and api_hash and session):
        raise SystemExit(
            "Telegram credentials missing. Configure TELEGRAM_API_ID, "
            "TELEGRAM_API_HASH and TELEGRAM_SESSION as GitHub Actions secrets."
        )

    try:
        api_id = int(api_id)
    except ValueError:
        raise SystemExit("TELEGRAM_API_ID must be an integer.")

    channels = [x.strip().lstrip("@") for x in
                os.getenv("TELEGRAM_CHANNELS", ",".join(DEFAULT_CHANNELS)).split(",") if x.strip()]
    messages = load_json(MESSAGES_FILE, [])
    state = load_json(STATE_FILE, {})
    known = {str(x.get("message_key")) for x in messages}
    added = 0
    errors = []

    client = TelegramClient(StringSession(session), api_id, api_hash)
    await client.start()
    try:
        for username in channels:
            try:
                entity = await client.get_entity(username)
                channel_id = str(getattr(entity, "id", username))
                last_id = int(state.get(username, {}).get("last_message_id", 0))
                newest_id = last_id
                async for msg in client.iter_messages(entity, min_id=last_id, reverse=True, limit=500):
                    newest_id = max(newest_id, int(msg.id))
                    body = (msg.message or "").strip()
                    if not body:
                        continue
                    key = f"{channel_id}:{msg.id}"
                    if key in known:
                        continue
                    date = msg.date.astimezone(dt.timezone.utc).isoformat() if msg.date else None
                    record = {
                        "message_key": key,
                        "channel_username": username,
                        "channel_title": getattr(entity, "title", username),
                        "channel_id": channel_id,
                        "message_id": int(msg.id),
                        "published_at": date,
                        "text": body[:20000],
                        "has_media": bool(msg.media),
                        "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                        "permalink": f"https://t.me/{username}/{msg.id}",
                        "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }
                    messages.append(record)
                    known.add(key)
                    added += 1
                state[username] = {
                    "last_message_id": max(last_id, newest_id),
                    "last_checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "channel_id": channel_id,
                }
                print(f"[TELEGRAM] @{username}: 신규 {added}건 누적")
            except Exception as exc:
                errors.append(f"@{username}: {type(exc).__name__}: {str(exc)[:240]}")
                print(f"[TELEGRAM ERROR] @{username}: {str(exc)[:240]}")
    finally:
        await client.disconnect()

    messages.sort(key=lambda x: (x.get("published_at") or "", x.get("message_key") or ""))
    save_json(MESSAGES_FILE, messages)
    save_json(STATE_FILE, state)
    summary = {
        "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "channels": channels,
        "total_messages": len(messages),
        "new_messages": added,
        "errors": errors,
    }
    save_json(OUT / "telegram_collection_status.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    if errors and not added and not messages:
        raise RuntimeError("No Telegram data collected; see channel errors above.")


if __name__ == "__main__":
    asyncio.run(main())
