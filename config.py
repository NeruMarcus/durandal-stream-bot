import os

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Config:
    COMMENT_INTERVAL: int = _env_int("COMMENT_INTERVAL", 45)
    MONITOR_INDEX: int = _env_int("MONITOR_INDEX", 1)
    # LLM: только локальный Ollama — без VPN, без лимитов, без интернета.
    # OpenAI-совместимый API: http://localhost:11434/v1
    LLM_BASE_URL: str = os.getenv(
        "LLM_BASE_URL", "http://localhost:11434/v1"
    ).rstrip("/")
    # Одна модель на vision + chat (см. Modelfile): ollama pull gemma3:4b
    LLM_MODEL: str = os.getenv("LLM_MODEL", "durandal-gemma")
    TEMP_DIR: str = os.path.join(os.path.dirname(__file__), "temp")
    OVERLAY_STATE: str = os.path.join(TEMP_DIR, "overlay_state.json")
    # В коде дефолт true (боевой голос Durandal). В .env.example — false,
    # чтобы новый пользователь стартовал на чистом edge-tts без rvc_env.
    USE_RVC: bool = os.getenv("USE_RVC", "true").lower() == "true"

    TWITCH_TOKEN: str = os.getenv("TWITCH_TOKEN", "")
    TWITCH_REFRESH_TOKEN: str = os.getenv("TWITCH_REFRESH_TOKEN", "")
    TWITCH_CLIENT_ID: str = os.getenv("TWITCH_CLIENT_ID", "")
    TWITCH_CLIENT_SECRET: str = os.getenv("TWITCH_CLIENT_SECRET", "")
    TWITCH_BOT_ID: str = os.getenv("TWITCH_BOT_ID", "")
    TWITCH_CHANNEL_ID: str = os.getenv("TWITCH_CHANNEL_ID", "")
    TWITCH_CHANNEL: str = os.getenv("TWITCH_CHANNEL", "")
    CHAT_COOLDOWN: float = _env_float("CHAT_COOLDOWN", 3.0)

    # Голоса edge-tts по приоритету: "голос[:сдвиг_RVC]" через запятую.
    # Конкретный голос у Microsoft периодически «замолкает» (сервис отдаёт
    # пустой ответ, NoAudioReceived) — бот молча переходит к следующему.
    # Мультиязычные голоса говорят по-русски, поэтому фолбэк тоже мужской.
    TTS_VOICES: str = os.getenv(
        "TTS_VOICES",
        "en-US-AndrewMultilingualNeural,ru-RU-DmitryNeural,"
        "en-US-BrianMultilingualNeural",
    )


# Валидация: бессмысленные значения молча убили бы бота (цикл 0 сек, <0 и т.д.)
if Config.COMMENT_INTERVAL < 10:
    Config.COMMENT_INTERVAL = 10
if Config.CHAT_COOLDOWN < 0:
    Config.CHAT_COOLDOWN = 0.0
if Config.MONITOR_INDEX < 0:
    Config.MONITOR_INDEX = 0
