"""Настройки сервиса. Всё переопределяется переменными окружения."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
JOBS_DIR = DATA_DIR / "jobs"
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
FRAME_FPS = float(os.getenv("FRAME_FPS", "2"))            # кадров/с для анализа
FRAME_MAX_SIDE = int(os.getenv("FRAME_MAX_SIDE", "640"))  # длинная сторона для модели
EVIDENCE_MAX_SIDE = int(os.getenv("EVIDENCE_MAX_SIDE", "1280"))
TIME_BUDGET_SEC = float(os.getenv("TIME_BUDGET_SEC", "270"))  # лимит жюри 300 с
MAX_VLM_CALLS = int(os.getenv("MAX_VLM_CALLS", "120"))
MERGE_GAP_SEC = float(os.getenv("MERGE_GAP_SEC", "3"))
MAX_EVENTS_PER_RULE = int(os.getenv("MAX_EVENTS_PER_RULE", "3"))

# --- модель -------------------------------------------------------------
# stub        : модель не вызывается (для отладки API и интерфейса)
# openai_local: локальный OpenAI-совместимый сервер (llama-server, vLLM, ...)
VLM_BACKEND = os.getenv("VLM_BACKEND", "stub")
VLM_BASE_URL = os.getenv("VLM_BASE_URL", "http://127.0.0.1:8080/v1")
VLM_MODEL = os.getenv("VLM_MODEL", "local")
VLM_TIMEOUT_SEC = float(os.getenv("VLM_TIMEOUT_SEC", "60"))

# Только для проверки интерфейса: заглушка выдаёт одно помеченное «ДЕМО» событие.
STUB_DEMO = os.getenv("STUB_DEMO", "0") == "1"
