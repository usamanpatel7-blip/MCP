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

| Инструмент | Зачем |
|---|---|
| `get_digest(channels, since="24h")` | «Что нового?» — посты из нескольких каналов за период одним вызовом, отсортированы по времени, с ошибками по каждому каналу отдельно |
| `get_channel_posts(channel, limit, since, before_id)` | Лента канала; `since` = `24h`, `7d`, `2w` или `2026-09-01` |
| `search_channel_posts(channel, query)` | Поиск по тексту постов |
| `get_post(link)` | Полный текст поста по ссылке `https://t.me/durov/545` |
| `get_channel_info(channel)` | Название, описание, подписчики, дата последнего поста |
| `list_my_channels()` | Ваши каналы с числом непрочитанных (режим аккаунта) |

Промпт `digest` (в Claude Desktop — через меню «+») делает сводку новостей с группировкой по темам и ссылками на посты.

**Экономия контекста:** по умолчанию посты отдаются компактным текстом и обрезаются (`max_chars`, 600 в дайджесте и 1500 в ленте). Полный текст — через `get_post`, все поля — `format="json"`.

**Каналы по умолчанию:** задайте `TELEGRAM_CHANNELS="durov,telegram,..."`, и вопрос «что нового в моих каналах за неделю?» заработает без перечисления каналов.

Примеры запросов к Claude:
- «Что нового в моих каналах за 3 дня? Сгруппируй по темам»
- «Найди в @durov всё про TON за последний год»
- «Перескажи https://t.me/durov/545»

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
        "TELEGRAM_SESSION": "1Aa...",
        "TELEGRAM_CHANNELS": "durov,telegram"
      }
    }
  }
}
```

Переменные `TELEGRAM_API_*`/`TELEGRAM_SESSION` нужны только для режима аккаунта; `TELEGRAM_CHANNELS` необязательна.

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
