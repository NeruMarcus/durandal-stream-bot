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
        # Троттл обновляем сразу: иначе серия ошибок даёт burst повторных
        # запросов, когда Ollama и так под нагрузкой.
        self._last_request = time.time()

        messages = [{"role": "system", "content": system}]
        messages.extend(self.memory.get_context(12))
        messages.append({"role": "user", "content": user})

        from core.ollama import chat as ollama_chat

        try:
            # 180, а не 300: sanitize всё равно режет до ~220 символов,
            # хвост генерации под нагрузкой — лишние секунды молчания.
            text = await asyncio.to_thread(
                ollama_chat, messages, Config.LLM_MODEL, 180, 0.85
            )
        except Exception as e:
            logger.warning(f"Ollama chat: {type(e).__name__}")
            return random.choice(_CHAT_FALLBACKS), "neutral"
        if not text:
            return random.choice(_CHAT_FALLBACKS), "neutral"

        self.memory.add_user(user)
        clean, emotion = parse_emotion(text)
        self.memory.add_assistant(clean)
        logger.info(f"LLM chat: {Config.LLM_MODEL}")
        return clean, emotion
