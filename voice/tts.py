import asyncio
import hashlib
import os
import subprocess
from pathlib import Path

from config import Config
from logger import logger

_SELF_DIR = Path(__file__).parent.parent.resolve()
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
    os.makedirs(str(Path(out).parent), exist_ok=True)
    subprocess.run(
        [_get_ffmpeg(), "-y", "-i", in_path, "-ar", "24000", out],
        capture_output=True,
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
    )
    return out


async def text_to_speech(text: str) -> str:
    if not text or not isinstance(text, str):
        text = "Ваше присутствие здесь — оскорбление."
    import re
    text = re.sub(r"\[.*?\]", "", text).strip()
    text = re.sub(
        r"(?i)^\s*\[?(sarcastic|angry|mocking|calm|neutral|"
        r"саркастичный|злой|насмешливый|спокойный)\]?[\s:,-]+",
        "", text
    ).strip()
    if len(text) > 240:
        text = text[:237] + "..."

    tag = hashlib.md5(text.encode()).hexdigest()[:8]
    os.makedirs(str(_SELF_DIR / "temp"), exist_ok=True)
    raw = str(_SELF_DIR / "temp" / f"tts_{tag}.wav")
    await _edge_save(text, raw)

    src24 = _to_24k(raw)

    if Config.USE_RVC:
        import rvc_convert
        rvc_out = rvc_convert.rvc_convert(
            src24, f0up_key=1, index_rate=0,
            resample_sr=24000, rms_mix_rate=0.33, protect=0.33,
        )
        return _apply_eq(rvc_out)

    return _apply_eq(src24)
