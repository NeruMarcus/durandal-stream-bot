import logging
import os
import sys


_LOG_FILE = os.path.join(os.path.dirname(__file__), "bot.log")


def setup_logger(name: str = "durandal") -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )

    for h in root.handlers[:]:
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)

    fh = logging.FileHandler(_LOG_FILE, encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    root.addHandler(console)
    root.addHandler(fh)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    return logger


logger = setup_logger()
