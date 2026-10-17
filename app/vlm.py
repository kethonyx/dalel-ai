"""Единый интерфейс к модели.

  ask(jpeg, question) -> {"answer": "yes|no|unclear", "reason": str}
  ground(jpeg, labels) -> [{"label": str, "box": (x1, y1, x2, y2)}]   # доли 0..1

Смена модели не должна ломать остальной код: достаточно другого бэкенда.
Требование локальности (ТЗ, раздел 7): адрес модели обязан быть loopback или
частной сети, иначе сервис откажется отправлять кадры (защита от случайной
передачи кадров в облако, это основание для дисквалификации).
"""
from __future__ import annotations

import base64
import ipaddress
import re
import socket
from urllib.parse import urlparse

from . import config

SYSTEM_PROMPT = (
    "You look at a frame from an overhead CCTV camera in a bank cashier room. "
    "Answer only from what is clearly visible, never guess. Do not identify people."
)
# Одно слово в ответе: следующий вопрос к тому же кадру берёт картинку из кэша llama-server
# и стоит ~0.3 с; пояснение добавляло бы ~1 с на каждый вопрос.
YES_NO_SUFFIX = " Answer with one word: yes or no."

# Qwen2.5-VL отдаёт пиксели входного изображения, Qwen3-VL — шкалу 0..1000.
BOX_SCALE = config.VLM_BOX_SCALE



class VLMError(RuntimeError):
    pass


def assert_local_url(url: str) -> None:
    host = urlparse(url).hostname
    if not host:
        raise VLMError(f"Некорректный VLM_BASE_URL: {url!r}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise VLMError(f"Не удалось разрешить адрес модели {host!r}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            raise VLMError(
                f"Адрес модели {host} ({ip}) не локальный. "
                "Кадры нельзя отправлять за пределы контура (ТЗ, раздел 7)."
            )


def parse_yes_no(text: str) -> dict:
    """Первое слово ответа -> yes/no/unclear, остальное -> причина."""
    text = (text or "").strip()
    m = re.match(r"\W*(yes|no|да|нет)\b[\s,.:;!-]*(.*)", text, re.I | re.S)
    if not m:
        return {"answer": "unclear", "reason": text[:200]}
    word = m.group(1).lower()
    answer = "yes" if word in {"yes", "да"} else "no"
    return {"answer": answer, "reason": m.group(2).strip()[:200]}


_BOX_RE = re.compile(r'"bbox_2d"\s*:\s*\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]')
_LABEL_RE = re.compile(r'"label"\s*:\s*"([^"]*)"')


def parse_boxes(text: str, width: int, height: int) -> list[dict]:
    """Рамки из ответа модели. Регулярками, а не json.loads: ответ бывает обрезан или
    с повторами, а первые рамки в нём при этом верные."""
    text = text or ""
    items = []
    for m in _BOX_RE.finditer(text):
        lab = None
        for lm in _LABEL_RE.finditer(text, 0, m.start()):
            lab = lm.group(1)
        items.append((lab or "", [float(v) for v in m.groups()]))
    out = []
    for label, (x1, y1, x2, y2) in items:
        sx, sy = (BOX_SCALE, BOX_SCALE) if BOX_SCALE else (width, height)
        box = (max(0.0, x1 / sx), max(0.0, y1 / sy), min(1.0, x2 / sx), min(1.0, y2 / sy))
        if box[2] > box[0] and box[3] > box[1]:
            out.append({"label": label, "box": box})
    return out


class StubBackend:
    name = "stub"
    model_id = "stub"

    def ask(self, jpeg: bytes, question: str) -> dict:
        return {"answer": "unclear", "reason": "модель не подключена (stub)"}

    def ground(self, jpeg: bytes, labels: list[str], width: int, height: int) -> list[dict]:
        return []


class OpenAILocalBackend:
    """Любой локальный сервер с /v1/chat/completions и поддержкой image_url."""

    name = "openai_local"

    def __init__(self, base_url: str, model: str, timeout: float, api_key: str = ""):
        assert_local_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._model_id: str | None = None

    @property
    def model_id(self) -> str:
        """Имя реально загруженной модели (для ключа кэша): 4B на Mac и 30B на GPU-компьютере
        слушают один и тот же 127.0.0.1:8080, их ответы смешивать нельзя."""
        if self._model_id is None:
            import httpx

            try:
                resp = httpx.get(f"{self.base_url}/models", headers=self.headers, timeout=10)
                resp.raise_for_status()
                self._model_id = resp.json()["data"][0]["id"]
            except Exception as exc:
                raise VLMError(f"Сервер модели недоступен: {exc}") from exc
        return self._model_id

    def _chat(self, jpeg: bytes, text: str, max_tokens: int) -> str:
        import httpx  # импорт здесь, чтобы заглушка работала без httpx

        b64 = base64.b64encode(jpeg).decode()
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": text},
                ]},
            ],
        }
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=self.headers,
                              timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # сеть, формат ответа, таймаут
            raise VLMError(f"Ошибка вызова модели: {exc}") from exc

    def ask(self, jpeg: bytes, question: str) -> dict:
        return parse_yes_no(self._chat(jpeg, question + YES_NO_SUFFIX, 4))

    def ground(self, jpeg: bytes, labels: list[str], width: int, height: int) -> list[dict]:
        # По одному объекту за запрос: длинный JSON-список квантованная 30B зацикливает
        # (повторяет "bbox_2d" до лимита токенов), короткий ответ из 4 чисел надёжен.
        out = []
        for label in labels:
            text = (f'Locate the {label} in the image. Output only JSON {{"bbox_2d": [x1, y1, x2, y2]}}, '
                    'or {"bbox_2d": []} if it is not visible.')
            out += [dict(b, label=label) for b in parse_boxes(self._chat(jpeg, text, 40), width, height)[:1]]
        return out


_backend = None


def get_backend():
    global _backend
    if _backend is None:
        if config.VLM_BACKEND == "stub":
            _backend = StubBackend()
        elif config.VLM_BACKEND == "openai_local":
            _backend = OpenAILocalBackend(config.VLM_BASE_URL, config.VLM_MODEL, config.VLM_TIMEOUT_SEC,
                                          config.VLM_API_KEY)
        else:
            raise VLMError(f"Неизвестный VLM_BACKEND: {config.VLM_BACKEND!r}")
    return _backend


def model_id() -> str:
    return get_backend().model_id


def ask(jpeg: bytes, question: str) -> dict:
    return get_backend().ask(jpeg, question)


def ground(jpeg: bytes, labels: list[str], width: int, height: int) -> list[dict]:
    return get_backend().ground(jpeg, labels, width, height)
