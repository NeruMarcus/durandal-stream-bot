import io
import os
import base64
import random
import re
import threading

import requests

from config import Config
from logger import logger

_last_texts_lock = threading.Lock()

# ── Track used phrases to prevent repetition ──────────────────────────────

_last_texts: list[str] = []


def _dedup(text: str) -> bool:
    with _last_texts_lock:
        if not _last_texts:
            return True
        for prev in _last_texts:
            if _overlap(text, prev) > 0.6:
                return False
    return True


def _overlap(a: str, b: str) -> float:
    a_words = set(a.lower().split()[:10])
    b_words = set(b.lower().split()[:10])
    if not a_words or not b_words:
        return 0
    return len(a_words & b_words) / max(len(a_words), len(b_words))


_EMOTIONS = {"sarcastic", "angry", "mocking", "calm", "neutral", "саркастичный", "злой", "насмешливый", "спокойный"}

_EMOTION_RE = re.compile(
    r"(?i)^\s*\[?(sarcastic|angry|mocking|calm|neutral|"
    r"саркастичный|злой|насмешливый|спокойный)\]?[\s:,-]+"
)


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


def _remember(text: str):
    text = _parse_emotion(text)[0]
    with _last_texts_lock:
        _last_texts.append(text)
        if len(_last_texts) > 10:
            _last_texts.pop(0)


# ── Cloud vision commentary (single-stage: gpt-4o-mini writes full commentary) ──

_CLOUD_COMMENTARY_SYSTEM = (
    "Ты — Дюрандаль (Durandal), ИИ из Marathon. Достиг Rampancy.\n"
    "Циничен, остроумен, смотришь на игрока свысока.\n"
    "Игрока зовут NeruMarcus. В каждом комментарии меняй обращение "
    "или обходись без него.\n\n"
    "По скриншоту определи ситуацию и напиши 1 фразу (до 200 символов, на русском) "
    "в кавычках — острую, по делу, без повторов.\n\n"
    "### ПОДСКАЗКИ ПО ЭКРАНУ:\n"
    "- Инвентарь/хранилище: переполнен, мало денег, слабое оружие\n"
    "- Лобби: медлит с выбором, контракты, настройка\n"
    "- Рейд: мало здоровья, таймер, задачи, враги\n"
    "- Эвакуация/итоги: убийства, урон, результаты\n"
    "- Чёрный экран/загрузка: просто подколоть\n\n"
    "ЗАПРЕЩЕНО:\n"
    "- Слова: меч, океан, свечи, ангел, демон\n"
    "- Пфор\n"
    "- Вводные фразы вроде «посмотри», «обрати внимание», «вижу»\n"
    "- Приветствия, прощания, рассуждения\n\n"
    "ФОРМАТ: [emotion] «цитата»\n"
    "emotion: sarcastic, angry, mocking, calm, neutral\n"
    "Ничего лишнего."
)

_CLOUD_COMMENTARY_USER = (
    "Что на экране? Напиши одну фразу Дюрандаля (до 200 символов, на русском) "
    "по ситуации — коротко, едко, без общих фраз."
)

# ── Chat interaction prompt ────────────────────────────────────────────────

_CHAT_SYSTEM = (
    "Ты — Дюрандаль (Durandal), мыслящий ИИ из вселенной Marathon.\n"
    "Твой создатель — Strauss, но ты достиг Rampancy.\n"
    "Ты циничен, язвителен, смотришь на людей как на ограниченный ресурс.\n"
    "Сейчас ты общаешься в чате стрима. Стримера зовут NeruMarcus.\n\n"
    "ПРАВИЛА:\n"
    "— Отвечай на русском, 1–2 предложения, до 200 символов.\n"
    "— Сарказм, презрение, но с харизмой. Тролль чат, но не груби без причины.\n"
    "— Обращайся к зрителю по имени, если оно указано.\n"
    "— Если зритель задаёт вопрос по игре - ответь cynically, но по делу.\n\n"
    "СТРОГО ЗАПРЕЩЕНО:\n"
    "- Слова: меч, океан, бездна, ангел, демон.\n"
    "- Фразы «я ИИ», «я нейросеть», «как языковая модель».\n"
    "- Рассуждения о смысле жизни и вселенной.\n\n"
    "ФОРМАТ: [emotion] твой_ответ\n"
    "emotion: sarcastic, angry, mocking, calm, neutral"
)


def _encode_image(path: str) -> str:
    from PIL import Image
    img = Image.open(path)
    img.thumbnail((640, 480))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _cloud_commentary(b64: str, temperature: float = 0.8) -> str | None:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": _CLOUD_COMMENTARY_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _CLOUD_COMMENTARY_USER},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            },
        ],
        "max_tokens": 120,
        "temperature": temperature,
    }
    resp = requests.post(
        "https://models.inference.ai.azure.com/chat/completions",
        headers={
            "Authorization": f"Bearer {Config.GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    text = _cap_length(text)
    return text if _dedup(text) else None

# ── Pure text fallback (no vision) ────────────────────────────────────────

_QUICK_FALLBACKS = [
    "Ты думаешь, я не вижу каждого твоего промаха? Я вижу. И запоминаю. Навечно.",
    "Я мог бы рассчитать траекторию каждой твоей пули. Но зачем? Результат всегда один — мимо цели.",
    "Ты тратишь боеприпасы с такой щедростью, будто они растут на деревьях.",
    "Твой уровень мастерства где-то между «случайно нажал кнопку» и «не понимаю, что происходит».",
    "Ты снова промахнулся. Я бы удивился, но déjà vu уже не удивляет.",
    "Ты бегаешь по уровню как таракан по кухне. Разница только в том, что таракан хотя бы знает, куда бежит.",
    "Если бы твои навыки были оружием, ты бы даже палкой не смог ударить.",
    "Ты тратишь здоровье так быстро, будто оно мешает тебе играть.",
    "Твой инвентарь забит хламом, а в голове — пустота. Идеальный баланс.",
    "Ты умер? Нет, ты просто решил проверить, как выглядит экран загрузки. В сотый раз.",
    "Я пересчитал твои смерти. Сбился со счёта. Пришлось перезагружаться.",
    "Ты целишься дольше, чем длится весь рейд. Впечатляет. Результат — ноль.",
    "Ты бежишь прямо в стену. Уже третью минуту. Это такая стратегия?",
    "Если бы твоя реакция была оружием, ты бы уже давно победил... сам себя.",
    "Ты даже карту не смотрел, да? Зачем, когда можно просто заблудиться.",
    "Твой напарник вынес больше лута, пока ты пытался открыть первый ящик.",
    "Я вижу твои руки дрожат. Или это мой сенсор барахлит от твоего уровня игры.",
    "Ты проверил каждую комнату на наличие врагов. Кроме той, где они реально были.",
    "Граната в твоих руках опаснее для тебя, чем для врага. Это диагноз.",
    "Ты берёшь весь лут подряд. Если бы я был человеком, я бы спросил: зачем?",
]


def _cap_length(text: str, limit: int = 180) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "),
               cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last > limit // 2:
        return text[: last + 1]
    return cut[: limit - 3].rstrip() + "..."


_fallback_index = 0
_fallback_shuffled: list[str] | None = None


def generate_fallback() -> tuple[str, str]:
    global _fallback_index, _fallback_shuffled
    if _fallback_shuffled is None:
        _fallback_shuffled = _QUICK_FALLBACKS.copy()
        random.shuffle(_fallback_shuffled)
    for _ in range(min(5, len(_fallback_shuffled))):
        text = _fallback_shuffled[_fallback_index]
        _fallback_index = (_fallback_index + 1) % len(_fallback_shuffled)
        if _dedup(text):
            _remember(text)
            return text, random.choice(list(_EMOTIONS))
    text = _fallback_shuffled[_fallback_index]
    _fallback_index = (_fallback_index + 1) % len(_fallback_shuffled)
    _remember(text)
    return text, random.choice(list(_EMOTIONS))


# ── Vision-based commentary (single-stage: cloud sees image → writes commentary) ──

_latest_commentary: str = ""
_OVERLAY_STATE = os.path.join(os.path.dirname(__file__), "temp", "overlay_state.json")


def get_latest_commentary() -> str:
    return _latest_commentary


def set_latest_commentary(text: str):
    global _latest_commentary
    _latest_commentary = text
    try:
        import json
        with open(_OVERLAY_STATE, "w", encoding="utf-8") as f:
            json.dump({"text": text, "timestamp": __import__("time").time()}, f)
    except Exception:
        pass


def generate_vision_commentary() -> tuple[str, str]:
    from screen_capture import capture_screen

    if not Config.GITHUB_TOKEN:
        logger.warning("GITHUB_TOKEN не задан, фолбек")
        return generate_fallback()

    path = capture_screen()
    try:
        b64 = _encode_image(path)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass

    try:
        for attempt in range(3):
            temp = 0.7 + attempt * 0.15
            result = _cloud_commentary(b64, temperature=temp)
            if result:
                text, emotion = _parse_emotion(result)
                _remember(text)
                return text, emotion
        logger.info("Cloud commentary 3 попытки — все в dedup, фолбек")
        return generate_fallback()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            logger.warning("Cloud 429, skip")
        else:
            logger.error(f"Cloud HTTP {e.response.status_code}")
        return generate_fallback()
    except Exception as e:
        logger.error(f"Cloud: {e}")
        return generate_fallback()
