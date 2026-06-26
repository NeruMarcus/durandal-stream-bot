# Durandal Stream Bot

ИИ-комментатор для стримов Marathon на базе GPT-4o-mini (GitHub Models) + edge-tts + RVC.

Скриншот экрана → vision LLM → эмоциональный комментарий → синтез речи → голос Durandal → эмбиент → OBS overlay.

## Возможности

| Режим | Описание |
|-------|----------|
| **Vision commentary** | Каждые 45 с анализирует скриншот (инвентарь/лобби/рейд/эвакуация), пишет цитату Дюрандаля |
| **Twitch чат** | Отвечает на сообщения в чате голосом, учитывает контекст последних 20 сообщений |
| **Overlay** | HTTP-сервер `http://127.0.0.1:9733/overlay`, 845×230, VT323, динамический badge эмоции |
| **RVC голос** | edge-tts (Дмитрий, -25%) → RVC Durandal (e3000, f0up+1) → EQ → эмбиент-дрон |
| **Эмоции** | `sarcastic / angry / mocking / calm / neutral` — влияют на цвет badge и тон комментария |

## Структура проекта

```
stream-bot/
├── core/              # Модуль чата: brain.py (LLM), memory.py (диалоговая память 50)
├── models/
│   └── rvc_webui/     # RVC inference engine (weights, hubert, rmvpe, pretrained)
├── twitch/
│   └── chat.py        # Twitchio бот: чтение/ответ в чате, кулдаун 3 с
├── voice/
│   ├── tts.py         # Пайплайн: edge-tts → 24kHz → RVC → EQ
│   └── audiofx.py     # Микшер: речь + эмбиент-дрон (-12 dB)
├── web/               # (зарезервировано)
├── main.py            # Точка входа: asyncio циклы vision + twitch
├── config.py          # Загрузка .env (токены, интервалы, флаги)
├── personality.py     # Промпты для vision и chat + fallback-фразы
├── overlay_server.py  # HTTP сервер + HTML overlay с эмоциями
├── screen_capture.py  # Захват экрана (PIL, индекс монитора)
├── rvc_convert.py     # Интерфейс к RVC daemon (JSON протокол)
├── rvc_daemon.py      # Постоянный RVC процесс на GPU (запускается в rvc_env)
├── logger.py          # Логирование в stdout + bot.log
├── run.bat            # Запуск бота
├── .env               # Конфигурация (не коммитится)
└── requirements.txt   # Зависимости Python
```

## Установка

### 1. Клонировать и создать окружение

```powershell
git clone https://github.com/nerumarcus/durandal-stream-bot
cd durandal-stream-bot
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### 2. Настроить `.env`

Скопируйте `.env.example` в `.env` и заполните:

```ini
# GitHub Models (https://github.com/settings/tokens)
GITHUB_TOKEN=ghp_ваш_токен

# Twitch (https://twitchtokengenerator.com)
TWITCH_TOKEN=oauth:ваш_токен
TWITCH_CLIENT_ID=ваш_client_id
TWITCH_CHANNEL=ваш_канал
TWITCH_NICK=имя_бота

# RVC
USE_RVC=true

# Интервал комментариев (сек)
COMMENT_INTERVAL=45

# Индекс монитора для захвата (0 = основной)
MONITOR_INDEX=1
```

### 3. RVC (опционально)

Для работы RVC нужна отдельная среда с PyTorch + CUDA:

```powershell
python -m venv rvc_env
rvc_env\Scripts\pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

Модель Durandal (e3000) должна лежать в `models/rvc_webui/assets/weights/`:
- `durandal_v1_40k_e3000_s93000.pth`
- `added_durandal_v1_40k_e3000_s93000.index`

Без RVC (`USE_RVC=false`) будет использоваться чистый edge-tts.

### 4. Запуск

```powershell
run.bat
```

Или напрямую:

```powershell
venv\Scripts\python main.py
```

### 5. OBS overlay

Добавьте **Browser Source**: `http://127.0.0.1:9733/overlay`, размер 845×230, прозрачный фон.

## Требования

- **Python 3.10+**
- **Windows** (winsound, RVC daemon на Windows)
- **FFmpeg** (устанавливается через `imageio-ffmpeg`)
- **Интернет** (edge-tts — Microsoft Cloud TTS; GitHub Models API)

## Работа без Twitch

Оставьте `TWITCH_TOKEN` пустым — бот запустится в режиме офлайн-комментатора (только vision цикл).

## Лицензия

MIT
