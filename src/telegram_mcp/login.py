"""Interactive login: prints a TELEGRAM_SESSION string for account mode."""

import os

from telethon.sessions import StringSession
from telethon.sync import TelegramClient


def main() -> None:
    api_id = os.environ.get("TELEGRAM_API_ID") or input("API ID (my.telegram.org): ")
    api_hash = os.environ.get("TELEGRAM_API_HASH") or input("API hash: ")
    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        session = client.session.save()
        me = client.get_me()
    print(f"\nLogged in as {me.first_name} (@{me.username}).")
    print("Keep this secret — it grants full access to your account:\n")
    print(f"TELEGRAM_SESSION={session}")


if __name__ == "__main__":
    main()
