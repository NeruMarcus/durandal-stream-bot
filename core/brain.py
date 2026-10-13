import asyncio
import random
import time

from config import Config
from core.emotions import parse_emotion
from core.memory import DialogueMemory
from logger import logger

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


class Brain:
    def __init__(self):
        self.memory = DialogueMemory()
        self._last_request = 0.0

    async def generate(self, system: str, user: str) -> tuple[str, str]:
        now = time.time()
        since_last = now - self._last_request
        if since_last < 2.0:
            await asyncio.sleep(2.0 - since_last)

        messages = [{"role": "system", "content": system}]
        messages.extend(self.memory.get_context(20))
        messages.append({"role": "user", "content": user})

        from core.ollama import chat as ollama_chat

        try:
            text = await asyncio.to_thread(
                ollama_chat, messages, Config.LLM_MODEL, 300, 0.85
            )
        except Exception as e:
            logger.warning(f"Ollama chat: {type(e).__name__}")
            return random.choice(_CHAT_FALLBACKS), "neutral"
        self._last_request = now
        if not text:
            return random.choice(_CHAT_FALLBACKS), "neutral"

        self.memory.add_user(user)
        clean, emotion = parse_emotion(text)
        self.memory.add_assistant(clean)
        logger.info(f"LLM chat: {Config.LLM_MODEL}")
        return clean, emotion
