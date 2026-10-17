"""Единый интерфейс к модели: ask(кадр, вопрос) -> dict.

Смена модели не должна ломать остальной код: достаточно другого бэкенда.
Требование локальности (ТЗ, раздел 7): адрес модели обязан быть loopback или
частной сети, иначе сервис откажется отправлять кадры (защита от случайной
передачи кадров в облако, это основание для дисквалификации).
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from . import config

SYSTEM_PROMPT = (
    "Ты анализируешь один кадр камеры, снятой сверху над банковской кассой. "
    "Отвечай только тем, что действительно видно на кадре, без догадок. "
    "Не определяй личности и не распознавай лица. "
    "Если по кадру нельзя уверенно ответить, answer = \"unclear\". "
    "Ответ строго в JSON без пояснений: "
    "{\"answer\": \"yes|no|unclear\", \"what_is_visible\": \"одна короткая фраза о том, что видно\"}"
)

_JSON_RE = re.compile(r"\{.*?\}", re.S)


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


def parse_answer(text: str) -> dict:
    """Достаёт JSON из ответа модели; при любой проблеме возвращает unclear."""
    for match in _JSON_RE.finditer(text or ""):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        answer = str(data.get("answer", "")).strip().lower()
        if answer in {"да", "true"}:
            answer = "yes"
        elif answer in {"нет", "false"}:
            answer = "no"
        if answer not in {"yes", "no", "unclear"}:
            answer = "unclear"
        visible = str(data.get("what_is_visible", "")).strip()[:300]
        return {"answer": answer, "what_is_visible": visible}
    return {"answer": "unclear", "what_is_visible": ""}


class StubBackend:
    name = "stub"

    def ask(self, image_path: Path, question: str) -> dict:
        return {"answer": "unclear", "what_is_visible": "модель не подключена (stub)"}


class OpenAILocalBackend:
    """Любой локальный сервер с /v1/chat/completions и поддержкой image_url."""

    name = "openai_local"

    def __init__(self, base_url: str, model: str, timeout: float):
        assert_local_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def ask(self, image_path: Path, question: str) -> dict:
        import httpx  # импорт здесь, чтобы заглушка работала без httpx

        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 120,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": question},
                    ],
                },
            ],
        }
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # сеть, формат ответа, таймаут
            raise VLMError(f"Ошибка вызова модели: {exc}") from exc
        return parse_answer(text)


_backend = None


def get_backend():
    global _backend
    if _backend is None:
        if config.VLM_BACKEND == "stub":
            _backend = StubBackend()
        elif config.VLM_BACKEND == "openai_local":
            _backend = OpenAILocalBackend(config.VLM_BASE_URL, config.VLM_MODEL, config.VLM_TIMEOUT_SEC)
        else:
            raise VLMError(f"Неизвестный VLM_BACKEND: {config.VLM_BACKEND!r}")
    return _backend


def ask(image_path: Path, question: str) -> dict:
    """ask(кадр, вопрос) -> {"answer": "yes|no|unclear", "what_is_visible": str}"""
    return get_backend().ask(Path(image_path), question)
