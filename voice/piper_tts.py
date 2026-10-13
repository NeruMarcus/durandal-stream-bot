"""Офлайн-фолбэк синтеза: Piper TTS (MIT, локально, без сети).

Используется, когда edge-tts стабильно отвечает 403 (Microsoft режет IP).
Тембр всё равно переозвучивает RVC, поэтому базовый голос Piper —
лишь разборчивая болванка: русские фонемы через bundled espeak-ng.

Первый вызов докачивает движок (~21 МБ) и голос dmitri/medium (~60 МБ)
в vendor/piper/ (в git не входит, см. .gitignore).
"""

import hashlib
import os
import subprocess
import urllib.request
import zipfile

from logger import logger

_SELF_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR_DIR = os.path.join(_SELF_DIR, "vendor", "piper")
_BIN_DIR = os.path.join(_VENDOR_DIR, "bin")
_VOICES_DIR = os.path.join(_VENDOR_DIR, "voices")

PIPER_TAG = "2023.11.14-2"
BIN_URL = (
    "https://github.com/rhasspy/piper/releases/download/"
    f"{PIPER_TAG}/piper_windows_amd64.zip"
)
VOICE_NAME = "ru_RU-dmitri-medium"
VOICE_URLS = (
    f"https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/dmitri/medium/{VOICE_NAME}.onnx",
    f"https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/dmitri/medium/{VOICE_NAME}.onnx.json",
)
VOICE_ONNX = os.path.join(_VOICES_DIR, VOICE_NAME + ".onnx")

# Заметно медленнее единицы — размеренная речь вместо скороговорки
# (≈−29%, в духе edge-Dmitry на −25%).
LENGTH_SCALE = "1.4"


def _download(url: str, dest: str):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "durandal-stream-bot"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, mark = 0, 0
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total and got - mark > 10 * 1024 * 1024:
                mark = got
                logger.info(f"Piper загрузка: {got // 1000000}/{total // 1000000} МБ")
    os.replace(tmp, dest)


def _find_exe() -> str | None:
    for root, _, files in os.walk(_BIN_DIR):
        if "piper.exe" in files:
            return os.path.join(root, "piper.exe")
    return None


def ensure_piper() -> tuple[str, str]:
    """Возвращает (piper.exe, voice.onnx), докачивая недостающее."""
    exe = _find_exe()
    voice, voice_json = VOICE_ONNX, VOICE_ONNX + ".json"
    if exe and all(
        os.path.isfile(p) and os.path.getsize(p) > 1000
        for p in (voice, voice_json)
    ):
        return exe, voice
    logger.warning("Piper: докачиваю движок и голос (~85 МБ, один раз)...")
    if not exe:
        _download(BIN_URL, os.path.join(_BIN_DIR, "piper_windows_amd64.zip"))
        with zipfile.ZipFile(os.path.join(_BIN_DIR, "piper_windows_amd64.zip")) as z:
            z.extractall(_BIN_DIR)
        try:
            os.remove(os.path.join(_BIN_DIR, "piper_windows_amd64.zip"))
        except OSError:
            pass
        exe = _find_exe()
    if not exe:
        raise RuntimeError("Piper: piper.exe не найден после распаковки")
    for url in VOICE_URLS:
        dest = os.path.join(_VOICES_DIR, url.rsplit("/", 1)[1])
        if not (os.path.isfile(dest) and os.path.getsize(dest) > 1000):
            _download(url, dest)
    logger.info("Piper: движок и голос готовы")
    return exe, voice


def synthesize(text: str, out_path: str | None = None,
               length_scale: str = LENGTH_SCALE) -> str:
    """Офлайн-синтез в wav (22050 Гц, моно). Текст — уже чистый, без [тегов]."""
    exe, voice = ensure_piper()
    if out_path is None:
        tag = hashlib.md5(text.encode()).hexdigest()[:8]
        out_path = os.path.join(_SELF_DIR, "temp", f"piper_{tag}.wav")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [exe, "--model", voice, "--output_file", out_path,
           "--length_scale", length_scale]
    try:
        r = subprocess.run(cmd, input=text.encode("utf-8"),
                           capture_output=True, timeout=180)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Piper: таймаут синтеза ({e})")
    if r.returncode != 0 or not (
        os.path.exists(out_path) and os.path.getsize(out_path) > 1000
    ):
        err = r.stderr.decode("utf-8", errors="replace")[-300:]
        raise RuntimeError(f"Piper: {err}")
    return out_path


if __name__ == "__main__":
    # run.bat piper — прогрев/докачка движка без запуска бота.
    exe, voice = ensure_piper()
    print(f"exe: {exe}")
    print(f"voice: {voice}")
    out = synthesize("Это Дюрандаль. Офлайн-голос готов.")
    print(f"test: {out}")
