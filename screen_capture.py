import os
import tempfile

from PIL import Image, ImageGrab

from config import Config


def capture_screen() -> str:
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".png", dir=Config.TEMP_DIR)
    os.close(fd)
    try:
        try:
            import win32api
            monitors = win32api.EnumDisplayMonitors()
            idx = Config.MONITOR_INDEX
            if idx < len(monitors):
                left, top, right, bottom = monitors[idx][2]
                img = ImageGrab.grab(bbox=(left, top, right, bottom))
            else:
                img = ImageGrab.grab(all_screens=True)
        except ImportError:
            img = ImageGrab.grab(all_screens=True)
        with img:
            img.save(path)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


_last_hash: int | None = None


def _dhash(img) -> int:
    """ Difference hash 64 бит: серый 9x8, сравнение соседей по строке. """
    px = img.convert("L").resize((9, 8)).tobytes()
    bits = 0
    for y in range(8):
        row = px[y * 9:(y + 1) * 9]
        for x in range(8):
            bits = (bits << 1) | (row[x] > row[x + 1])
    return bits


def is_unchanged(path: str, threshold: int = 4) -> bool:
    """ True, если кадр почти не отличается от предыдущего (экономия LLM-вызовов). """
    global _last_hash
    with Image.open(path) as img:
        h = _dhash(img)
    if _last_hash is None:
        _last_hash = h
        return False
    same = bin(h ^ _last_hash).count("1") <= threshold
    _last_hash = h
    return same
