import json
import os
import logging

logger = logging.getLogger(__name__)
HISTORY_FILE = "published_matches.json"


def load_history() -> dict:
    """Загружает историю опубликованных матчей из JSON."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка чтения истории: {e}")
        return {}


def save_to_history(match_title: str, platform: str):
    """
    Отмечает в JSON, что матч был опубликован.
    platform может быть 'rutube' или 'vk'.
    """
    history = load_history()

    if match_title not in history:
        history[match_title] = {}

    history[match_title][platform] = True

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения истории: {e}")


def is_match_published(match_title: str) -> bool:
    """Проверяет, публиковался ли уже этот матч на Rutube."""
    history = load_history()
    # Пока проверяем только Rutube, потом добавим VK
    return history.get(match_title, {}).get("rutube", False)