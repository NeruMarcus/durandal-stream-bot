import asyncio
import json
import os
import subprocess
import tempfile
import threading
import time
import shutil

import imageio_ffmpeg

from config import Config
from personality import (
    generate_vision_commentary,
    generate_fallback,
    _CHAT_SYSTEM,
)
from core.brain import Brain
from logger import logger


_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_OVERLAY_STATE = os.path.join(os.path.dirname(__file__), "temp", "overlay_state.json")
_TEMP_DIR = Config.TEMP_DIR

os.makedirs(_TEMP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(_OVERLAY_STATE), exist_ok=True)

_tts_lock = asyncio.Lock()
_brain = Brain()


# ── Overlay ─────────────────────────────────────────────────────────────────


def _save_overlay(text: str, emotion: str = "neutral"):
    data = json.dumps(
        {"text": text, "emotion": emotion, "timestamp": time.time()},
        ensure_ascii=False,
    )
    with open(_OVERLAY_STATE, "w", encoding="utf-8") as f:
        f.write(data)


# ── Audio pipeline ──────────────────────────────────────────────────────────


def _play_local(path: str):
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    r = subprocess.run(
        [_FFMPEG, "-y", "-i", path, "-sample_fmt", "s16", "-f", "wav", wav],
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        shutil.copy2(path, wav)
    import winsound

    try:
        winsound.PlaySound(wav, winsound.SND_ASYNC)
    except Exception as e:
        logger.warning(f"winsound: {e}")
    threading.Timer(5.0, os.unlink, [wav]).start()


def _cleanup(path: str):
    try:
        os.remove(path)
    except Exception:
        pass


async def _speak(text: str) -> bool:
    """Generate TTS and play. Returns True if successful."""
    async with _tts_lock:
        try:
            from voice.tts import text_to_speech

            tts_path = await asyncio.wait_for(
                text_to_speech(text), timeout=120
            )
            if not tts_path or not os.path.exists(tts_path):
                return False

            try:
                from voice.audiofx import process_speech

                final = await asyncio.wait_for(
                    asyncio.to_thread(process_speech, tts_path), timeout=30
                )
                _cleanup(tts_path)
            except Exception:
                final = tts_path

            logger.info("Воспроизведение")
            _play_local(final)
            _cleanup(final)
            return True
        except Exception as e:
            logger.error(f"TTS: {e}")
            return False


# ── Vision commentary loop ──────────────────────────────────────────────────


async def _vision_loop():
    while True:
        cycle_start = time.time()
        try:
            commentary, emotion = await asyncio.wait_for(
                asyncio.to_thread(generate_vision_commentary),
                timeout=60,
            )
        except asyncio.TimeoutError:
            logger.warning("Vision timeout, фолбек")
            commentary, emotion = generate_fallback()
        except Exception as e:
            logger.error(f"Vision: {type(e).__name__}: {e}")
            commentary, emotion = generate_fallback()

        _save_overlay(commentary, emotion)
        logger.info(f"Комментарий: {commentary}")

        await _speak(commentary)

        elapsed = time.time() - cycle_start
        remaining = Config.COMMENT_INTERVAL - elapsed
        if remaining > 0:
            logger.info(f"Пауза {remaining:.0f}с до следующего цикла")
            await asyncio.sleep(remaining)


# ── Twitch callback ─────────────────────────────────────────────────────────


async def _on_chat(user: str, text: str):
    logger.info(f"Чат [{user}]: {text}")
    response, emotion = await _brain.generate(_CHAT_SYSTEM, f"{user}: {text}")

    _save_overlay(response, emotion)

    await _speak(response)


# ── Main ────────────────────────────────────────────────────────────────────


async def main():
    from overlay_server import main as overlay_main

    logger.info("Запуск overlay сервера на http://127.0.0.1:9733/overlay")
    t = threading.Thread(target=overlay_main, daemon=True)
    t.start()
    await asyncio.sleep(1)

    _save_overlay("")

    vision_task = asyncio.create_task(_vision_loop())

    if Config.TWITCH_TOKEN:
        from twitch.chat import DurandalBot

        twitch_bot = DurandalBot(_on_chat)
        logger.info("Запуск Twitch бота...")
        twitch_task = asyncio.create_task(twitch_bot.start())
        await asyncio.gather(vision_task, twitch_task)
    else:
        logger.info("TWITCH_TOKEN не задан, только офлайн режим")
        await vision_task


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
