import os
import tempfile

from PIL import ImageGrab

from config import Config


def capture_screen() -> str:
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".png", dir=Config.TEMP_DIR)
    os.close(fd)

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

    img.save(path)
    return path
