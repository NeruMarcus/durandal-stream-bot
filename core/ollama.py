"""Нативный /api/chat Ollama (не OpenAI-совместимый /v1).

Причина: у нативного API images: [base64 без префикса] и параметр "think",
который гасит болтовню думающих моделей. Плюс один слой меньше между
нас и локальным сервером.
"""

import requests

from config import Config
from logger import logger


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


def chat(
    messages: list,
    model: str,
    max_tokens: int,
    temperature: float,
    extra_options: dict | None = None,
    timeout: int = 60,
) -> str | None:
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
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        logger.warning(f"Ollama: HTTP {code}")
        return None
