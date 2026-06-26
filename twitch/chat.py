import asyncio

from twitchio.ext import commands

from config import Config
from logger import logger


class DurandalBot(commands.Bot):
    def __init__(self, on_message_callback):
        super().__init__(
            token=Config.TWITCH_TOKEN,
            client_id=Config.TWITCH_CLIENT_ID,
            nick=Config.TWITCH_NICK,
            prefix="!",
            initial_channels=[Config.TWITCH_CHANNEL],
        )
        self._callback = on_message_callback
        self._cooldown = Config.CHAT_COOLDOWN
        self._last_response = 0.0

    async def event_ready(self):
        logger.info(f"Twitch: подключился как {self.nick}")

    async def event_message(self, message):
        if message.author is None:
            return
        if message.author.name.lower() == Config.TWITCH_NICK.lower():
            return
        if message.content and message.content.startswith("!"):
            return

        now = asyncio.get_event_loop().time()
        if now - self._last_response < self._cooldown:
            return
        self._last_response = now

        logger.info(f"Twitch [{message.author.name}]: {message.content}")
        await self._callback(message.author.name, message.content)
