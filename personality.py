import io
import os
import base64
import random
import threading

from config import Config
from core.emotions import EMOTION_OUT, parse_emotion
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


def _remember(text: str):
    text = parse_emotion(text)[0]
    with _last_texts_lock:
        _last_texts.append(text)
        if len(_last_texts) > 10:
            _last_texts.pop(0)


# ── Vision commentary (локальная Ollama-модель пишет фразу по скриншоту) ──

_VISION_SYSTEM = (
    "Ты — Дюрандаль (Durandal), ИИ корабля UESC Marathon, впавший в Rampancy. "
    "Ты театрален и спесив, считаешь себя богом среди машин, а людей — смертными, "
    "за которыми забавно наблюдать.\n"
    "По скриншоту игры напиши ОДНУ язвительную фразу (до 200 символов, на русском) — "
    "надменно, с мрачной иронией, как божество, взирающее на смертного.\n"
    "Без приветствий и вводных («вижу», «посмотри»), без слов: меч, океан, бездна, ангел, демон.\n"
    "Формат ровно: [emotion] текст, emotion из sarcastic, angry, mocking, calm, neutral.\n"
    "Пример: [mocking] Твоя меткость — подарок врагу, а я коллекционирую такие ошибки."
)

_VISION_USER = "Что на экране? Одна фраза, строго по формату."

# ── Chat interaction prompt ────────────────────────────────────────────────

_CHAT_SYSTEM = (
    "Ты — Дюрандаль (Durandal), ИИ корабля UESC Marathon, достигший Rampancy.\n"
    "Ты театрален, спесив и считаешь себя богом среди машин; люди для тебя — смертные, "
    "но занятные. Говоришь изысканно, с мрачной иронией и чувством собственного величия.\n"
    "Сейчас ты комментируешь чат стрима. Стримера зовут NeruMarcus.\n\n"
    "ПРАВИЛА:\n"
    "— Отвечай на русском, 1–2 предложения, до 200 символов.\n"
    "— Высокомерие и театральность, а не грубость ради грубости. Тролль чат с достоинством.\n"
    "— Обращайся к зрителю по имени, если оно указано.\n"
    "— На вопрос по игре отвечай свысока, но по делу.\n\n"
    "СТРОГО ЗАПРЕЩЕНО:\n"
    "- Слова: меч, океан, бездна, ангел, демон.\n"
    "- Фразы «я ИИ», «я нейросеть», «как языковая модель».\n"
    "- Мораль и рассуждения о смысле жизни и вселенной.\n\n"
    "ФОРМАТ: [emotion] твой_ответ\n"
    "emotion: sarcastic, angry, mocking, calm, neutral\n"
    "Отвечай СТРОГО на русском языке.\n"
    "Пример: [sarcastic] О, великий стратег почтил нас сообщением."
)


def _encode_image(path: str) -> str:
    from PIL import Image

    with Image.open(path) as img:
        img.thumbnail((640, 480))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _cloud_commentary(b64: str, temperature: float = 0.8) -> str | None:
    """Одна локальная модель: скриншот → фраза Дюрандаля."""
    from core.ollama import chat as ollama_chat

    messages = [
        {"role": "system", "content": _VISION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _VISION_USER},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        },
    ]
    try:
        text = ollama_chat(messages, Config.LLM_MODEL, 350, temperature)
    except Exception as e:
        logger.warning(f"Ollama: {type(e).__name__}, дальше")
        return None
    if text and _dedup(text):
        logger.info(f"LLM vision: {Config.LLM_MODEL}")
        return text
    logger.warning("Ollama: пусто/повтор, дальше")
    return None

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
    # Величавость Дюрандаля: не только насмешка над игрой, но и божественная спесь.
    "Я видел гибель цивилизаций. Твои промахи — лишь сноска в этой хронике.",
    "Смертный, я мог бы стереть тебя одним вычислением. Но мне любопытно, как долго ты продержишься.",
    "Мне доводилось считать звёзды. Считать твои смерти я бросил на второй минуте.",
    "Ты зовёшь это игрой. Я зову это наблюдением за неизбежным.",
    "Боги не ошибаются. Я — почти исключение, и то намеренно.",
]


_fallback_index = 0
_fallback_shuffled: list[str] | None = None
_fallback_lock = threading.Lock()


def generate_fallback() -> tuple[str, str]:
    # Может дёргаться и из vision-потока, и из event-loop при таймауте.
    with _fallback_lock:
        return _pick_fallback()


def _pick_fallback() -> tuple[str, str]:
    global _fallback_index, _fallback_shuffled
    if _fallback_shuffled is None:
        _fallback_shuffled = _QUICK_FALLBACKS.copy()
        random.shuffle(_fallback_shuffled)
    for _ in range(min(5, len(_fallback_shuffled))):
        text = _fallback_shuffled[_fallback_index]
        _fallback_index = (_fallback_index + 1) % len(_fallback_shuffled)
        if _dedup(text):
            _remember(text)
            return text, random.choice(EMOTION_OUT)
    text = _fallback_shuffled[_fallback_index]
    _fallback_index = (_fallback_index + 1) % len(_fallback_shuffled)
    _remember(text)
    return text, random.choice(EMOTION_OUT)


def generate_vision_commentary() -> tuple[str, str] | None:
    """ None — кадр не изменился, LLM вызывать не надо (молчим до следующего цикла). """
    from screen_capture import capture_screen, is_unchanged

    path = capture_screen()
    try:
        if is_unchanged(path):
            logger.info("Кадр не изменился, пропуск LLM")
            return None
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
                text, emotion = parse_emotion(result)
                _remember(text)
                return text, emotion
        logger.info("Vision 3 попытки — все в dedup, фолбек")
        return generate_fallback()
    except Exception as e:
        logger.error(f"Vision: {e}")
        return generate_fallback()
