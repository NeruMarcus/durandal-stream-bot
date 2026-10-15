# Эмоции: LLM отдаёт теги и по-русски («сарказм», «гнев», «насмешка»).
# Приводим к английским — их знают CSS-бейдж overlay и парсеры.

import re

EMOTION_OUT = ("sarcastic", "angry", "mocking", "calm", "neutral")

_RU2EN = {
    "сарказм": "sarcastic",
    "саркастичный": "sarcastic",
    "саркастично": "sarcastic",
    "саркастическое": "sarcastic",
    "ирония": "sarcastic",
    "иронично": "sarcastic",
    "злой": "angry",
    "злая": "angry",
    "зло": "angry",
    "гнев": "angry",
    "гневный": "angry",
    "гневно": "angry",
    "агрессия": "angry",
    "раздражение": "angry",
    "раздражённый": "angry",
    "насмешливый": "mocking",
    "насмешка": "mocking",
    "насмешливо": "mocking",
    "издёвка": "mocking",
    "издевательский": "mocking",
    "презрение": "mocking",
    "презрительно": "mocking",
    "спокойный": "calm",
    "спокойно": "calm",
    "спокойствие": "calm",
    "ровный": "calm",
    "нейтральный": "neutral",
    "нейтрально": "neutral",
    "нейтр": "neutral",
    # Синонимы, которыми gemma3:4b любит помечать фразы по-русски.
    "иронический": "sarcastic",
    "сатира": "sarcastic",
    "сатиричный": "sarcastic",
    "сатирический": "sarcastic",
    "сатирично": "sarcastic",
    "пренебрежение": "mocking",
    "пренебрежительно": "mocking",
    "пренебрежительный": "mocking",
    "свысока": "mocking",
    "мрачно": "mocking",
    "мрачный": "mocking",
    "злобно": "angry",
    "злобный": "angry",
    "злой смех": "angry",
}

_TAG_RE = re.compile(r"^\s*\[([^\[\]]{1,30})\][\s:,-]*")
_TAG_INLINE_RE = re.compile(r"\[([^\[\]]{1,30})\]")


def _scrub_inline(m: re.Match) -> str:
    """Внутри текста режем только эмоция-теги, прочее ([2:1], [sic]) — оставляем."""
    tag = m.group(1).strip().lower()
    return "" if tag in _RU2EN or tag in EMOTION_OUT else m.group(0)


def sanitize(text: str) -> str:
    """Убирает режиссёрские ремарки (…) в начале и многословие локальных моделей."""
    text = re.sub(r"^\s*[（(][^)）]*[)）]\s*", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # Снимаем обрамляющие кавычки/ёлочки: оверлей сам оформляет реплику.
    _quotes = "«»\"'“”‘’`"
    while text and text[0] in _quotes:
        text = text[1:].lstrip()
    while text and text[-1] in _quotes:
        text = text[:-1].rstrip()
    if len(text) > 220:
        cut = text[:220]
        last = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        if last > 80:
            text = text[: last + 1]
        else:
            text = cut.rsplit(" ", 1)[0][:217].rstrip() + "..."  # ровно ≤220
    return text


def parse_emotion(text: str) -> tuple[str, str]:
    """(фраза без тега, английская эмоция из EMOTION_OUT).

    Ведущий [тег] снимается всегда (известный — в эмоцию, чужой — в neutral).
    Без скобок текст считается чистой фразой: «гнев: ...» больше не парсится.
    """
    m = _TAG_RE.match(text)
    if m:
        tag = m.group(1).strip().lower()
        emotion = _RU2EN.get(tag, tag if tag in EMOTION_OUT else "neutral")
        rest = text[m.end():]
    else:
        rest, emotion = text, "neutral"
    return sanitize(_TAG_INLINE_RE.sub(_scrub_inline, rest).strip()), emotion
