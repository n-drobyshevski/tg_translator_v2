"""Буфер для медиагрупп (альбомов) Telegram.

Telegram доставляет альбом как N независимых апдейтов с общим
``media_group_id`` — сигнала «альбом закончился» в API нет. Если обрабатывать
каждый апдейт отдельно, один альбом из 4 фото превращается в 4 отдельных поста,
причём подпись альбома есть только у одного из них (а переводится она столько
раз, сколько в альбоме элементов).

Этот модуль копит части группы и вызывает callback один раз — после того как по
группе не приходило новых частей в течение ``debounce`` секунд.

Модуль намеренно свободен от Pyrogram-специфики (принимает любые объекты
сообщений), чтобы его можно было тестировать на простых заглушках — так же, как
``admin_commands.handle_command``.
"""

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("PYRO")

# Bot API limits for sendMediaGroup.
MEDIA_GROUP_MIN = 2
MEDIA_GROUP_MAX = 10

# Части альбома приходят подряд, поэтому короткой паузы достаточно, чтобы
# считать группу собранной. Переопределяется через env для медленных каналов.
DEFAULT_DEBOUNCE = 2.0


def debounce_seconds() -> float:
    """Пауза тишины, после которой группа считается собранной."""
    raw = os.getenv("MEDIA_GROUP_DEBOUNCE")
    if not raw:
        return DEFAULT_DEBOUNCE
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid MEDIA_GROUP_DEBOUNCE=%r; falling back to %ss", raw, DEFAULT_DEBOUNCE
        )
        return DEFAULT_DEBOUNCE
    return value if value > 0 else DEFAULT_DEBOUNCE


class MediaGroupBuffer:
    """Копит части одной медиагруппы и отдаёт их одним куском.

    ``flush`` — корутина, принимающая список сообщений группы, упорядоченный по
    ``message_id`` (апдейты могут прийти не по порядку, а порядок в альбоме
    значим). Исключения из ``flush`` логируются и не всплывают в хендлер: одна
    сбойная группа не должна ронять релей.
    """

    def __init__(
        self,
        flush: Callable[[List[Any]], Awaitable[None]],
        debounce: Optional[float] = None,
    ):
        self._flush = flush
        self._debounce = debounce
        self._groups: Dict[Tuple[Any, str], List[Any]] = {}
        self._timers: Dict[Tuple[Any, str], asyncio.Task] = {}
        self._lock = asyncio.Lock()

    @property
    def pending_groups(self) -> int:
        return len(self._groups)

    async def add(self, chat_id: Any, media_group_id: Any, message: Any) -> None:
        """Добавить часть группы и (пере)запустить таймер её сборки."""
        key = (chat_id, str(media_group_id))
        async with self._lock:
            self._groups.setdefault(key, []).append(message)
            # Каждая новая часть отодвигает флаш: таймер отсчитывает тишину
            # после последней части, а не время с начала группы.
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()
            self._timers[key] = asyncio.create_task(self._flush_after_quiet(key))

    async def _flush_after_quiet(self, key: Tuple[Any, str]) -> None:
        delay = self._debounce if self._debounce is not None else debounce_seconds()
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            # Пришла ещё одна часть — флашем займётся новый таймер.
            return
        async with self._lock:
            items = self._groups.pop(key, [])
            self._timers.pop(key, None)
        if not items:
            return
        # Апдейты могут прийти не по порядку; порядок в альбоме значим.
        items.sort(key=lambda m: getattr(m, "id", 0) or 0)
        try:
            await self._flush(items)
        except Exception:
            logger.exception(
                "Media group flush failed for chat %s group %s (%d item(s))",
                key[0],
                key[1],
                len(items),
            )

    async def close(self) -> None:
        """Отменить таймеры и забыть недособранные группы (для остановки бота)."""
        async with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
            self._groups.clear()
        for timer in timers:
            timer.cancel()


# --------------------------------------------------------------------------- #
# sendMediaGroup compatibility
# --------------------------------------------------------------------------- #

# Наши media_type (из get_media_info) → тип InputMedia в sendMediaGroup.
# sendMediaGroup принимает только эти четыре типа: анимации, голосовые и
# видеосообщения в альбом не кладутся вообще.
_INPUT_MEDIA_TYPES = {
    "photo": "photo",
    "live_photo": "live_photo",  # Bot API 10.0: allowed in albums with photo/video
    "video": "video",
    "doc": "document",
    "audio": "audio",
}

# Внутри одного альбома можно смешивать только фото с видео; документы и аудио
# группируются лишь с себе подобными.
_FAMILIES = {
    "photo": "visual",
    "live_photo": "visual",
    "video": "visual",
    "document": "document",
    "audio": "audio",
}


def input_media_type(media_type: str) -> Optional[str]:
    """Тип InputMedia для sendMediaGroup, либо None если тип в альбом нельзя."""
    return _INPUT_MEDIA_TYPES.get(media_type)


def can_send_as_album(media_types: List[str]) -> bool:
    """Можно ли отправить эти элементы одним sendMediaGroup.

    Проверяет три ограничения Bot API: размер 2..10, все типы допустимы в
    альбоме, и все — из одного семейства (фото+видео можно, документы и аудио
    только между собой). Если False, вызывающий код отправляет элементы по
    одному, как раньше.
    """
    if not (MEDIA_GROUP_MIN <= len(media_types) <= MEDIA_GROUP_MAX):
        return False
    families = set()
    for media_type in media_types:
        mapped = input_media_type(media_type)
        if mapped is None:
            return False
        families.add(_FAMILIES[mapped])
    return len(families) == 1
