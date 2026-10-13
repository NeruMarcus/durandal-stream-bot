import os
import shutil
import subprocess
import tempfile

import imageio_ffmpeg

from logger import logger

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_AMBIENT_PATH = None
# Стабильный путь в проектном temp/cache: дрон генерируется один раз
# (~57 МБ) и переиспользуется между перезапусками, а не утекает
# новым файлом в системный temp при каждом старте. _prune_temp чистит
# только верхний уровень temp/, подкаталог cache не трогает.
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "temp", "cache")
_AMBIENT_FILE = os.path.join(_CACHE_DIR, "ambient_drone.wav")
_FALLBACK_FILE = os.path.join(_CACHE_DIR, "ambient_sine.wav")


def _ensure_ambient():
    global _AMBIENT_PATH
    if _AMBIENT_PATH and os.path.exists(_AMBIENT_PATH):
        return _AMBIENT_PATH
    for cached in (_AMBIENT_FILE, _FALLBACK_FILE):
        if os.path.exists(cached) and os.path.getsize(cached) > 0:
            _AMBIENT_PATH = cached
            return _AMBIENT_PATH
    os.makedirs(_CACHE_DIR, exist_ok=True)
    # Дрон заведомо тихий: здесь -10 dB, плюс -12 dB при миксе с речью
    # (суммарно ~-22 dB). На слух эта разница незначительна, зато эмбиент
    # гарантированно не перекрывает голос. Не «оптимизировать» вслепую.
    ambient_filter = (
        "[1:a]asplit[noise_low][noise_mid];"
        "[noise_low]lowpass=f=250,volume=0.3[low];"
        "[noise_mid]bandpass=f=700:width=500,volume=0.2,"
        "aphaser=type=t:decay=0.8:speed=0.12:out_gain=0.6[band];"
        "[0:a][low]amix=inputs=2:duration=first:weights=0.5 0.5,"
        "volume=0.7[mix];"
        "[mix][band]amix=inputs=2:duration=first:weights=0.7 0.3,"
        "aecho=0.8:0.7:100|200|350:0.3|0.2|0.1,volume=-10dB"
    )
    cmd = [
        _FFMPEG, "-y", "-f", "lavfi", "-i",
        "sine=frequency=50:sample_rate=48000:d=300",
        "-f", "lavfi", "-i",
        "anoisesrc=color=brown:sample_rate=48000:amplitude=0.5:d=300",
        "-filter_complex", ambient_filter,
        "-ac", "2", "-ar", "48000", "-sample_fmt", "s16", _AMBIENT_FILE,
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Ambient gen: {result.stderr[-200:]}")
        try:
            os.remove(_AMBIENT_FILE)
        except OSError:
            pass
        subprocess.run(
            [_FFMPEG, "-y", "-f", "lavfi", "-i",
             "sine=frequency=50:sample_rate=48000:d=300",
             "-ac", "2", "-ar", "48000", _FALLBACK_FILE],
            check=False, capture_output=True,
        )
        _AMBIENT_PATH = _FALLBACK_FILE
    else:
        _AMBIENT_PATH = _AMBIENT_FILE
    return _AMBIENT_PATH


def process_speech(tts_path: str) -> str:
    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    ambient = _ensure_ambient()
    cmd = [
        _FFMPEG, "-y",
        "-i", tts_path,
        "-i", ambient,
        "-filter_complex",
        "[1:a]volume=-12dB[ambient];"
        "[0:a][ambient]amix=inputs=2:duration=first:weights=1.0 0.6,"
        "volume=1.0[out]",
        "-map", "[out]", "-ac", "2", "-ar", "48000", out,
    ]

    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg voice: {result.stderr[-200:]}")
        shutil.copy2(tts_path, out)
    return out
