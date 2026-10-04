# MOEX Telegram Bot

Бот отслеживает индексы Московской биржи через официальный **ISS MOEX API** и присылает уведомления в Telegram по расписанию (время — `Europe/Moscow`).

| Отображаемое имя | Тикер ISS | Описание |
|---|---|---|
| **MOEX** | `IMOEX` | Индекс МосБиржи — **только основная** торговая сессия |
| **MOEX2** | `IMOEX2` | Индекс МосБиржи за **все сессии**: утренняя, основная, вечерняя, выходного дня |

Тикеры можно переопределить в `.env` (`MOEX_SECID`, `MOEX2_SECID`).

### Логика сессий

- **MOEX2** всегда показывает актуальные данные текущей сессии.
- **MOEX** во время основной сессии — живые котировки.
- Во время **утренней / вечерней / выходной** сессии для **MOEX** выводятся итоги **последнего дня основной сессии** с указанием даты (например: «итоги основной сессии на 10.07.2026»).

---

## Архитектура

```
MOEX_bot/
├── main.py            # точка входа
├── config.py          # настройки из .env
├── moex_api.py        # все запросы к ISS MOEX
├── scheduler.py       # APScheduler: 10:00 / интервал / 19:00 / 00:00
├── telegram_bot.py    # команды и отправка сообщений
├── database.py        # SQLite: chat_id, интервал, антидубли
├── messages.py        # шаблоны уведомлений
├── utils.py           # время МСК, форматирование, логи
├── requirements.txt
├── .env.example       # шаблон настроек (скопировать в .env)
├── data/              # SQLite (создаётся автоматически)
└── logs/bot.log
```

---

## 1. Установка Python

Нужен Python **3.11+** (рекомендуется 3.12/3.13).

Проверка:

```bash
python --version
```

## 2. Виртуальное окружение

```bash
cd MOEX_bot
python -m venv venv
```

Активация:

- Windows (PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

- Windows (cmd):

```cmd
venv\Scripts\activate.bat
```

- Linux / macOS:

```bash
source venv/bin/activate
```

## 3. Зависимости

```bash
pip install -r requirements.txt
```

## 4. Настройка `.env`

Скопируйте шаблон `.env.example` в `.env`:

```powershell
copy .env.example .env
```

Откройте файл `.env` и заполните:

```env
TELEGRAM_TOKEN=123456:ABC...
CHAT_ID=123456789

START_NOTIFICATION_TIME=10:00
END_NOTIFICATION_TIME=19:00
MIDNIGHT_NOTIFICATION_TIME=00:00

DEFAULT_INTERVAL_MINUTES=60
TEST_MODE=false
```

### Где взять Telegram Bot Token

1. Откройте [@BotFather](https://t.me/BotFather)
2. Команда `/newbot` (или возьмите токен существующего бота)
3. Скопируйте токен в `TELEGRAM_TOKEN`

### Как узнать CHAT_ID

Вариант A (рекомендуется):

1. Запустите бота
2. Напишите ему `/start`
3. Бот сохранит ваш `chat_id` в SQLite и покажет его в ответе

Вариант B:

1. Напишите боту любое сообщение
2. Откройте в браузере:  
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Найдите `"chat":{"id": ...}` и пропишите в `CHAT_ID`

`CHAT_ID` в `.env` нужен, чтобы бот знал получателя ещё до первого `/start` (например, для фоновых уведомлений сразу после запуска).

---

## 5. Запуск

```bash
python main.py
```

Логи пишутся в консоль и в `logs/bot.log`.

---

## Расписание уведомлений

Все времена — **московские** (`Europe/Moscow`).

| Время | Событие |
|---|---|
| `10:00` | Проверка торгового дня. Если торгов нет → «Сегодня торгов нет» и тишина до завтра. Если есть → «Утренняя сессия MOEX2» |
| каждые N минут | Текущие котировки MOEX + MOEX2 (изменение к открытию дня) |
| `19:00` | «Итоги дневных торгов» |
| `00:00` | «Итоги торгового дня» |

Источник данных:  
`https://iss.moex.com/iss/engines/stock/markets/index/securities/{SECID}.json`

---

## Изменение интервала

Допустимые значения: **30, 60, 120, 180, 240** минут.

В Telegram:

```text
/setinterval 60
```

Ответ:

```text
Интервал уведомлений изменен: 60 минут
```

Либо задайте `DEFAULT_INTERVAL_MINUTES` в `.env` и перезапустите бота.

---

## Интерфейс Telegram

Главное меню (ReplyKeyboard):

1. **📊 Текущие котировки** — статус MOEX/MOEX2 + график MOEX2 за 24 часа  
2. **🔔 Настройки алертов** — цель по уровню или по %, частота проверки (по умолчанию 30 мин)  
3. **⚙️ Параметры уведомлений** — вкл/выкл слотов и интервал рассылки  

Все настройки меняются **Inline-кнопками**. Команды `/start` и `/help` — только технические.

---

## Тестовый режим (без ожидания 10:00 / 19:00)

1. В `.env` поставьте:

```env
TEST_MODE=true
CHAT_ID=ваш_chat_id
```

2. Запустите:

```bash
python main.py
```

3. Через ~3 секунды бот один раз прогонит:
   - утреннюю задачу
   - интервальную (если текущее время внутри окна 10:00–19:00)
   - вечернюю задачу

Дополнительно можно в любой момент вызвать `/status`.

После проверки верните `TEST_MODE=false`.

### Ручной smoke-тест API без Telegram

```bash
python -c "import asyncio; from moex_api import get_both_indices, is_trading_day; 
async def t():
  print('trading', await is_trading_day())
  m,m2=await get_both_indices()
  print(m); print(m2)
asyncio.run(t())"
```

---

## Надёжность

- Повторные попытки запросов к ISS (3 раза)
- Логирование ошибок в `logs/bot.log`
- Защита от дублей уведомлений (таблица `sent_notifications`)
-Timezone-aware время только через `Europe/Moscow`

---

## Важно

- Не запускайте два polling-процесса с одним `TELEGRAM_TOKEN` одновременно.
- Не публикуйте `.env` и токен в git.
