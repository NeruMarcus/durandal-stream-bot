import os
import shutil
import subprocess
import tempfile

import imageio_ffmpeg

from logger import logger

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_AMBIENT_PATH = None


def _ensure_ambient():
    global _AMBIENT_PATH
    if _AMBIENT_PATH and os.path.exists(_AMBIENT_PATH):
        return _AMBIENT_PATH
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
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
        "-ac", "2", "-ar", "48000", "-sample_fmt", "s16", path,
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Ambient gen: {result.stderr[-200:]}")
        fd2, fallback = tempfile.mkstemp(suffix=".wav")
        os.close(fd2)
        subprocess.run(
            [_FFMPEG, "-y", "-f", "lavfi", "-i",
             "sine=frequency=50:sample_rate=48000:d=300",
             "-ac", "2", "-ar", "48000", fallback],
            check=False, capture_output=True,
        )
        _AMBIENT_PATH = fallback
    else:
        _AMBIENT_PATH = path
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
