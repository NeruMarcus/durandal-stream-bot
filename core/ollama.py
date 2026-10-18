"""Нативный /api/chat Ollama (не OpenAI-совместимый /v1).

Причина: у нативного API images: [base64 без префикса] и параметр "think",
который гасит болтовню думающих моделей. Плюс один слой меньше между
нами и локальным сервером.

Сбой транспорта больше не глотается в None: chat бросает LLMError (см. ниже),
чтобы вызывающий видел причину — «Ollama закрыта» и «Ollama не успела за 90с»
раньше выглядели одинаково («Vision сцена: пусто») и реплика молча уходила
заготовкой.
"""

import shutil
import subprocess
import threading
import time

import requests

from config import Config
from logger import logger


class LLMError(RuntimeError):
    """LLM-запрос не дошёл: сервер недоступен, таймаут или HTTP-ошибка."""


class LLMUnavailable(LLMError):
    """Ollama не слушает порт (закрыта или упала)."""


class LLMTimeout(LLMError):
    """Ollama не ответила в отведённое время (GPU забит игрой/OBS)."""


class LLMHTTPError(LLMError):
    """Ollama ответила HTTP-ошибкой."""


def _host() -> str:
    base = Config.LLM_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base


def _to_native(messages: list) -> list:
    native = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            native.append({"role": m.get("role", "user"), "content": content})
            continue
        texts, images = [], []
        for part in content:
            if part.get("type") == "text" and part.get("text"):
                texts.append(part["text"])
            elif part.get("type") == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                if "," in url:
                    images.append(url.split(",", 1)[1])
        entry = {"role": m.get("role", "user"), "content": "\n".join(texts)}
        if images:
            entry["images"] = images
        native.append(entry)
    return native


def health(timeout: float = 2.0) -> bool:
    """Отвечает ли сервер Ollama. Дёшево: GET /api/version, модель не трогаем."""
    try:
        return requests.get(f"{_host()}/api/version", timeout=timeout).status_code == 200
    except Exception:
        # Нет сервера, таймаут или песочница без requests — всё это «недоступна».
        return False


_server_lock = threading.Lock()
_last_autostart = 0.0
_AUTOSTART_COOLDOWN = 300.0  # сек: не плодим `ollama serve` на каждом цикле


def ensure_server(wait: float = 25.0) -> bool:
    """True, если Ollama отвечает. Если лежит и разрешён автостарт — поднимаем
    `ollama serve` (не чаще раза в 5 минут) и ждём до `wait` секунд."""
    global _last_autostart
    if health():
        return True
    if not Config.OLLAMA_AUTOSTART:
        return False
    with _server_lock:
        if health():  # другой поток поднял, пока ждали лок
            return True
        if time.monotonic() - _last_autostart < _AUTOSTART_COOLDOWN:
            return False
        _last_autostart = time.monotonic()
        exe = shutil.which("ollama")
        if not exe:
            logger.error("Ollama не отвечает, а `ollama` не найден в PATH")
            return False
        logger.warning("Ollama не отвечает — поднимаю `ollama serve`...")
        try:
            subprocess.Popen(
                [exe, "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            logger.error(f"Ollama не поднять: {e}")
            return False
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(1.0)
            if health():
                logger.info("Ollama поднята, сервер отвечает")
                return True
        logger.error(f"Ollama не поднялась за {wait:.0f}с")
        return False


def chat(
    messages: list,
    model: str,
    max_tokens: int,
    temperature: float,
    extra_options: dict | None = None,
    timeout: int = 60,
) -> str | None:
    """Ответ модели или None (модель ответила пустотой). Транспортные сбои —
    через LLMError: вызывающий решает, ждать или идти в фолбэк."""
    options = {
        "temperature": temperature,
        "num_predict": max_tokens,
    }
    if extra_options:
        options.update(extra_options)
    try:
        r = requests.post(
            f"{_host()}/api/chat",
            headers={"Content-Type": "application/json"},
            json={
                "model": model,
                "messages": _to_native(messages),
                "stream": False,
                "think": False,
                # Модель не выгружать между запусками бота: холодный старт
                # (загрузка 3.3 ГБ + первое vision-инференс) упирался в 60с таймаут.
                "keep_alive": "30m",
                "options": options,
            },
            timeout=timeout,  # локальная модель; vision передаёт свой короткий лимит
        )
        r.raise_for_status()
        content = (r.json().get("message") or {}).get("content")
        if not content or not content.strip():
            return None
        return content.strip()
    except requests.exceptions.Timeout as e:
        raise LLMTimeout(f"таймаут {timeout}с") from e
    except requests.exceptions.ConnectionError as e:
        raise LLMUnavailable("Ollama не слушает порт") from e
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        raise LLMHTTPError(f"HTTP {code}") from e
    except requests.exceptions.RequestException as e:
        raise LLMError(type(e).__name__) from e
