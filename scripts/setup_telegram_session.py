#!/usr/bin/env python3
"""Run locally once to create a Telethon StringSession for GitHub Actions.

Do not share the printed session string. Store it only as the TELEGRAM_SESSION
GitHub Actions secret. Never commit it to the repository.
"""
import asyncio
import os
from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in your local environment first.")
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.start()
    try:
        print("\n아래 세션 문자열은 비밀번호와 같은 비밀정보입니다.")
        print("GitHub Actions secret TELEGRAM_SESSION에만 저장하고, 채팅/코드/로그에 공유하지 마세요.\n")
        print(client.session.save())
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
