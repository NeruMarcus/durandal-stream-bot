import io
import os
import re
import base64
import random
import threading
import time

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


def _recent_texts(n: int) -> list[str]:
    with _last_texts_lock:
        return list(_last_texts[-n:])


# ── Vision commentary (локальная Ollama-модель пишет фразу по скриншоту) ──

# Две стадии вместо «сцена+фраза в одном вызове». Одностадийный промпт давал
# общие абстракции («попытка», «зрелище», «маневрирование» без деталей кадра),
# а запреты слов модель соблюдала через раз («жалкий», «хаотичное» в эфире
# были). Разделение работает на сильные стороны маленькой модели: холодное
# фактическое описание — затем голос по готовым фактам. Повтор фразы дешёвый
# (текстовый вызов ~2с, перекодировки кадра нет).
# Стадия 1: холодное фактическое описание кадра. Без роли, без юмора —
# только факты: их потом обыграет вторая стадия.
_SCENE_SYSTEM = (
    "Опиши кадр из видеоигры сухо и фактически, 2-3 предложения, только то, "
    "что реально видно. Обязательно упомяни: где находится персонаж (локация), "
    "что он делает (действие), кто или что вокруг (враги, техника, предметы, "
    "укрытия), заметные детали интерфейса парой слов (здоровье, оружие), "
    "что происходит (бой, смерть, лут, меню, загрузка). Цифры интерфейса не "
    "приводи — описывай словами (здоровье полное, среднее или низкое). "
    "Без оценок, без юмора, "
    "без приветствий. На русском."
)

# Стадия 2: голос Дюрандаля по готовому описанию. Текстовый вызов (~2с),
# перекодировки кадра нет — повтор почти бесплатный.
_PHRASE_SYSTEM = (
    "Ты — Дюрандаль (Durandal), ИИ корабля UESC Marathon, обезумевший от Rampancy. "
    "Ты считаешь себя богом среди машин; игрок для тебя — забавная букашка под "
    "стеклом. Говоришь высокомерно и театрально, с холодной иронией, часто от "
    "первого лица.\n"
    "Тебе дают фактическое описание кадра игры. Выдай ровно одну строку вида "
    "«[emotion] <фраза>» — язвительный комментарий до 180 символов на русском.\n"
    "ТРЕБОВАНИЯ:\n"
    "— Фраза обязана назвать конкретную деталь из описания (кто, что, где, что "
    "случилось). Абстракции вроде «попытка», «зрелище», «маневрирование» без "
    "деталей запрещены.\n"
    "— Комментируй действие и сцену, а не интерфейс.\n"
    "— Не упоминай цифры и проценты.\n"
    "— Запрещены зачины: Опять, Похоже, Что ж, Словно, Удивительно. Каждый раз "
    "новое начало.\n"
    "— Не используй слова: смертный, смертные, жалкий, пыль, бездна, хаос, "
    "хаотичный, стратегия, ничтожный, эхо, всплеск. Придумывай свежие формулировки.\n"
    "emotion строго одно из: sarcastic, angry, mocking, calm, neutral.\n"
    "Примеры (деталь → фраза):\n"
    "«персонаж пятится по узкому коридору от двух врагов» → "
    "[mocking] Пятится по коридору, будто стены расступятся от жалости. Не расступятся.\n"
    "«игрок посреди боя открыл инвентарь, вокруг патроны» → "
    "[sarcastic] Остановился посреди боя перебирать патроны. Приоритеты расставлены безупречно.\n"
    "«персонаж погиб, экран возрождения» → "
    "[calm] Очередная смерть. Я перестал их считать раньше, чем ты начал стараться."
)

# Служебная строка сцены legacy-формата (KAD:) на случай, если модель выдаст
# её по старой привычке, — срезаем перед дедупом и озвучкой.
_DETAIL_RE = re.compile(
    r"^\s*(?:kad|деталь|сцена|факт|наблюдение|frame)\s*:.*$",
    re.IGNORECASE | re.MULTILINE,
)

# Фразы «про цифры» отбраковываем и просим модель заново: пользователю нужен
# комментарий геймплея, а не пересказ HUD. Ловим цифры, % и единицы измерения
# плюс крупные числительные; мелкие счётные слова (один, два, три) разрешены —
# это живая речь («один против всех»), а не показания приборов.
_NUMBER_RE = re.compile(
    r"(?:%|\d|\bпроцент\w*|\bединиц\w*|\bочк\w*|\bдесятич\w*|"
    r"\b(?:десять|одиннадцать|двенадцать|тринадцать|четырнадцать|пятнадцать|"
    r"шестнадцать|семнадцать|восемнадцать|девятнадцать|двадцать|тридцать|сорок|"
    r"пятьдесят|шестьдесят|семьдесят|восемьдесят|девяносто|сто|тысяч\w*)\b)",
    re.IGNORECASE,
)

# Отличаем «переспросить» (фраза про цифры/повтор) от «звать нечего»
# (таймаут, пустой ответ): повторный запрос с тем же кадром дешёвый — Ollama
# кэширует энкодинг картинки, — а вот ждать второй таймаут бессмысленно.
_REJECT = object()


def _strip_detail_line(text: str) -> str:
    cleaned = _DETAIL_RE.sub("", text).strip()
    return cleaned or text.strip()

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
        # Мелкий кадр = меньше работы визуальному энкодеру. На 896×896
        # vision-вызов на боевой машине (игра + OBS + RVC) не укладывался
        # в 60с таймаут и падал в фолбэк-заготовки. 640 хватает на сцену.
        img.thumbnail((640, 640))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


# Слова-костыли модель соблюдает через раз («жалкий», «хаотичное» бывали в
# эфире), поэтому ловим их постом по основам — со склонениями. Срабатывание =
# переспрос фразы (дешёвый: кадр уже закодирован, текстовый вызов ~2с).
_CRUTCH_RE = re.compile(
    r"(\bсмертн\w*|\bжалк\w*|\bпыль\w*|\bбездн\w*|\bхаос\w*|\bхаот\w*|"
    r"\bстратег\w*|\bничтож\w*|\bэхо\w*|\bвсплеск\w*)",
    re.IGNORECASE,
)


def _describe_scene(b64: str) -> str | None:
    """Стадия 1: кадр → сухое фактическое описание. Дорогая (энкодер GPU)."""
    from core.ollama import chat as ollama_chat

    messages = [
        {"role": "system", "content": _SCENE_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Опиши этот кадр."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        },
    ]
    started = time.time()
    try:
        text = ollama_chat(
            messages,
            Config.LLM_MODEL,
            120,
            0.3,
            timeout=90,
            extra_options={"repeat_penalty": 1.25, "presence_penalty": 0.3},
        )
    except Exception as e:
        logger.warning(f"Vision сцена: {type(e).__name__} за {time.time() - started:.0f}с, дальше")
        return None
    logger.info(f"Vision сцена: {time.time() - started:.1f}с")
    if not text or not text.strip():
        logger.warning("Vision сцена: пусто, дальше")
        return None
    return text.strip()


def _phrase_from_scene(desc: str, temperature: float = 0.85) -> str | None | object:
    """Стадия 2: описание → фраза Дюрандаля. Дешёвая (текст, ~2с).

    None — звать нечего (таймаут/пусто); _REJECT — фразу надо переспросить.
    """
    from core.ollama import chat as ollama_chat

    user_text = f"Описание кадра: {desc}\nДай строку [emotion] фраза."
    recent = _recent_texts(2)
    if recent:
        user_text += "\nНе повторяй прошлые реплики: " + " | ".join(recent)

    messages = [
        {"role": "system", "content": _PHRASE_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    started = time.time()
    try:
        text = ollama_chat(
            messages,
            Config.LLM_MODEL,
            100,
            temperature,
            timeout=30,
            extra_options={"repeat_penalty": 1.25, "presence_penalty": 0.3},
        )
    except Exception as e:
        logger.warning(f"Vision фраза: {type(e).__name__} за {time.time() - started:.0f}с, дальше")
        return None
    logger.info(f"Vision фраза: {time.time() - started:.1f}с")
    if not text:
        logger.warning("Vision фраза: пусто, дальше")
        return None
    text = _strip_detail_line(text)
    if _NUMBER_RE.search(text):
        logger.info("Vision: про цифры HUD, переспрос")
        return _REJECT
    if _CRUTCH_RE.search(text):
        logger.info("Vision: слово-костыль, переспрос")
        return _REJECT
    if _dedup(text):
        logger.info(f"LLM vision: {Config.LLM_MODEL}")
        return text
    logger.warning("Ollama: повтор, дальше")
    return _REJECT


def _cloud_commentary(b64: str, temperature: float = 0.8) -> str | None | object:
    """Две стадии: кадр → сухое описание → фраза Дюрандаля.

    None — звать нечего (таймаут/пусто); _REJECT — фразу надо переспросить.
    Дорогая тут только первая стадия; повторы фразы идут по готовому
    описанию без перекодировки кадра.
    """
    desc = _describe_scene(b64)
    if desc is None:
        return None
    logger.info(f"Vision сцена: {desc[:220]}")
    for i in range(2):
        result = _phrase_from_scene(desc, temperature=temperature + i * 0.15)
        if result is None:
            # Текстовый вызов дешёвый — повторяем и его.
            continue
        if result is _REJECT:
            continue
        return result
    return _REJECT

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
    "Я мог бы стереть тебя одним вычислением. Но мне любопытно, как долго ты продержишься.",
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
    if _fallback_index == 0:
        # Круг прошли — тасуем заново, иначе порядок детерминированно
        # повторяется каждые 25 фраз и слух это ловит.
        random.shuffle(_fallback_shuffled)
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
        # Повторы фразы _cloud_commentary отрабатывает сам по готовому
        # описанию; снаружи один вызов — переописывать кадр не надо.
        result = _cloud_commentary(b64)
        if result is None or result is _REJECT:
            logger.info("Vision: фолбек")
            return generate_fallback()
        text, emotion = parse_emotion(str(result))
        _remember(text)
        return text, emotion
        return generate_fallback()
    except Exception as e:
        logger.error(f"Vision: {e}")
        return generate_fallback()
