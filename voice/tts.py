import asyncio
import hashlib
import os
import subprocess
from pathlib import Path

from config import Config
from core.emotions import parse_emotion
from logger import logger

_SELF_DIR = Path(__file__).parent.parent.resolve()
_DEFAULT_TEXT = "Ваше присутствие здесь — оскорбление."
_FFMPEG = None


def _get_ffmpeg():
    global _FFMPEG
    if _FFMPEG is None:
        import imageio_ffmpeg
        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return _FFMPEG


async def _edge_save(text: str, path: str):
    import edge_tts
    tts = edge_tts.Communicate(text, voice="ru-RU-DmitryNeural", rate="-25%")
    await tts.save(path)


def _to_24k(in_path: str) -> str:
    out = str(_SELF_DIR / "temp" / f"g24_{Path(in_path).stem}.wav")
    subprocess.run(
        [_get_ffmpeg(), "-y", "-i", in_path, "-ar", "24000", out],
        capture_output=True,
        check=False,
    )
    return out


def _apply_eq(in_path: str) -> str:
    out = str(_SELF_DIR / "temp" / f"eq_{Path(in_path).stem}.wav")
    subprocess.run(
        [
            _get_ffmpeg(), "-y", "-i", in_path,
            "-af", "lowshelf=f=150:w=1:g=4,highshelf=f=6000:w=1:g=4",
            out,
        ],
        capture_output=True,
        check=False,
    )
    return out


def _post_process(raw: str) -> str:
    """ ffmpeg + RVC — всё синхронное, поэтому живёт в отдельном потоке. """
    src24 = _to_24k(raw)
    rvc_out = None
    try:
        if Config.USE_RVC:
            import rvc_convert
            rvc_out = rvc_convert.rvc_convert(
                src24, f0up_key=1, index_rate=0,
                resample_sr=24000, rms_mix_rate=0.33, protect=0.33,
            )
            return _apply_eq(rvc_out)
        return _apply_eq(src24)
    finally:
        # Промежутки (g24_, rvc_) — сразу в утиль, иначе за долгий стрим
        # копятся сотнями мегабайт до часового _prune_temp. Итоговый eq_
        # возвращает вызывающий, его чистит main._speak.
        for p in (src24, rvc_out):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


async def text_to_speech(text: str) -> str:
    text = parse_emotion(text or "")[0] or _DEFAULT_TEXT

    tag = hashlib.md5(text.encode()).hexdigest()[:8]
    os.makedirs(str(_SELF_DIR / "temp"), exist_ok=True)
    raw = str(_SELF_DIR / "temp" / f"tts_{tag}.wav")
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            await _edge_save(text, raw)
            last_err = None
            break
        except Exception as e:
            last_err = e
            # NoAudioReceived = сервис промолчал (троттлинг VPN-выхода и т.п.),
            # это транзиентное — пережидаем нарастающей паузой.
            logger.warning(
                f"edge-tts попытка {attempt + 1}/4: {type(e).__name__}: {e}"
            )
            if attempt < 3:
                await asyncio.sleep(min(2 ** (attempt + 1), 10))
    if last_err is not None:
        # edge-tts стабильно недоступен (403/IP-блок) — офлайн-фолбэк Piper.
        # Тембр всё равно переозвучивает RVC, так что смена базы безопасна.
        logger.warning("edge-tts недоступен, переключаюсь на офлайн Piper...")
        try:
            from voice.piper_tts import synthesize as piper_synthesize

            raw = await asyncio.to_thread(piper_synthesize, text)
            last_err = None
            logger.info("Piper: синтез ok")
        except Exception as e:
            logger.error(f"Piper: {type(e).__name__}: {e}")
    if last_err is not None:
        raise last_err

    # В отдельном потоке: RVC занимает секунды и не должен вешать цикл событий.
    return await asyncio.to_thread(_post_process, raw)
