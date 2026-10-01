# telegram-mcp

MCP-сервер, позволяющий Claude читать посты из Telegram-каналов.

## Два режима

| Режим | Что нужно | Что умеет |
|---|---|---|
| **Публичный** (по умолчанию) | ничего | публичные каналы через веб-превью `t.me/s/<канал>` |
| **Аккаунт** | `api_id`/`api_hash` + сессия | любые каналы, группы и чаты, где состоит ваш аккаунт; список ваших каналов |

Если заданы переменные аккаунта, сервер использует аккаунт; иначе — публичный режим.
В каждом инструменте можно явно выбрать режим параметром `use_account`.

## Инструменты

- `get_channel_posts(channel, limit=20, before_id=None)` — последние посты (новые первыми); `before_id` для пролистывания назад.
- `search_channel_posts(channel, query, limit=20)` — поиск по тексту постов.
- `get_post(channel, post_id)` — один пост (например, из ссылки `https://t.me/durov/545`).
- `list_my_channels(limit=50, channels_only=True)` — каналы/чаты аккаунта (только режим аккаунта).

`channel` принимает `durov`, `@durov`, `https://t.me/durov` или (в режиме аккаунта) числовой id.

## Установка

```bash
git clone <repo> telegram-mcp && cd telegram-mcp
python -m venv .venv && .venv/bin/pip install -e .
```

### Подключение к Claude Code

```bash
claude mcp add telegram -- /абсолютный/путь/telegram-mcp/.venv/bin/telegram-mcp
```

### Подключение к Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "telegram": {
      "command": "/абсолютный/путь/telegram-mcp/.venv/bin/telegram-mcp",
      "env": {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "abcdef...",
        "TELEGRAM_SESSION": "1Aa..."
      }
    }
  }
}
```

Блок `env` нужен только для режима аккаунта.

## Режим аккаунта

1. Получите `api_id` и `api_hash` на https://my.telegram.org → *API development tools*.
2. Выполните вход (спросит телефон и код из Telegram):
   ```bash
   .venv/bin/telegram-mcp-login
   ```
3. Скопируйте выведенную строку `TELEGRAM_SESSION=...` в конфиг.

⚠️ Строка сессии даёт полный доступ к аккаунту — храните её как пароль. Сервер только читает сообщения.

## Тесты

```bash
.venv/bin/pip install pytest && PYTHONPATH=src .venv/bin/pytest
```
