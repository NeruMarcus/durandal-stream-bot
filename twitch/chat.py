import asyncio
import time

import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from config import Config
from logger import logger


def _clean_token(raw: str) -> str:
    """ v3 хочет голый токен без префикса oauth:. """
    token = (raw or "").strip()
    if token.lower().startswith("oauth:"):
        token = token[len("oauth:"):]
    return token.strip()


class DurandalBot(commands.AutoBot):
    """Read-only слушатель чата через EventSub (twitchio v3, IRC больше нет).

    Подписка channel.chat.message создаётся автоматически из конструктора.
    Требуется: CLIENT_ID + CLIENT_SECRET приложения, BOT_ID, CHANNEL_ID
    и user-токен со скопом user:read:chat.
    """

    def __init__(self, on_message_callback):
        if not Config.TWITCH_BOT_ID or not Config.TWITCH_CHANNEL_ID:
            raise RuntimeError(
                "TWITCH_BOT_ID / TWITCH_CHANNEL_ID не заданы — "
                "возьми ID на https://twitchtokengenerator.com или "
                "через https://api.twitch.tv/helix/users?login=<ник>"
            )
        subs = [
            eventsub.ChatMessageSubscription(
                broadcaster_user_id=Config.TWITCH_CHANNEL_ID,
                user_id=Config.TWITCH_BOT_ID,
            )
        ]
        super().__init__(
            client_id=Config.TWITCH_CLIENT_ID,
            client_secret=Config.TWITCH_CLIENT_SECRET,
            bot_id=Config.TWITCH_BOT_ID,
            owner_id=Config.TWITCH_CHANNEL_ID,
            prefix="!",
            # Должен буква в букву совпадать с OAuth Redirect URL в консоли Twitch.
            redirect_uri="http://localhost:4343/oauth/callback",
            subscriptions=subs,
        )
        self._callback = on_message_callback
        self._cooldown = Config.CHAT_COOLDOWN
        self._last_response = 0.0
        self._pending = 0

    def _wanted_subs(self):
        return [
            eventsub.ChatMessageSubscription(
                broadcaster_user_id=Config.TWITCH_CHANNEL_ID,
                user_id=self.bot_id,
            )
        ]

    @staticmethod
    def _sub_problems(resp) -> list:
        # 409 (уже подписаны) — не ошибка, как считает и сама twitchio.
        return [e for e in (resp.errors or [])
                if getattr(e.error, "status", None) != 409]

    async def _ensure_subscription(self) -> None:
        """Подписка channel.chat.message с видимым результатом.

        Стартовый subscribe в twitchio нередко обгоняет готовность сессии
        (тот самый warning 1/1 failed) — дублируем его здесь и в event_ready.
        """
        try:
            resp = await self.multi_subscribe(self._wanted_subs())
            errs = self._sub_problems(resp)
            if errs:
                logger.warning(f"Twitch subscribe: {errs}")
            else:
                logger.info("Twitch subscribe ok: channel.chat.message")
        except Exception as e:
            logger.error(f"Twitch subscribe: {type(e).__name__}: {e}")

    async def setup_hook(self) -> None:
        token = _clean_token(Config.TWITCH_TOKEN)
        if not token:
            return
        refresh = (Config.TWITCH_REFRESH_TOKEN or "").strip()
        try:
            await self.add_token(token, refresh)
            if not refresh:
                logger.warning(
                    "TWITCH_REFRESH_TOKEN пуст — токен не сможет автообновиться, "
                    "при протухании понадобится новый"
                )
        except Exception as e:
            logger.error(f"Twitch add_token: {type(e).__name__}: {e}")
            raise

    async def event_oauth_authorized(
        self, payload: twitchio.authentication.UserTokenPayload,
    ) -> None:
        await self.add_token(payload.access_token, payload.refresh_token)
        logger.info(f"Twitch OAuth: {payload.user_login} (id={payload.user_id})")
        await self._ensure_subscription()

    async def event_ready(self) -> None:
        logger.info(
            f"Twitch EventSub: #{Config.TWITCH_CHANNEL} "
            f"(bot_id={self.bot_id}) — чат слушается"
        )
        await self._ensure_subscription()

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        name = payload.chatter.display_name or payload.chatter.name
        if payload.chatter.id == self.bot_id:
            # Бот только читает и никогда не пишет сам: это человек пишет
            # с аккаунта бота (для соло-теста — со второго аккаунта).
            logger.debug(f"Twitch [{name}]: своё сообщение, пропуск")
            return
        if payload.source_broadcaster is not None:
            logger.debug(f"Twitch [{name}]: репост shared-чата, пропуск")
            return  # репост из shared-чата, не дублируем

        text = (payload.text or "").strip()
        if not text or text.startswith("!"):
            logger.debug(f"Twitch [{name}]: пустое/команда, пропуск")
            return

        now = time.monotonic()
        if now - self._last_response < self._cooldown:
            logger.debug(f"Twitch [{name}]: кулдаун, пропуск")
            return
        self._last_response = now

        logger.info(f"Twitch [{name}]: {text}")
        # Не вешаем диспетчер событий на долгий LLM: отвечаем в фоне.
        # _tts_lock в main всё равно сериализует озвучку, оверлей покажет свежее.
        if self._pending >= 2:
            logger.warning("Twitch: очередь ответов полна, пропуск")
            return
        self._pending += 1
        asyncio.create_task(self._answer(name, text))

    async def _answer(self, user: str, text: str) -> None:
        try:
            await self._callback(user, text)
        except Exception as e:
            logger.error(f"Twitch callback: {type(e).__name__}: {e}")
        finally:
            self._pending -= 1
