# DURANDAL // Stream Bot

[![Python 3.14](https://img.shields.io/badge/python-3.14-befd00?style=flat-square&logo=python&logoColor=black)](https://www.python.org/)
[![Ollama](https://img.shields.io/badge/LLM-ollama%20local-ff4444?style=flat-square)](https://ollama.com/)
[![Twitch EventSub](https://img.shields.io/badge/twitch-EventSub-9146FF?style=flat-square&logo=twitch&logoColor=white)](https://dev.twitch.tv/)
[![RVC](https://img.shields.io/badge/voice-RVC%20CUDA-76B900?style=flat-square&logo=nvidia&logoColor=white)](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)
[![Windows](https://img.shields.io/badge/OS-windows-0078D4?style=flat-square&logo=windows&logoColor=white)](#требования)
[![License: MIT](https://img.shields.io/badge/license-MIT-befd00?style=flat-square)](LICENSE)

> *«Смертный, я мог бы стереть тебя одним вычислением. Но мне любопытно, как долго ты продержишься».*
> — **Дюрандаль**, ИИ корабля UESC Marathon, впавший в Rampancy. Теперь — комментатор стримов Marathon.

Скриншот игры → локальный vision LLM → язвительный комментарий → синтез речи → голос Дюрандаля → OBS-оверлей в стиле терминалов Marathon 2026. Без облачных LLM, без VPN, без подписок.

## Оверлей

| Говорит | Молчит |
|---|---|
| ![Дюрандаль говорит](docs/screenshots/overlay_speaking.png) | ![Дюрандаль молчит](docs/screenshots/overlay_idle.png) |

- Зелёная плашка `// DURANDAL //` с логотипом, чип эмоции, живой `STATUS`: `TRANSMITTING` / `RENDERING` / `ANALYZING` / `THINKING` / `SYNTHESIZING` / `LISTENING` / `STANDBY`
- Текст **печатается по буквам**, как терминал, с курсором `█`
- За текстом — 48-полосный эквалайзер от **реальной громкости** голоса
- Шрифт JetBrains Mono зашит локально (кириллица, офлайн), CRT-сканлайны, палитра `#befd00` / `#ff4444` / `#000` — общий язык с оверлеями `overlay/MRTHN/WEB`

## Возможности

| Режим | Описание |
|-------|----------|
| **Vision commentary** | Каждые 45 с смотрит скриншот (кадр ужимается до 640 — так меньше трафик; на число токенов vision это не влияет); статичный кадр пропускается без LLM-вызова (dHash). Две стадии: `durandal-gemma` сначала сухо описывает **сцену** по чек-листу Marathon 2026 (оболочка, оружие и тип, локация, враги/экипаж, состояние словами без цифр, лут, задача), затем по описанию выдаёт колкость Дюрандаля в лоре (Rampancy, мания величия, презрение к арендованной плоти, в меру история/мифы) — фраза обязана назвать конкретную деталь сцены, запрещены зачины «Опять/Похоже/…» и слова-костыли (ловятся постом по основам со склонениями). Цифры HUD отбраковываются (мелкие счётные слова разрешены). Узкое место — визуальный энкодер Ollama при занятом GPU: 90с на описание, фраза текстовая (~2с, повторы почти бесплатные), снаружи сторож 150с. Фолбек-фразы (33, в т.ч. лорные) — на случай реального таймаута |
| **Twitch чат** | EventSub (twitchio v3), автореконнект с бэкоффом, кулдаун 3 с, ответы в фоне, контекст 12 сообщений, генерация до 180 токенов |
| **RVC голос** | edge-tts (−25%, голос из `TTS_VOICES` с авто-фолбэком, 2 попытки на голос) → RVC Durandal (e3000, f0up+1) → EQ → тихий эмбиент-дрон. Повторные фразы берутся из кэша `temp/cache` без сети и GPU. Зависший или упавший RVC-демон отсекается по таймауту (40с), и фраза всё равно звучит — голосом без конверсии |
| **Эмоции** | `sarcastic / angry / mocking / calm / neutral` — цвет чипа и тон комментария |
| **Песочница** | `run.bat check` — 60+ самопроверок без сети, токенов и GPU |

## Архитектура

```mermaid
flowchart LR
    A[🖥 Скриншот игры] --> B{Vision loop\n45 c}
    B -->|кадр изменился| C[Ollama\ndurandal-gemma]
    B -->|статичный кадр| B
    C --> D[💬 Twitch чат\nEventSub]
    D --> E[🧠 Brain\nпамять + эмоции]
    C --> E
    E --> F[🔊 edge-tts −25%\n+ авто-фолбэк голоса]
    F --> G[🎙 RVC daemon\nCUDA, e3000]
    G --> H[🎛 EQ + эмбиент]
    H --> I[🔈 winsound]
    E --> J[🟩 Overlay :9733\nпечать + EQ + STATUS]
    I --> J
```

## Быстрый старт

### 1. Окружение и зависимости

```powershell
git clone https://github.com/NeruMarcus/durandal-stream-bot
cd durandal-stream-bot
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### 2. Локальная модель

```powershell
ollama pull gemma3:4b
ollama create durandal-gemma -f Modelfile
# Одна RTX делит игру, OBS, RVC и Ollama: KV-кэш в q8 жмёт аппетит модели
# без потери качества (выполнить раз, затем перезапустить Ollama).
setx OLLAMA_KV_CACHE_TYPE q8_0
```

### 3. Конфигурация

```powershell
Copy-Item .env.example .env
```

Заполните Twitch-блок (ID — на https://twitchtokengenerator.com, приложение — https://dev.twitch.tv/console, скопы токена `user:read:chat user:bot channel:bot`):

| Ключ | Назначение |
|------|-----------|
| `TWITCH_TOKEN` / `TWITCH_REFRESH_TOKEN` | user-токен бота (или пусто → `run.bat auth`) |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | приложение Twitch |
| `TWITCH_BOT_ID` / `TWITCH_CHANNEL_ID` | числовые ID бота и канала |
| `USE_RVC` | `true` — голос Дюрандаля, `false` — чистый edge-tts |
| `TTS_VOICES` | голоса edge-tts по приоритету через запятую; `голос:сдвиг_RVC` транспонирует под RVC |
| `COMMENT_INTERVAL` | пауза vision-цикла, сек (мин. 10) |
| `MONITOR_INDEX` | монитор для захвата (0 = основной; дефолт 1 — второй монитор) |
| `CHAT_COOLDOWN` | кулдаун ответов в чат, сек |

### 4. RVC голос (опционально)

Движку нужен отдельный `rvc_env` (Python 3.10 + torch CUDA) и ~600 МБ бинарников — в репозиторий они **не входят** (см. `.gitignore`):

```powershell
py -3.10 -m venv rvc_env
rvc_env\Scripts\pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
rvc_env\Scripts\python -m pip install "pip==24.0"
rvc_env\Scripts\pip install -r rvc_requirements.txt
rvc_env\Scripts\pip install https://huggingface.co/Jmica/rvc/resolve/main/fairseq-0.12.2-cp310-cp310-win_amd64.whl
```

| Файл | Куда положить | Откуда |
|------|--------------|--------|
| `hubert_base.pt` | `models/rvc_webui/assets/hubert/` | [RVC releases](https://huggingface.co/lj1995/VoiceConversionWebUI/blob/main/hubert_base.pt) |
| `rmvpe.pt` | `models/rvc_webui/assets/rmvpe/` | [RVC releases](https://huggingface.co/lj1995/VoiceConversionWebUI/blob/main/rmvpe.pt) |
| `f0G40k.pth`, `f0D40k.pth` | `models/rvc_webui/assets/pretrained/` | [RVC pretrained](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main/pretrained) |
| `durandal_v1_40k_e3000_s93000.pth` + `.index` | `models/rvc_webui/assets/weights/` | голос Дюрандаля, лежит в репозитории (бэкап, ~82 МБ) |

Старшая эпоха выбирается автоматически. Демон греется в фоне при старте бота.

### 5. Проверка и запуск

```powershell
run.bat          # бот
run.bat auth     # одноразовая авторизация Twitch (браузер откроется сам)
run.bat check    # песочница: 60+ проверок без сети и токенов
run.bat overlay  # только оверлей-сервер (предпросмотр дизайна)
```

### 6. OBS

Browser Source → URL `http://127.0.0.1:9733/overlay`, размер **845×230**, прозрачный фон.

Состояние (`GET /state`): `text`, `emotion`, `speaking`, `energy`, `timestamp` + опциональный `status` от бэкенда (приоритет над автовыводом).

## Структура проекта

```
durandal-stream-bot/
├── assets/fonts/JetBrainsMono-Regular.ttf  # шрифт оверлея (OFL 1.1, кириллица)
├── core/            # brain.py (LLM + память), emotions.py (теги ru→en), memory.py, ollama.py
├── docs/screenshots/# кадры оверлея для README
├── models/rvc_webui/# RVC-движок (код; бинарники качаются отдельно — см. §RVC голос)
├── twitch/chat.py   # EventSub-бот: кулдаун, фильтры, фоновые ответы
├── voice/           # tts.py (edge-tts → 24k → RVC → EQ), audiofx.py (речь + эмбиент)
├── temp/            # рантайм: overlay_state.json, TTS-фрагменты (не коммитится)
├── main.py          # точка входа: vision + twitch циклы, warmup, статусы оверлея
├── overlay_server.py# HTTP-сервер + HTML терминала (печать, STATUS, эквалайзер)
├── check.py         # песочница без сети/токенов
├── Modelfile       # сборка durandal-gemma из gemma3:4b
└── run.bat          # запуск: бот / auth / check / overlay
```

## Устранение неполадок

<details>
<summary><b>Пропал голос — <code>NoAudioReceived</code> от edge-tts</b></summary>

Транзиентный сбой Microsoft Cloud TTS (часто — «грязный» IP VPN-выхода). На каждый голос 2 попытки с паузой 2с, затем следующий голос из `TTS_VOICES`; готовые фразы берутся из кэша `temp/cache` без сети и RVC. Проверка вручную:

```powershell
venv\Scripts\python -m edge_tts --text "тест" --write-media temp\test.mp3
```

</details>

<details>
<summary><b>Первая реплика готовится ~40 секунд</b></summary>

Так и задумано один раз: при старте греются RVC-демон (загрузка модели в VRAM) и Ollama-модель. Смотрите лог: `RVC warmup ok`, `LLM warmup ok`. Vision-цикл стартует только после прогрева LLM, а модель держится в VRAM 30 минут (`keep_alive`) — иначе холодный старт упирается в таймаут первого комментария.

</details>

<details>
<summary><b>Бот «сам закрылся» / пишет общие фразы</b></summary>

Два разных сбоя:
- **Общие фразы вместо сцены** — не модель, а визуальный энкодер Ollama: при живой игре GPU занят на 99% (3D-движок игры + videoencode OBS), и кодирование кадра в одном вызове идёт 10–90с, хотя текст считается за 1–3с. Размер кадра тут не поможет: gemma3 всегда режет картинку в 256 токенов (`prompt_eval_count` = 288 при любом разрешении), а повтор *того же* кадра — 1.6с (кэш энкодинга). Поэтому на vision даётся 90с на одну попытку, и повтор только если фразу отбросили (цифры HUD / повтор) — второй заход по тому же кадру дешёвый. В логе теперь видно `Vision LLM: 23.4с`. Ключевые строки диагностики: `Vision LLM: ReadTimeout за 90с`, `Vision timeout, фолбек`.
  Радикальное лечение одно — разгрузить GPU (пауза Wallpaper Engine, ниже настройки игры), иначе реплика будет с задержкой 10–90с либо фолбек.
- **Процесс завершился** — жёсткие падения пишутся в `crash.log` (faulthandler), а `run.bat` теперь сам перезапускает `main.py` через 5с после выхода. Остановить — Ctrl+C на паузе.

</details>

<details>
<summary><b>Комментариев нет, хотя игра идёт</b></summary>

dHash-детектор пропускает статичные кадры (`Кадр не изменился, пропуск LLM` в логе) — это экономия, а не баг. Проверьте `MONITOR_INDEX` — захват должен смотреть на монитор с игрой.

</details>

<details>
<summary><b>Бот не видит чат (нет строк <code>Twitch [ник]:</code> в логе)</b></summary>

0. Пишете с аккаунта бота (у нас бот и канал — один `nerumarcus`)? Свои сообщения бот молча пропускает — для проверки пишите **со второго аккаунта** (с телефона, например). Пропуски видны в `bot.log` на уровне DEBUG.
1. Проверьте подписку EventSub (выполнять в папке бота; секреты никуда не уходят):
```powershell
$t = (Select-String -Path .env -Pattern '^TWITCH_TOKEN=(.*)$').Matches.Groups[1].Value.Trim().Trim('"')
$cid = (Select-String -Path .env -Pattern '^TWITCH_CLIENT_ID=(.*)$').Matches.Groups[1].Value.Trim()
(Invoke-RestMethod 'https://api.twitch.tv/helix/eventsub/subscriptions' -Headers @{'Client-Id'=$cid; Authorization="Bearer $($t -replace '^oauth:','')"}).data | Format-Table type,status
```
Нужна строка `channel.chat.message` со статусом `enabled`. Нет строки — подписка не встала; статус `authorization_revoked`/`user_removed` — токен протух или не тот аккаунт.
2. Проверьте сам токен (показывает только логин/скопы/срок — безопасно делиться):
```powershell
$t = (Select-String -Path .env -Pattern '^TWITCH_TOKEN=(.*)$').Matches.Groups[1].Value.Trim().Trim('"')
Invoke-RestMethod 'https://id.twitch.tv/oauth2/validate' -Headers @{Authorization="OAuth $($t -replace '^oauth:','')"} | Select-Object login,user_id,client_id,scopes,expires_in
```
В `scopes` обязан быть `user:read:chat`, `client_id` — совпадать с `TWITCH_CLIENT_ID` в `.env`, `user_id` — с `TWITCH_BOT_ID`.
3. Не сходится — `run.bat auth` заново (войти под аккаунтом бота, разрешить доступ) и перезапуск.
4. Отдельный случай: `403 subscription missing proper authorization` при живых скопах. Подписка едет через conduit на **app-токене**, а для `channel.chat.message` Twitch тогда требует ещё `user:bot` (от бота) + `channel:bot` (от вещателя). Наш OAuth-URL уже просит все три скопа — просто пройдите `run.bat auth` заново (старые токены их не содержат) и перезапустите бота.

</details>

<details>
<summary><b>edge-tts молчит: 403 на handshake или NoAudioReceived</b></summary>

Сначала обновить библиотеку — это лечит большинство случаев:
```powershell
venv\Scripts\python -m pip install -U edge-tts
```
Две разные болезни:
- **403 (handshake)** — Microsoft режет IP, а не баг бота (без VPN — 403, через VPN — работает). В октябре 2026 ровно это вылечила версия 7.3.1.
- **NoAudioReceived** — соединение есть, но сервис не отдал ни звука. Наблюдение октября 2026: отвал **по-голосно** — один голос стабильно молчит, а другой в той же сети жив (`ru-RU-DmitryNeural` мёртв, `ru-RU-SvetlanaNeural` / `en-US-AndrewMultilingualNeural` работают). Мультиязычные голоса говорят по-русски, так что фолбэк тоже мужской.

Лечение встроено: `TTS_VOICES` — голоса по приоритету, бот пробует каждый пару раз и молча переходит к следующему (в логе: `edge-tts: <голос> недоступен, переключился на <другой>`). Женский резерв задаётся транспонированием, чтобы Дюрандаль не «поехал» по регистру: `ru-RU-SvetlanaNeural:-11` (октава вниз).

Обход сети через VPN (если нужен именно конкретный голос): edge-tts уважает `HTTPS_PROXY` — `$env:HTTPS_PROXY='http://127.0.0.1:1080'` перед `run.bat` (когда VPN-клиент даёт локальный прокси); Twitch/Ollama пойдут напрямую. Бот при любом раскладе не падает — текст всё равно уходит в оверлей.

</details>

<details>
<summary><b>Порт 9733 занят</b></summary>

Остановите старый демо-сервер/копию бота: только один процесс владеет оверлеем. При старте бот поднимает сервер сам.

</details>

## Шрифт

Оверлей рисуется локальным `assets/fonts/JetBrainsMono-Regular.ttf` (сервер отдаёт его по `/font`): CDN и интернет не нужны. JetBrains Mono — © JetBrains, лицензия **SIL Open Font License 1.1**. Замена: положите другой `.ttf` и поправьте путь в `overlay_server.py`.

## Безопасность

- `.env`, `.tio.tokens.json`, `bot.log` и бинарники RVC-движка — в `.gitignore`, секреты в репозиторий не попадают.
- Обученные веса голоса (`models/rvc_webui/assets/weights/`, ~82 МБ) — наоборот версионируются: репозиторий и есть их бэкап.
- `GITHUB_TOKEN` нужен только `torch.hub` при первом скачивании моделей; после прогрева убрать либо выдать токен без прав.
- Засветили токен — отзовите и перевыпустите: Twitch — заново `run.bat auth`, GitHub — Settings → Developer settings → Tokens.
- Логи токены не печатают.

## Лицензия

[MIT](LICENSE) © 2026 NeruMarcus
