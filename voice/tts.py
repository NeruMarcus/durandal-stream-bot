import asyncio
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from config import Config
from core.emotions import parse_emotion
from logger import logger

_SELF_DIR = Path(__file__).parent.parent.resolve()
_DEFAULT_TEXT = "Ваше присутствие здесь — оскорбление."
_DEFAULT_VOICE = "ru-RU-DmitryNeural"
_DEFAULT_F0 = 1
_RETRIES_PER_VOICE = 2
_FFMPEG = None

# Кэш готовых фраз: фолбеки и частые реплики повторяются дословно —
# повторный edge-tts (сеть) + RVC (GPU) заменяем копией файла (~0.2с).
# Ключ: md5 текста + f0 + флаг RVC (параметры цепочки фиксированы).
_CACHE_DIR = _SELF_DIR / "temp" / "cache"
_CACHE_MAX = 50


def _cache_path(tag: str, f0: int) -> str:
    mode = "r" if Config.USE_RVC else "p"
    return str(_CACHE_DIR / f"tts_{tag}_{f0}{mode}.wav")


def _cache_hit(tag: str, f0: int) -> str | None:
    try:
        src = _cache_path(tag, f0)
        if os.path.exists(src) and os.path.getsize(src) > 0:
            dst = str(_SELF_DIR / "temp" / f"final_{tag}.wav")
            shutil.copy2(src, dst)
            return dst
    except OSError:
        pass
    return None


def _cache_store(tag: str, f0: int, path: str) -> None:
    # Кэш — только ускорение: любая ошибка молча игнорируется.
    try:
        os.makedirs(str(_CACHE_DIR), exist_ok=True)
        shutil.copy2(path, _cache_path(tag, f0))
        files = sorted(
            (p for p in _CACHE_DIR.glob("tts_*.wav") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        for old in files[: max(0, len(files) - _CACHE_MAX)]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _parse_voices(raw: str) -> list[tuple[str, int]]:
    """ "голос[:сдвиг_RVC]" через запятую -> [(голос, f0up_key), ...].

    Сдвиг нужен RVC: женскую базу транспонируем на октаву вниз (напр.
    ru-RU-SvetlanaNeural:-11), иначе Дюрандаль заговорит женским регистром.
    """
    voices: list[tuple[str, int]] = []
    for item in raw.split(","):
        name, _, shift = item.strip().partition(":")
        name = name.strip()
        if not name:
            continue
        try:
            f0 = int(shift)
        except ValueError:
            f0 = _DEFAULT_F0
        voices.append((name, f0))
    return voices or [(_DEFAULT_VOICE, _DEFAULT_F0)]


_VOICES = _parse_voices(Config.TTS_VOICES)


def _get_ffmpeg():
    global _FFMPEG
    if _FFMPEG is None:
        import imageio_ffmpeg
        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return _FFMPEG


async def _edge_save(text: str, path: str, voice: str = _DEFAULT_VOICE):
    import edge_tts
    tts = edge_tts.Communicate(text, voice=voice, rate="-25%")
    # Сеть до Microsoft иногда молчит: без лимита cycle висел до общего 120с.
    await asyncio.wait_for(tts.save(path), timeout=25)


def _to_24k(in_path: str) -> str:
    out = str(_SELF_DIR / "temp" / f"g24_{Path(in_path).stem}.wav")
    try:
        r = subprocess.run(
            [_get_ffmpeg(), "-y", "-i", in_path, "-ar", "24000", out],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg 24k: timeout, дальше без ресемпла")
        return in_path
    # Битый вход/ffmpeg: дальше по цепочке отдаём исходник, а не
    # несуществующий путь (иначе тихий каскадный фейл до winsound).
    if r.returncode != 0 or not os.path.exists(out):
        return in_path
    return out


def _apply_eq(in_path: str) -> str:
    out = str(_SELF_DIR / "temp" / f"eq_{Path(in_path).stem}.wav")
    try:
        r = subprocess.run(
            [
                _get_ffmpeg(), "-y", "-i", in_path,
                "-af", "lowshelf=f=150:w=1:g=4,highshelf=f=6000:w=1:g=4",
                out,
            ],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg EQ: timeout, дальше без эквализации")
        return in_path
    if r.returncode != 0 or not os.path.exists(out):
        return in_path
    return out


def _post_process(raw: str, f0up_key: int = _DEFAULT_F0) -> str:
    """ ffmpeg + RVC — всё синхронное, поэтому живёт в отдельном потоке. """
    src24 = _to_24k(raw)
    rvc_out = None
    try:
        if Config.USE_RVC:
            import rvc_convert
            try:
                rvc_out = rvc_convert.rvc_convert(
                    src24, f0up_key=f0up_key, index_rate=0,
                    resample_sr=24000, rms_mix_rate=0.33, protect=0.33,
                )
            except Exception as e:
                # Лучше голос без тембра Дюрандаля, чем молчание в эфире.
                logger.warning(f"RVC недоступен ({e}), голос без конверсии")
                return _apply_eq(src24)
            return _apply_eq(rvc_out)
        return _apply_eq(src24)
    finally:
        # Промежутки (сырой edge-tts, g24_, rvc_) — сразу в утиль, иначе за
        # долгий стрим копятся сотнями мегабайт до часового _prune_temp.
        # Итоговый eq_ возвращает вызывающий, его чистит main._speak.
        for p in (raw, src24, rvc_out):
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

    # Каждый голос пробуем пару раз (транзиентный сбой), затем идём дальше
    # по цепочке: конкретный голос у Microsoft «замолкает» надолго, а соседний
    # при этом жив — это и лечит NoAudioReceived.
    # Сначала кэш по всей цепочке: повторная фраза любым голосом
    # дешевле любого синтеза, даже если первый голос сменился.
    for voice, f0 in _VOICES:
        hit = _cache_hit(tag, f0)
        if hit:
            logger.info(f"edge-tts: кэш {voice}, без сети/RVC")
            return hit

    last_err: Exception | None = None
    voice, f0 = _VOICES[0][0], _VOICES[0][1]
    for voice, f0 in _VOICES:
        for attempt in range(1, _RETRIES_PER_VOICE + 1):
            try:
                await _edge_save(text, raw, voice)
                last_err = None
                break
            except Exception as e:
                last_err = e
                logger.warning(
                    f"edge-tts {voice} {attempt}/{_RETRIES_PER_VOICE}: "
                    f"{type(e).__name__}: {e}"
                )
                if attempt < _RETRIES_PER_VOICE:
                    await asyncio.sleep(2)
        if last_err is None:
            if voice != _VOICES[0][0]:
                logger.warning(
                    f"edge-tts: {_VOICES[0][0]} недоступен, "
                    f"переключился на {voice}"
                )
            break
    if last_err is not None:
        try:
            os.remove(raw)
        except OSError:
            pass
        raise last_err

    # В отдельном потоке: RVC занимает секунды и не должен вешать цикл событий.
    final = await asyncio.to_thread(_post_process, raw, f0)
    _cache_store(tag, f0, final)
    return final
