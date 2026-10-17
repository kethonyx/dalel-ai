"""Настройки сервиса. Всё переопределяется переменными окружения."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
VIDEOS_DIR = DATA_DIR / "videos"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://dalel:dalel_dev_password@127.0.0.1:5433/dalel")
RULES_PATH = Path(os.getenv("RULES_PATH", BASE_DIR / "rules.json"))

# --- доступ -------------------------------------------------------------
# Ключ для жюри (заголовок X-API-Key). Если не задан, генерируется при старте
# и печатается в лог: для сдачи задайте его явно через API_KEY.
_env_key = os.getenv("API_KEY")
API_KEY = _env_key or secrets.token_urlsafe(24)
API_KEY_GENERATED = _env_key is None

# Веб-интерфейс работает без ключа (удобно для демо). UI_OPEN=0 выключает.
UI_OPEN = os.getenv("UI_OPEN", "1") == "1"

# --- загрузка -----------------------------------------------------------
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
ALLOWED_EXT = {".mov", ".mp4", ".m4v"}  # по ТЗ нужен .mov, остальное про запас

# --- пайплайн -----------------------------------------------------------
FRAME_FPS = float(os.getenv("FRAME_FPS", "1"))            # кадров/с для анализа (максимум)
# Потолок кадров на видео: длинные видео прореживаются. 32 кадра × ~7 с (кадр с посетителем:
# кроп зоны + кроп стола, M1 Pro / Qwen3-VL-8B) + поиск зоны ≈ 240 с — в бюджет 270 с.
MAX_FRAMES = int(os.getenv("MAX_FRAMES", "32"))
# Длинная сторона изображения для модели. Новая картинка стоит ~1.2 с (448) / ~2 с (640) на M1,
# поэтому рабочая зона (мелкие предметы) крупнее, а полный кадр (люди) мельче.
FRAME_MAX_SIDE = int(os.getenv("FRAME_MAX_SIDE", "640"))
FULL_MAX_SIDE = int(os.getenv("FULL_MAX_SIDE", "448"))
EVIDENCE_MAX_SIDE = int(os.getenv("EVIDENCE_MAX_SIDE", "1280"))
TIME_BUDGET_SEC = float(os.getenv("TIME_BUDGET_SEC", "270"))  # лимит жюри 300 с
MERGE_GAP_SEC = float(os.getenv("MERGE_GAP_SEC", "3"))
MAX_EVENTS_PER_RULE = int(os.getenv("MAX_EVENTS_PER_RULE", "3"))
VLM_PARALLEL = int(os.getenv("VLM_PARALLEL", "1"))        # одновременных запросов; на M1 параллель почти не ускоряет
# Кэш ответов модели (ключ: хеш кропа + вопрос). Ускоряет повторные прогоны и подбор правил.
CACHE_DIR = Path(os.getenv("CACHE_DIR", DATA_DIR / "cache"))

# --- модель -------------------------------------------------------------
# stub        : модель не вызывается (для отладки API и интерфейса)
# openai_local: локальный OpenAI-совместимый сервер (llama-server, vLLM, ...)
VLM_BACKEND = os.getenv("VLM_BACKEND", "stub")
VLM_BASE_URL = os.getenv("VLM_BASE_URL", "http://127.0.0.1:8080/v1")
VLM_MODEL = os.getenv("VLM_MODEL", "local")
VLM_TIMEOUT_SEC = float(os.getenv("VLM_TIMEOUT_SEC", "60"))
# Ключ сервера модели (llama-server --api-key-file). Нужен, когда модель на отдельном GPU-компьютере.
VLM_API_KEY = os.getenv("VLM_API_KEY", "")
# Шкала координат рамок в ответе модели: 1000 для Qwen3-VL, 0 = пиксели входного кадра (Qwen2.5-VL).
VLM_BOX_SCALE = float(os.getenv("VLM_BOX_SCALE", "1000"))

# Только для проверки интерфейса: заглушка выдаёт одно помеченное «ДЕМО» событие.
STUB_DEMO = os.getenv("STUB_DEMO", "0") == "1"
