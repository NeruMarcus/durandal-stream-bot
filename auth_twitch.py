"""Одноразовая авторизация Twitch (twitchio v3).

Запуск:  run.bat auth
Браузер с Authorize откроется сам. Войди под аккаунтом nerumarcus
и нажми Authorize. Токены сохранятся в .tio.tokens.json,
бот подхватит их сам. Остановка: Ctrl+C
"""

import asyncio
import webbrowser

from twitch.chat import DurandalBot
from logger import logger

AUTH_URL = (
    "http://localhost:4343/oauth"
    "?scopes=user:read:chat+user:bot+channel:bot&force_verify=true"
)


async def _port_busy() -> bool:
    import socket

    try:
        s = socket.create_connection(("127.0.0.1", 4343), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _probe_once() -> bool:
    """ Синхронная проба роута. Вызывать ТОЛЬКО через to_thread — не вешать loop. """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:4343/oauth/callback", timeout=2
        ):
            return True
    except urllib.error.HTTPError as e:
        return e.code == 400
    except Exception:
        return False


async def _wait_adapter(timeout: float = 120.0) -> bool:
    """ Ждём живые роуты. Проба в отдельном потоке, иначе душим старт адаптера. """
    for _ in range(int(timeout / 2)):
        if await asyncio.to_thread(_probe_once):
            return True
        await asyncio.sleep(2)
    return False


async def _open_when_ready() -> None:
    if await _wait_adapter():
        logger.info("Открываю браузер для авторизации...")
        try:
            webbrowser.open(AUTH_URL)
        except Exception as e:
            logger.warning(f"Не смог открыть браузер: {e}. Открой вручную: {AUTH_URL}")
    else:
        logger.warning(f"Адаптер не поднялся. Открой вручную: {AUTH_URL}")


async def main() -> None:
    if await _port_busy():
        logger.warning(
            "Порт 4343 уже занят — похоже, запущена вторая копия auth. "
            "Закрой старое окно и повтори."
        )
        return
    bot = DurandalBot(lambda user, text: None)
    logger.info(f"Если браузер не открылся: {AUTH_URL}")
    opener = asyncio.create_task(_open_when_ready())
    try:
        await bot.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Авторизация прервана")
    finally:
        opener.cancel()
        try:
            await opener
        except asyncio.CancelledError:
            pass
        try:
            await bot.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
