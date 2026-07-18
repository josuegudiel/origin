"""Fallback de intent vía LLM local (Ollama).

Cuando ningún comando del perfil supera `fuzz_threshold` pero la transcripción
no está vacía y el mejor score ≥ `llm.floor_score`, mandamos la transcripción +
catálogo del perfil activo a un LLM local que devuelve qué comandos ejecutar.

El cliente es un wrapper liviano sobre `httpx`, portado del patrón TS de
`src/agents/predictive/ollama-client.ts`. Sin reintentos: si Ollama está caído
o lento, devolvemos `IntentResolution(confidence="low")` y el flujo sigue.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

from .config import LlmSettings, Profile

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Cualquier error de comunicación o respuesta inválida de Ollama."""


class IntentResolution(BaseModel):
    commands: list[str] = Field(default_factory=list)
    confidence: str = "low"        # "high" | "medium" | "low"
    reasoning: str = ""


# SEGURIDAD (DoS): un Ollama comprometido/MITM podría devolver un body enorme
# y agotar memoria en `r.json()`. Cortamos en 8 MB — una respuesta de intent
# legítima son cientos de bytes.
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def _is_loopback_base_url(base_url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "")


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_ms: int) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._timeout = max(0.5, timeout_ms / 1000.0)

    @staticmethod
    def _guard_size(r: httpx.Response) -> None:
        if len(r.content) > _MAX_RESPONSE_BYTES:
            raise OllamaError(f"ollama_response_too_large: {len(r.content)} bytes")

    def chat_json(self, system: str, user: str, *, temperature: float = 0.2) -> dict[str, Any]:
        body = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            r = httpx.post(f"{self._base}/api/chat", json=body, timeout=self._timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise OllamaError(f"ollama_http_error: {e}") from e
        self._guard_size(r)
        try:
            content = r.json()["message"]["content"]
            return json.loads(content)
        except (KeyError, json.JSONDecodeError, ValueError) as e:
            raise OllamaError(f"ollama_bad_json: {e}") from e

    def preflight(self) -> str | None:
        """None si OK; mensaje legible si no. Verifica conexión + modelo pulled."""
        # SEGURIDAD: la transcripción del micrófono viaja al servidor LLM. Si el
        # host no es loopback, avisar — un perfil compartido puede haber apuntado
        # base_url a un host que exfiltra el audio transcrito.
        if not _is_loopback_base_url(self._base):
            logger.warning(
                "llm_base_url_not_loopback host=%s — las transcripciones de voz "
                "salen a un host remoto",
                self._base,
            )
        try:
            r = httpx.get(f"{self._base}/api/tags", timeout=5.0)
            r.raise_for_status()
        except httpx.HTTPError as e:
            return f"no_conn: {e}"
        try:
            models = [m["name"] for m in r.json().get("models", [])]
        except Exception as e:
            return f"bad_response: {e}"
        wanted = self._model
        if not any(m == wanted or m.startswith(f"{wanted}:") for m in models):
            return f"model_not_pulled: corré `ollama pull {wanted}`"
        return None


class LLMIntentResolver:
    def __init__(self, client: OllamaClient, settings: LlmSettings) -> None:
        self._client = client
        self._cfg = settings

    def resolve(self, transcription: str, profile: Profile, lang: str) -> IntentResolution:
        text = transcription.strip()
        if not text:
            return IntentResolution(confidence="low", reasoning="empty_input")
        catalog = self._build_catalog(profile, lang)
        system = self._prompt_system(catalog, lang)
        try:
            raw = self._client.chat_json(system, text, temperature=self._cfg.temperature)
        except OllamaError as e:
            logger.warning("llm_resolve_failed err=%s", e)
            return IntentResolution(confidence="low", reasoning=f"error:{e}")
        try:
            res = IntentResolution.model_validate(raw)
        except Exception:
            return IntentResolution(confidence="low", reasoning="bad_schema")
        valid_ids = {c.id for c in profile.commands}
        res.commands = [c for c in res.commands if c in valid_ids][
            : self._cfg.max_commands_per_resolution
        ]
        return res

    # ---------------------------------------------------------------- prompt

    @staticmethod
    def _build_catalog(profile: Profile, lang: str) -> str:
        lines: list[str] = []
        for c in profile.commands:
            label = c.label_for(lang)
            phrases = c.phrases_for(lang)[:3]
            phrases_str = ", ".join(f'"{p}"' for p in phrases) if phrases else "—"
            lines.append(f"- {c.id} — {label} — {phrases_str}")
        return "\n".join(lines)

    @staticmethod
    def _prompt_system(catalog: str, lang: str) -> str:
        lang_hint = "Spanish" if lang == "es" else "English"
        return f"""You are Origin's intent resolver for the game Star Citizen. The user speaks a phrase in {lang_hint}; you map it to one OR more commands from the active profile catalog.

CATALOG (id — label — example phrases):
{catalog}

Reply with JSON only matching this schema:
{{
  "commands": [<list of command IDs in execution order, max 5>],
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one short sentence in {lang_hint}>"
}}

Rules:
- If no command applies, return {{"commands": [], "confidence": "low", "reasoning": "..."}}.
- "high" only if the user phrase clearly matches one or more catalog entries.
- Respect execution order: "prepare to leave for Crusader" = [target_crusader, quantum_mode, engage_quantum].
- Never invent command IDs. Use only IDs from CATALOG.
"""
