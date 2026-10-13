"""Durandal smoke check (песочница).

Запуск:  python check.py
Без сети, без токенов, без Twitch/RVC/edge-tts.
Проверяет структуру, синтаксис поведения чистой логики и overlay HTTP.

Exit 0 — всё ок / только предупреждения.
Exit 1 — есть FAIL.
"""

import importlib.util
import json
import os
import sys
import threading
import urllib.request
from http.server import HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Песочница обязана работать без сторонних зависимостей:
# подменяем отсутствующие dotenv/requests минимальными заглушками,
# чтобы чистая логика (config/personality/memory/overlay) тестировалась везде.
import types

if importlib.util.find_spec("dotenv") is None:
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _dotenv

if importlib.util.find_spec("requests") is None:
    _req = types.ModuleType("requests")

    class _HTTPError(Exception):
        def __init__(self, *a, response=None, **k):
            super().__init__(*a)
            self.response = response

    _exc = types.ModuleType("requests.exceptions")
    _exc.HTTPError = _HTTPError
    _req.exceptions = _exc

    def _post(*a, **k):
        raise RuntimeError("requests не установлен (песочница без сети)")

    _req.post = _post
    sys.modules["requests"] = _req
    sys.modules["requests.exceptions"] = _exc

PASS, FAIL, SKIP = [], [], []


def ok(name):
    PASS.append(name)
    print(f"  [PASS] {name}")


def fail(name, why):
    FAIL.append((name, why))
    print(f"  [FAIL] {name}: {why}")


def skip(name, why):
    SKIP.append((name, why))
    print(f"  [SKIP] {name}: {why}")


def has_module(name):
    if name in sys.modules and getattr(sys.modules[name], "__spec__", None) is None:
        return False  # наша заглушка песочницы, не настоящий пакет
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


print("== 1. Структура файлов ==")
for p in [
    "main.py", "config.py", "personality.py", "overlay_server.py",
    "screen_capture.py", "rvc_convert.py", "rvc_daemon.py", "logger.py",
    "run.bat", "requirements.txt", ".env.example", ".gitignore",
    "README.md", "LICENSE",
    "docs/screenshots/overlay_speaking.png", "docs/screenshots/overlay_idle.png",
    "core/brain.py", "core/emotions.py", "core/memory.py", "core/ollama.py", "Modelfile",
    "twitch/chat.py", "voice/tts.py", "voice/piper_tts.py", "voice/audiofx.py",
    "temp/.gitkeep", "auth_twitch.py",
]:
    if os.path.exists(os.path.join(ROOT, p)):
        ok(f"file:{p}")
    else:
        fail(f"file:{p}", "отсутствует")

print("== 2. requirements ==")
req_path = os.path.join(ROOT, "requirements.txt")
with open(req_path, encoding="utf-8") as f:
    req = f.read().lower()
for dep in ["imageio-ffmpeg", "python-dotenv", "requests", "pillow",
            "pywin32", "edge-tts", "twitchio"]:
    if dep in req:
        ok(f"req:{dep}")
    else:
        fail(f"req:{dep}", "нет в requirements.txt")

print("== 3. config/logger (чистая логика) ==")
try:
    from config import Config
    assert isinstance(Config.COMMENT_INTERVAL, int)
    assert Config.LLM_BASE_URL.startswith("http") and Config.LLM_MODEL
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    ok("config: импорт + TEMP_DIR создаётся")
except Exception as e:
    fail("config", str(e))

try:
    from logger import logger
    logger.info("check: logger ok")
    ok("logger: пишет в stdout + bot.log")
except Exception as e:
    fail("logger", str(e))

print("== 4. personality + core.emotions (без сети) ==")
try:
    import personality as P
    from core.emotions import EMOTION_OUT, parse_emotion

    t, emo = parse_emotion("[angry] Ты опять мимо")
    assert t and emo == "angry", (t, emo)
    ok("emotions: parse_emotion en")

    t2, emo2 = parse_emotion("[злой] Ты опять мимо")
    assert emo2 == "angry", (t2, emo2)
    ok("emotions: parse_emotion ru->en нормализация")

    t3, emo3 = parse_emotion("[насмешливый] Ну и дела")
    assert emo3 == "mocking", (t3, emo3)
    ok("emotions: ru->en насмешка")

    t4, _ = parse_emotion("(вздыхает) Ты опять мимо")
    assert not t4.startswith("("), t4
    ok("emotions: ремарки (…) вырезаны")

    t5, _ = parse_emotion("x" * 500)
    assert len(t5) <= 220, len(t5)
    ok("emotions: обрезка до 220")

    t6, emo6 = parse_emotion("[sarcastic]Без пробела")
    assert emo6 == "sarcastic" and t6 == "Без пробела", (t6, emo6)
    ok("emotions: тег без разделителя")

    t7, emo7 = parse_emotion("[чужое] текст")
    assert emo7 == "neutral" and not t7.startswith("["), (t7, emo7)
    ok("emotions: неизвестный тег не протекает в текст")

    t8, _ = parse_emotion("«Твоя меткость — подарок врагу.»")
    assert t8 == "Твоя меткость — подарок врагу.", t8
    ok("emotions: снятие обрамляющих кавычек")

    t9, emo9 = parse_emotion("[sarcastic] счёт [2:1] в твою пользу")
    assert emo9 == "sarcastic" and "[2:1]" in t9, (t9, emo9)
    ok("emotions: скобки в тексте целы, режется только эмоция-тег")

    t10, emo10 = parse_emotion("гнев: ты опять мимо")
    assert emo10 == "neutral" and t10 == "гнев: ты опять мимо", (t10, emo10)
    ok("emotions: тег без скобок — обычная фраза")

    seen = set()
    for _ in range(25):
        text, emotion = P.generate_fallback()
        assert text, "пустой фолбек"
        assert emotion in EMOTION_OUT, f"эмоция {emotion!r} сломает overlay badge"
        seen.add(text)
    assert len(seen) > 3, "фолбеки не варьируются"
    ok(f"personality: generate_fallback x25, уникальных {len(seen)}, эмоции только en")
except Exception as e:
    fail("personality", f"{type(e).__name__}: {e}")

print("== 5. core.memory / brain parsing ==")
try:
    from core.memory import DialogueMemory
    m = DialogueMemory(maxlen=5)
    for i in range(7):
        m.add_user(f"msg {i}")
    assert len(m.get_context(20)) == 5
    assert len(m.get_context(2)) == 2
    ok("memory: deque maxlen + окно")
except Exception as e:
    fail("memory", str(e))

try:
    from core.brain import Brain  # noqa: F401 — сам импорт уже проверка
    ok("brain: импорт модуля (без сети)")
except Exception as e:
    if "No module" in str(e):
        skip("brain", str(e))
    else:
        fail("brain", f"{type(e).__name__}: {e}")

print("== 6. overlay HTTP (локально, эфемерный порт) ==")
try:
    import overlay_server as O
    srv = HTTPServer(("127.0.0.1", 0), O._Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/state", timeout=5) as r:
        data = json.loads(r.read().decode())
        assert "text" in data and "emotion" in data
        for k in ("speaking", "energy", "timestamp"):
            assert k in data, f"в /state нет {k}"
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/overlay", timeout=5) as r:
        html = r.read().decode("utf-8")
        assert "DURANDAL" in html and "emotion-badge" in html
        for marker in ("TRANSMITTING // VOICE", 'class="cursor"',
                       'id="status"', 'id="eq"'):
            assert marker in html, f"нет {marker}"
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/font", timeout=5) as r:
        assert "font" in r.headers.get("Content-Type", ""), r.headers.get("Content-Type")
        assert len(r.read()) > 1000, "шрифт подозрительно мал"
    srv.shutdown()
    ok(f"overlay: /state + /overlay + /font отвечают (порт {port})")
    ok("overlay: терминал (печать/статус/эквалайзер) на месте")
except Exception as e:
    fail("overlay", f"{type(e).__name__}: {e}")

print("== 6b. main._rms_envelope (из AST, без импорта main) ==")
try:
    import array as _array
    import ast as _ast
    import math as _math
    import struct as _struct
    import wave as _wave
    _src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    _fn = next(n for n in _ast.parse(_src).body
               if isinstance(n, _ast.FunctionDef) and n.name == "_rms_envelope")
    _ns = {"array": _array, "math": _math, "wave": _wave}
    exec(compile(_ast.Module(body=[_fn], type_ignores=[]), "main.py", "exec"), _ns)
    _rms = _ns["_rms_envelope"]
    _wav = os.path.join(ROOT, "temp", "_check_rms.wav")
    with _wave.open(_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(_struct.pack("<16000h", *([0] * 4000 + [10000] * 4000
                                                + [0] * 4000 + [3000] * 4000)))
    try:
        _env = _rms(_wav)
        assert _env and all(0.0 <= v <= 1.0 for v in _env), _env
        assert max(_env) == 1.0 and min(_env) < 0.6, _env
        ok(f"rms_envelope: пик 1.0, тишина ниже (кадров {len(_env)})")
    finally:
        os.remove(_wav)
    with _wave.open(_wav, "wb") as w:  # 8 бит не поддерживаем
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(bytes(8000))
    try:
        assert _rms(_wav) == []
        ok("rms_envelope: 8-битный wav -> []")
    finally:
        os.remove(_wav)
    assert _rms(os.path.join(ROOT, "temp", "нет_такого.wav")) == []
    ok("rms_envelope: битый путь -> []")
except Exception as e:
    fail("rms_envelope", f"{type(e).__name__}: {e}")

print("== 6c. Piper offline TTS (SKIP = движок не скачан) ==")
try:
    import array as _arr2
    import wave as _wave2
    from voice import piper_tts as _pt
    assert _pt.BIN_URL.startswith("https://") and _pt.BIN_URL.endswith(".zip")
    assert len(_pt.VOICE_URLS) == 2
    ok("piper: модуль + URL движка и голоса")
    if _pt._find_exe() and os.path.isfile(_pt.VOICE_ONNX):
        _out = None
        try:
            _out = _pt.synthesize("Тестовая фраза Дюрандаля.", length_scale="1.0")
            with _wave2.open(_out, "rb") as w:
                assert w.getsampwidth() == 2 and w.getframerate() == 22050
                _s = _arr2.array("h")
                _s.frombytes(w.readframes(w.getnframes()))
            assert max(abs(x) for x in _s) > 1000, "тишина"
            ok("piper: офлайн-синтез работает (22050 Гц, не тишина)")
        finally:
            if _out:
                try:
                    os.remove(_out)
                except OSError:
                    pass
    else:
        skip("piper", "движок/голос не скачаны (run.bat piper)")
except Exception as e:
    fail("piper", f"{type(e).__name__}: {e}")

print("== 7. Опциональные зависимости (SKIP = нет в этом python) ==")
for mod, label in [
    ("requests", "LLM cloud"),
    ("PIL", "скриншоты"),
    ("edge_tts", "TTS"),
    ("twitchio", "Twitch чат"),
    ("imageio_ffmpeg", "ffmpeg"),
]:
    if has_module(mod):
        ok(f"dep:{label} ({mod}) установлен")
    else:
        skip(f"dep:{label} ({mod})", "не установлен в этом интерпретаторе")

print("== 8. Twitch v3 (фейковые события, без сети) ==")
try:
    import asyncio
    import types as _t
    from config import Config as _Cfg
    from twitch.chat import DurandalBot, _clean_token

    assert _clean_token("oauth:abc123") == "abc123"
    assert _clean_token("  xyz  ") == "xyz"
    ok("twitch: _clean_token срезает oauth:")

    _saved = (_Cfg.TWITCH_BOT_ID, _Cfg.TWITCH_CHANNEL_ID,
              _Cfg.TWITCH_CLIENT_ID, _Cfg.TWITCH_CLIENT_SECRET)
    _Cfg.TWITCH_BOT_ID, _Cfg.TWITCH_CHANNEL_ID = "111", "222"
    _Cfg.TWITCH_CLIENT_ID, _Cfg.TWITCH_CLIENT_SECRET = "cid", "csecret"
    try:
        calls = []

        async def _cb(user, text):
            calls.append((user, text))

        bot = DurandalBot(_cb)
        assert bot.bot_id == "111"
        ok("twitch: AutoBot конструируется без сети")

        def _msg(uid, name, text, shared=False):
            return _t.SimpleNamespace(
                chatter=_t.SimpleNamespace(id=uid, name=name, display_name=name),
                text=text,
                source_broadcaster=_t.SimpleNamespace() if shared else None,
            )

        async def _run_cases():
            await bot.event_message(_msg("999", "Zed", "привет, Дюрандаль"))
            await bot.event_message(_msg("999", "Zed", "второе подряд"))  # кулдаун
            await bot.event_message(_msg("111", "Bot", "я сам"))  # своё
            await bot.event_message(_msg("999", "Zed", "!хи"))  # команда
            await bot.event_message(_msg("999", "Zed", "   "))  # пустое
            await bot.event_message(_msg("999", "Zed", "из shared", shared=True))
            # Колбэк теперь в фоновой задаче — ждём осушения очереди.
            for _ in range(500):
                if calls and bot._pending == 0:
                    break
                await asyncio.sleep(0.01)
            assert bot._pending == 0, "очередь не осушилась"

        asyncio.run(_run_cases())
        assert calls == [("Zed", "привет, Дюрандаль")], calls
        ok("twitch: колбэк 1 раз (кулдаун/своё/!/пустое/shared отсеяны)")

        _Cfg.TWITCH_BOT_ID = ""
        try:
            DurandalBot(_cb)
            fail("twitch: нет проверки ID", "сконструировался без ID")
        except RuntimeError:
            ok("twitch: без BOT_ID/CHANNEL_ID — понятный RuntimeError")
    finally:
        (_Cfg.TWITCH_BOT_ID, _Cfg.TWITCH_CHANNEL_ID,
         _Cfg.TWITCH_CLIENT_ID, _Cfg.TWITCH_CLIENT_SECRET) = _saved
except ImportError as e:
    skip("twitch v3", f"twitchio нет в этом интерпретаторе: {e}")
except Exception as e:
    fail("twitch v3", f"{type(e).__name__}: {e}")

print("== 9. Окружение / песочница ==")
venv_py = os.path.join(ROOT, "venv", "Scripts", "python.exe")
if os.path.exists(venv_py):
    import subprocess
    r = subprocess.run([venv_py, "--version"], capture_output=True, text=True)
    if r.returncode == 0:
        ok(f"venv: работает ({(r.stdout or r.stderr).strip()})")
    else:
        fail("venv", f"интерпретатор бит: {(r.stderr or '')[:120]} — пересоздай: python -m venv --clear venv")
else:
    skip("venv", "нет venv/Scripts/python.exe")

rvc_py = os.path.join(ROOT, "rvc_env", "Scripts", "python.exe")
if os.path.exists(rvc_py):
    import subprocess
    r = subprocess.run(
        [rvc_py, "-c", "import torch, fairseq; "
         "assert torch.cuda.is_available(); "
         "print(torch.__version__)"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode == 0:
        ok(f"rvc_env: torch+fairseq+CUDA ({r.stdout.strip()})")
    else:
        fail("rvc_env", f"сломан: {(r.stderr or '')[-200:]}")
else:
    skip("rvc_env", "нет — при USE_RVC=true будет чистый edge-tts / ошибка RVC")

w_dir = os.path.join(ROOT, "models", "rvc_webui", "assets", "weights")
if os.path.isdir(w_dir) and any(f.endswith(".pth") for f in os.listdir(w_dir)):
    ok(f"rvc weights: {[f for f in os.listdir(w_dir) if f.endswith('.pth') or f.endswith('.index')]}")
else:
    fail("rvc weights", "модель не найдена")

if os.path.exists(os.path.join(ROOT, ".env")):
    skip(".env", "существует (секреты не проверяю, см. отчёт)")
else:
    fail(".env", "нет — скопируй из .env.example")

print()
print(f"ИТОГ: PASS={len(PASS)} FAIL={len(FAIL)} SKIP={len(SKIP)}")
if FAIL:
    print("Неисправности:")
    for n, w in FAIL:
        print(f"  - {n}: {w}")
    sys.exit(1)
print("OK: базовая песочница зелёная.")
