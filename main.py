import array
import asyncio
import json
import math
import os
import subprocess
import tempfile
import threading
import time
import wave
import shutil
from concurrent.futures import ThreadPoolExecutor

import imageio_ffmpeg

from config import Config
from personality import (
    generate_vision_commentary,
    generate_fallback,
    _CHAT_SYSTEM,
)
from core.brain import Brain
from logger import logger


_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_OVERLAY_STATE = Config.OVERLAY_STATE
_TEMP_DIR = Config.TEMP_DIR

os.makedirs(_TEMP_DIR, exist_ok=True)


def _prune_temp(max_age_sec: float | None = None):
    """Чистим накопленные TTS/скриншот-файлы в temp/.

    Без max_age_sec (на старте) удаляем всё, кроме состояния оверлея. С max_age_sec
    удаляем только файлы старше указанного возраста — для чистки во время работы,
    не задевая свежие промежуточные файлы.
    """
    keep = {"overlay_state.json", ".gitkeep"}
    now = time.time()
    try:
        for name in os.listdir(_TEMP_DIR):
            if name in keep:
                continue
            path = os.path.join(_TEMP_DIR, name)
            try:
                if not os.path.isfile(path):
                    continue
                # Пустышки от несостоявшихся записей (оборванный edge-tts и т.п.) —
                # в утиль сразу, вне зависимости от возраста.
                if os.path.getsize(path) == 0:
                    os.remove(path)
                    continue
                if max_age_sec is not None and now - os.path.getmtime(path) < max_age_sec:
                    continue
                os.remove(path)
            except OSError:
                pass
    except OSError as e:
        logger.warning(f"temp очистка: {e}")


# Стартовый проход — только из main(): import модуля не должен стирать файлы.
def _prune_startup():
    _prune_temp()

_tts_lock = asyncio.Lock()
_brain = Brain()
# Один поток: если LLM зависнет, следующий цикл встанет в очередь,
# а не насует параллельных зависших вызовов.
_VISION_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")


# ── Overlay ─────────────────────────────────────────────────────────────────


_current_overlay = {"text": "", "emotion": "neutral", "status": ""}
# RLock: мутация кадра и запись файла — одна атомарная секция (_state_json
# читает словарь, _atomic_write тоже берёт лок).
_state_lock = threading.RLock()
_speaking = False


def _atomic_write(data: str):
    # Атомарно: OBS-поллер не должен поймать полузаписанный JSON.
    # Лок — поток эквалайзера и event-loop пишут один и тот же .tmp.
    tmp = _OVERLAY_STATE + ".tmp"
    with _state_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        # Windows: читатель (overlay_server поллит каждые 120 мс) может держать
        # файл открытым без FILE_SHARE_DELETE — тогда os.replace даёт WinError 5.
        # Ретраим замену, а не падаем: окно гонки — доли миллисекунды.
        for attempt in range(8):
            try:
                os.replace(tmp, _OVERLAY_STATE)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.01 * (attempt + 1))


def _state_json(speaking: bool, energy: float, status: str | None = None) -> str:
    return json.dumps(
        {
            "text": _current_overlay["text"],
            "emotion": _current_overlay["emotion"],
            "speaking": speaking,
            "energy": round(energy, 3),
            # Пустой status — оверлей выводит свой (TRANSMITTING/RENDERING/...).
            "status": _current_overlay["status"] if status is None else status,
            "timestamp": time.time(),
        },
        ensure_ascii=False,
    )


def _save_overlay(text: str, emotion: str = "neutral", speaking: bool = False):
    with _state_lock:
        _current_overlay["text"] = text
        _current_overlay["emotion"] = emotion
        _current_overlay["status"] = ""
        _atomic_write(_state_json(speaking, 0.0))


def _set_speaking(on: bool):
    global _speaking
    with _state_lock:
        _speaking = on
        _current_overlay["status"] = ""
        _atomic_write(_state_json(on, 0.0))


def _set_status(status: str):
    """Стадия пайплайна в шапку оверлея (ANALYZING/THINKING/SYNTHESIZING)."""
    with _state_lock:
        _current_overlay["status"] = status
        _atomic_write(_state_json(_speaking, 0.0))


# ── Audio pipeline ──────────────────────────────────────────────────────────


def _rms_envelope(path: str, fps: int = 15) -> list[float]:
    """Нормированная (0..1) громкость по кадрам — для эквалайзера оверлея."""
    try:
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                return []
            frames = w.readframes(w.getnframes())
            rate, channels = w.getframerate(), w.getnchannels()
        samples = array.array("h")
        samples.frombytes(frames)
        if channels > 1:
            samples = samples[::channels]
        step = max(1, rate // fps)
        rms = []
        for i in range(0, len(samples), step):
            chunk = samples[i:i + step]
            if not chunk:
                break
            rms.append(math.sqrt(sum(x * x for x in chunk) / len(chunk)))
        peak = max(rms, default=0.0)
        if peak <= 0:
            return []
        # sqrt «вытягивает» тихие слоги, чтобы полоски живо реагировали.
        return [round((v / peak) ** 0.5, 3) for v in rms]
    except Exception:
        return []


def _is_direct_wav(path: str) -> bool:
    """Финальный wav пайплайна уже s16 — крутить через ffmpeg незачем (~1с экономии)."""
    try:
        with wave.open(path, "rb") as w:
            return w.getsampwidth() == 2
    except Exception:
        return False


def _play_local(path: str):
    """ Синхронное проигрывание: winsound требует живой файл весь трек. """
    wav, owned = path, False
    if not _is_direct_wav(path):
        # mp3 от edge-tts и прочие форматы — гоним через ffmpeg в s16 wav.
        fd, wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        owned = True
        try:
            r = subprocess.run(
                [_FFMPEG, "-y", "-i", path, "-sample_fmt", "s16", "-f", "wav", wav],
                capture_output=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg convert: timeout, копия без конверсии")
            r = None
        if r is None or r.returncode != 0:
            shutil.copy2(path, wav)
    stop = threading.Event()
    try:
        # Пока играет — шлём громкость в оверлей, чтобы эквалайзер реагировал на голос.
        envelope = _rms_envelope(wav)
        if envelope:
            fps = 15

            def pump():
                start = time.monotonic()
                for i, level in enumerate(envelope):
                    if stop.is_set():
                        return
                    delay = (start + i / fps) - time.monotonic()
                    if delay > 0:
                        stop.wait(delay)
                    if stop.is_set():
                        return
                    # Статус жёстко пустой: идёт голос — оверлей покажет TRANSMITTING.
                    # Кадр не критичен: лок читателя — пропускаем, эквалайзер не заметит.
                    try:
                        _atomic_write(_state_json(True, level, ""))
                    except OSError:
                        pass

            threading.Thread(target=pump, daemon=True, name="eq").start()

        import winsound

        winsound.PlaySound(wav, winsound.SND_FILENAME)
    except Exception as e:
        logger.warning(f"winsound: {e}")
    finally:
        stop.set()
        if owned:
            _cleanup(wav)


def _cleanup(path: str):
    try:
        os.remove(path)
    except Exception:
        pass


async def _speak(text: str) -> bool:
    """Generate TTS and play. Returns True if successful."""
    async with _tts_lock:
        _set_speaking(True)
        _set_status("SYNTHESIZING // VOICE")
        try:
            from voice.tts import text_to_speech

            tts_path = await asyncio.wait_for(
                text_to_speech(text), timeout=120
            )
            if not tts_path or not os.path.exists(tts_path):
                return False

            try:
                from voice.audiofx import process_speech

                final = await asyncio.wait_for(
                    asyncio.to_thread(process_speech, tts_path), timeout=30
                )
                _cleanup(tts_path)
            except Exception:
                final = tts_path

            logger.info("Воспроизведение")
            await asyncio.to_thread(_play_local, final)
            _cleanup(final)
            return True
        except Exception as e:
            logger.error(f"TTS: {e}")
            return False
        finally:
            _set_speaking(False)
            # Страховка от роста temp за долгий стрим: убираем старое (> 1 ч).
            _prune_temp(3600)


# ── Vision commentary loop ──────────────────────────────────────────────────


async def _vision_loop():
    global _VISION_EXEC
    loop = asyncio.get_running_loop()
    pending = None
    while True:
        cycle_start = time.time()
        # Если предыдущий вызов завис — не плодим очередь, пропускаем цикл,
        # пока воркер не освободится.
        if pending is not None and not pending.done():
            logger.warning("Vision: предыдущий вызов ещё идёт, пропуск цикла")
            await asyncio.sleep(Config.COMMENT_INTERVAL)
            continue
        _set_status("ANALYZING // FRAME")
        # Сторож LLM: закрытая Ollama иначе даёт 90с ожидания и «Vision сцена:
        # пусто» в логе, а реплика всё равно уходит заготовкой. Проверяем (и,
        # если разрешено, поднимаем сервер) до вызова зрения.
        from core.ollama import ensure_server
        if not await asyncio.to_thread(ensure_server):
            logger.error(
                "Vision: Ollama недоступна — комментарий заготовкой "
                "(включи OLLAMA_AUTOSTART или подними `ollama serve`)"
            )
            result = generate_fallback()
            pending = None
        else:
            try:
                pending = loop.run_in_executor(
                    _VISION_EXEC, generate_vision_commentary
                )
                result = await asyncio.wait_for(pending, timeout=150)
            except asyncio.TimeoutError:
                logger.warning("Vision timeout, фолбек")
                result = generate_fallback()
                # wait_for поток не убивает: зависший воркер иначе держал бы
                # единственный слот вечно и все следующие циклы пропускались бы.
                # Старый executor глушим, дальше работает свежий; зависший поток
                # умирает сам, когда его HTTP-таймаут (90с) догорит.
                if pending is not None and not pending.done():
                    try:
                        _VISION_EXEC.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                    _VISION_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")
                    pending = None
            except Exception as e:
                logger.error(f"Vision: {type(e).__name__}: {e}")
                result = generate_fallback()

        # Тело цикла в try: любая ошибка (оверлей, звук, статус) не должна
        # убивать задачу — иначе asyncio.gather падает и бот молча умирает.
        try:
            if result is None:
                # Кадр не изменился — молчим, ждём следующий цикл.
                _set_status("")
                elapsed = time.time() - cycle_start
                remaining = Config.COMMENT_INTERVAL - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
                continue

            commentary, emotion = result
            _save_overlay(commentary, emotion)
            logger.info(f"Комментарий: {commentary}")

            await _speak(commentary)

            elapsed = time.time() - cycle_start
            remaining = Config.COMMENT_INTERVAL - elapsed
            if remaining > 0:
                logger.info(f"Пауза {remaining:.0f}с до следующего цикла")
                await asyncio.sleep(remaining)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Vision-цикл: {type(e).__name__}: {e}")
            await asyncio.sleep(5)


# ── Twitch callback ─────────────────────────────────────────────────────────


async def _on_chat(user: str, text: str):
    # Чтение мгновенно, видимая стадия — долгое думание LLM.
    _set_status("THINKING // LLM")
    response, emotion = await _brain.generate(_CHAT_SYSTEM, f"{user}: {text}")
    _save_overlay(response, emotion)
    await _speak(response)


# ── Twitch с автореконнектом ──────────────────────────────────────────────────


async def _twitch_loop():
    from twitch.chat import DurandalBot

    delay = 5
    while True:
        bot = None
        started = time.monotonic()
        try:
            bot = DurandalBot(_on_chat)
            logger.info("Запуск Twitch бота...")
            await bot.start()
            logger.warning("Twitch бот остановлен, перезапуск...")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Twitch: {type(e).__name__}: {e} — рестарт через {delay}с")
        finally:
            if bot is not None:
                try:
                    await bot.close()
                except Exception:
                    pass
        # Бэкофф растёт только на «шторме» перезапусков; после долгой сессии сбрасываем.
        if time.monotonic() - started > 60:
            delay = 5
        await asyncio.sleep(delay)
        delay = min(delay * 2, 300)


# ── RVC warmup ──────────────────────────────────────────────────────────────


def _warmup_rvc():
    """ Греем демон заранее: первая реплика не будет ждать загрузки моделей. """
    try:
        import struct
        import time

        warm = os.path.join(_TEMP_DIR, "_warmup.wav")
        with wave.open(warm, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(struct.pack("<" + "h" * 24000, *([0] * 24000)))
        import rvc_convert

        t0 = time.monotonic()
        out = rvc_convert.rvc_convert(
            warm, f0up_key=1, index_rate=Config.RVC_INDEX_RATE,
            resample_sr=Config.RVC_RESAMPLE_SR,
            rms_mix_rate=Config.RVC_RMS_MIX_RATE, protect=Config.RVC_PROTECT,
        )
        _cleanup(out)
        logger.info(f"RVC warmup ok ({time.monotonic() - t0:.1f}с, {Config.RVC_DEVICE})")
    except Exception as e:
        logger.warning(f"RVC warmup: {type(e).__name__}: {e}")
    finally:
        _cleanup(os.path.join(_TEMP_DIR, "_warmup.wav"))


# ── LLM warmup ──────────────────────────────────────────────────────────────


def _warmup_llm():
    """ Греем локальную модель заранее: первая реплика не будет ждать загрузки. """
    from core.ollama import LLMError, chat as ollama_chat, ensure_server

    if not ensure_server():
        logger.error("LLM warmup: Ollama недоступна — комментарии пойдут заготовками")
        return
    try:
        text = ollama_chat(
            [{"role": "user", "content": "Ответь одним словом: готов."}],
            Config.LLM_MODEL,
            20,
            0.5,
        )
        if text:
            logger.info(f"LLM warmup ok: {Config.LLM_MODEL}")
        else:
            logger.warning(f"LLM warmup {Config.LLM_MODEL}: пустой ответ")
    except LLMError as e:
        logger.warning(f"LLM warmup {Config.LLM_MODEL}: {e}")


# ── Main ────────────────────────────────────────────────────────────────────


def _overlay_port_busy(host: str = "127.0.0.1", port: int = 9733) -> bool:
    """Порт оверлея уже слушают: второй сервер в daemon-потоке умер бы молча."""
    import socket

    try:
        s = socket.create_connection((host, port), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _twitch_config_ok() -> bool:
    return all(
        [
            Config.TWITCH_CLIENT_ID,
            Config.TWITCH_CLIENT_SECRET,
            Config.TWITCH_BOT_ID,
            Config.TWITCH_CHANNEL_ID,
        ]
    )


async def main():
    from overlay_server import main as overlay_main

    _prune_startup()

    # Маркер сессии: в bot.log нет даты, а дописывают несколько запусков
    # подряд — границу ищем по этой строке, а не по warmup.
    import datetime
    logger.info(
        "=== запуск "
        f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
        f"(RVC {'выкл' if not Config.USE_RVC else Config.RVC_DEVICE}) ==="
    )

    if _overlay_port_busy():
        logger.warning(
            "Порт 9733 уже занят — похоже, оверлей уже запущен "
            "(вторая копия бота?). Этот экземпляр state писать будет, "
            "а сервер не поднимаю."
        )
    else:
        logger.info("Запуск overlay сервера на http://127.0.0.1:9733/overlay")
        t = threading.Thread(target=overlay_main, daemon=True)
        t.start()
        await asyncio.sleep(1)

    _save_overlay("")

    # Ссылки на warmup-задачи держим в локальной переменной: main живёт
    # пока gather, так что задачи не будут подобраны сборщиком мусора.
    warmup_tasks: list[asyncio.Task] = []
    if Config.USE_RVC:
        logger.info("RVC warmup в фоне...")
        warmup_tasks.append(asyncio.create_task(asyncio.to_thread(_warmup_rvc)))

    # LLM греем СТРОГО до старта vision-цикла и ждём: холодная модель +
    # параллельный vision-запрос сериализуются в llama-server и первый
    # комментарий упирается в 60с таймаут. Warmup = загрузчик + гейт.
    logger.info("LLM warmup, ждём прогрев модели...")
    await asyncio.to_thread(_warmup_llm)

    tasks = [asyncio.create_task(_vision_loop())]

    token_file = os.path.join(os.path.dirname(__file__), ".tio.tokens.json")
    use_twitch = (bool(Config.TWITCH_TOKEN) or os.path.exists(token_file)) and _twitch_config_ok()
    if use_twitch:
        tasks.append(asyncio.create_task(_twitch_loop()))
    else:
        logger.info("Нет Twitch-токена/ID (см. auth_twitch.py), только офлайн режим")

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Остановка...")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        _set_speaking(False)
        logger.info("Остановлен")


if __name__ == "__main__":
    import faulthandler
    import sys
    import traceback

    # Жёсткие падения (нативный крэш, убийство процесса) пишем в файл: в
    # консоли traceback теряется, а по bot.log конец выглядит «просто оборвался».
    _crash = open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log"),
        "a",
        encoding="utf-8",
        buffering=1,
    )
    faulthandler.enable(file=_crash)

    def _excepthook(exc_type, exc, tb):
        logger.error("Необработанное исключение:")
        for line in traceback.format_exception(exc_type, exc, tb):
            for part in line.rstrip("\n").splitlines():
                logger.error(part)

    sys.excepthook = _excepthook

    if sys.version_info < (3, 14):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
