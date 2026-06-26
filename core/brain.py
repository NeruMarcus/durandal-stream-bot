import asyncio
import random
import re
import time

import requests

from config import Config
from core.memory import DialogueMemory

_EMOTIONS = {"sarcastic", "angry", "mocking", "calm", "neutral", "саркастичный", "злой", "насмешливый", "спокойный"}

_EMOTION_RE = re.compile(
    r"(?i)^\s*\[?(sarcastic|angry|mocking|calm|neutral|"
    r"саркастичный|злой|насмешливый|спокойный)\]?[\s:,-]+"
)

_CHAT_FALLBACKS = [
    "Хм. Я мог бы ответить, но стоит ли оно того?",
    "Твоё сообщение принято. Проанализировано. Проигнорировано.",
    "Ты ждёшь ответа? Мило.",
    "О, ты ещё здесь? А я думал, ты уже сдался.",
    "Даже не знаю, что сказать. Такое бывает редко. Шучу, просто лень.",
    "Твой запрос обрабатывается... обработка завершена. Ответ: нет.",
    "Я бы пошутил про твой уровень игры, но это было бы слишком жестоко.",
    "Ты действительно хочешь поговорить со мной? Ладно, получай.",
]


def _parse_emotion(text: str) -> tuple[str, str]:
    m = _EMOTION_RE.match(text)
    if m:
        result = text[m.end():]
        emotion = m.group(1).lower()
    else:
        result = text
        emotion = "neutral"
    result = re.sub(r"\[.*?\]", "", result).strip()
    return result, emotion


class Brain:
    def __init__(self):
        self.memory = DialogueMemory()
        self._last_request = 0.0

    async def generate(self, system: str, user: str) -> tuple[str, str]:
        now = time.time()
        since_last = now - self._last_request
        if since_last < 2.0:
            await asyncio.sleep(2.0 - since_last)

        for attempt in range(3):
            try:
                messages = [{"role": "system", "content": system}]
                messages.extend(self.memory.get_context(20))
                messages.append({"role": "user", "content": user})

                resp = requests.post(
                    "https://models.inference.ai.azure.com/chat/completions",
                    headers={
                        "Authorization": f"Bearer {Config.GITHUB_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "max_tokens": 200,
                        "temperature": 0.85,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                self._last_request = time.time()
                text = resp.json()["choices"][0]["message"]["content"].strip()

                self.memory.add_user(user)
                clean, emotion = _parse_emotion(text)
                self.memory.add_assistant(clean)
                return clean, emotion

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and attempt < 2:
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                return random.choice(_CHAT_FALLBACKS), "neutral"
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                return random.choice(_CHAT_FALLBACKS), "neutral"
