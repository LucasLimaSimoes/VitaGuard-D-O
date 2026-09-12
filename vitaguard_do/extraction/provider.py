from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from vitaguard_do.extraction.gemini_schema import gemini_json_schema


T = TypeVar("T", bound=BaseModel)


class StructuredLLMProvider(Protocol):
    provider_name: str
    model: str

    def generate_structured(self, prompt: str, schema: type[T]) -> T:
        ...


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".casefold()


def _is_transient_error(exc: Exception) -> bool:
    text = _error_text(exc)
    transient_tokens = (
        "503",
        "unavailable",
        "high demand",
        "temporarily overloaded",
        "temporary overload",
        "429",
        "resource_exhausted",
        "resource exhausted",
        "rate limit",
        "too many requests",
        "quota exceeded",
        "exceeded your current quota",
        "please retry in",
        "502",
        "504",
        "deadline exceeded",
        "timeout",
        "timed out",
        "connection reset",
    )
    return any(token in text for token in transient_tokens)


def _is_fatal_configuration_error(exc: Exception) -> bool:
    text = _error_text(exc)
    fatal_tokens = (
        "api key not valid",
        "invalid api key",
        "unauthenticated",
        "unauthorized",
        "permission denied",
        "billing is not enabled",
        "billing not enabled",
        "billing account is disabled",
        "project is not linked to a billing account",
    )
    return any(token in text for token in fatal_tokens)


def _is_model_not_found(exc: Exception) -> bool:
    text = _error_text(exc)
    return (
        "404" in text
        or "not_found" in text
        or "not found" in text
        or "no longer available" in text
    )


def _is_bad_request(exc: Exception) -> bool:
    text = _error_text(exc)
    return "400" in text or "invalid_argument" in text or "invalid argument" in text


def _is_model_output_error(exc: Exception) -> bool:
    if isinstance(exc, (ValidationError, json.JSONDecodeError)):
        return True
    text = _error_text(exc)
    tokens = (
        "invalid json",
        "json_invalid",
        "eof while parsing",
        "unterminated string",
        "no text in response",
        "returned no text",
    )
    return any(token in text for token in tokens)


def _retry_after_seconds(exc: Exception) -> float | None:
    text = str(exc)
    patterns = (
        r"Please retry in\s+([0-9]+(?:\.[0-9]+)?)s",
        r"retry in\s+([0-9]+(?:\.[0-9]+)?)s",
        r"retry after\s+([0-9]+(?:\.[0-9]+)?)\s*s",
        r"retryDelay[^0-9]*([0-9]+(?:\.[0-9]+)?)s",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def _clean_json_text(text: str) -> str:
    """Extract a JSON document from a Gemini response without repairing it."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    if text.startswith("{") or text.startswith("["):
        return text

    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(text[idx:])
            return text[idx : idx + end]
        except json.JSONDecodeError:
            continue
    return text


def _compact_schema_contract(schema: type[BaseModel]) -> str:
    """Compact Pydantic-derived JSON schema used in the prompt only."""
    safe = gemini_json_schema(schema)
    return json.dumps(safe, ensure_ascii=False, separators=(",", ":"))


def _validation_feedback(exc: Exception) -> str:
    if not isinstance(exc, ValidationError):
        return "A resposta anterior nao era JSON valido/completo."

    parts: list[str] = []
    for item in exc.errors()[:12]:
        loc = ".".join(str(x) for x in item.get("loc", ())) or "<root>"
        msg = item.get("msg", "erro de validacao")
        parts.append(f"- {loc}: {msg}")
    return "Erros de validacao da resposta anterior:\n" + "\n".join(parts)


class GeminiProvider:
    """GenerateContent provider with strict *local* Pydantic validation.

    v0.4.8 does not send the complex extraction model as server-side
    ``response_schema``. Instead, it includes a compact JSON schema in the
    prompt, requests JSON MIME when supported, then validates with Pydantic.
    If JSON MIME itself is rejected, it retries the same model in plain text
    mode while preserving the exact same local validation contract.
    """

    provider_name = "google-gemini"
    api_mode = "GenerateContent JSON mode + local Pydantic validation"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        fallback_models: list[str] | tuple[str, ...] | None = None,
        max_retries_per_model: int = 2,
        base_delay_seconds: float = 2.0,
        min_request_interval_seconds: float | None = None,
        max_output_tokens: int | None = None,
    ):
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not found. Set it in the environment or pass api_key=."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "google-genai is not installed. Run: pip install -r requirements.txt"
            ) from exc

        self._types = types
        self.requested_model = model or os.getenv(
            "VITAGUARD_GEMINI_MODEL", "gemini-3.5-flash-lite"
        )
        self.model = self.requested_model

        if fallback_models is None:
            raw_fallbacks = os.getenv(
                "VITAGUARD_GEMINI_FALLBACKS", "gemini-3.1-flash-lite"
            )
            fallback_models = [
                item.strip() for item in raw_fallbacks.split(",") if item.strip()
            ]

        seen: set[str] = {self.requested_model}
        self.fallback_models: list[str] = []
        for item in fallback_models:
            if item not in seen:
                self.fallback_models.append(item)
                seen.add(item)

        self.max_retries_per_model = max(1, int(max_retries_per_model))
        self.base_delay_seconds = max(0.0, float(base_delay_seconds))

        if min_request_interval_seconds is None:
            min_request_interval_seconds = float(
                os.getenv("VITAGUARD_GEMINI_MIN_INTERVAL_SECONDS", "7")
            )
        self.min_request_interval_seconds = max(0.0, float(min_request_interval_seconds))

        if max_output_tokens is None:
            max_output_tokens = int(
                os.getenv("VITAGUARD_GEMINI_MAX_OUTPUT_TOKENS", "8192")
            )
        self.max_output_tokens = max(1024, int(max_output_tokens))

        self.models_used: list[str] = []
        self.last_attempt_log: list[str] = []
        self.last_raw_output: str | None = None
        self.last_raw_output_model: str | None = None
        self.last_generation_mode: str | None = None
        self._last_request_started_at: float | None = None

        self._client = genai.Client(api_key=api_key)

    @property
    def model_summary(self) -> str:
        if not self.models_used:
            return self.model
        ordered = list(dict.fromkeys(self.models_used))
        return " + ".join(ordered)

    def _candidate_models(self) -> list[str]:
        ordered = [self.model, self.requested_model, *self.fallback_models]
        return list(dict.fromkeys(ordered))

    def _respect_min_request_interval(self) -> None:
        if self._last_request_started_at is None:
            return
        elapsed = time.monotonic() - self._last_request_started_at
        remaining = self.min_request_interval_seconds - elapsed
        if remaining > 0:
            print(
                f"[Gemini] Aguardando {remaining:.1f}s para respeitar o intervalo entre chamadas...",
                flush=True,
            )
            time.sleep(remaining)

    def _request(self, *, model: str, prompt: str, mode: str):
        self._respect_min_request_interval()
        self._last_request_started_at = time.monotonic()

        if mode == "json_mime":
            config = self._types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=self.max_output_tokens,
            )
        elif mode == "plain":
            config = self._types.GenerateContentConfig(
                max_output_tokens=self.max_output_tokens,
            )
        else:
            raise ValueError(f"Unknown generation mode: {mode}")

        return self._client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

    def _request_multimodal_text(
        self,
        *,
        model: str,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
    ):
        self._respect_min_request_interval()
        self._last_request_started_at = time.monotonic()
        config = self._types.GenerateContentConfig(
            max_output_tokens=self.max_output_tokens,
            temperature=0,
        )
        part = self._types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        return self._client.models.generate_content(
            model=model,
            contents=[prompt, part],
            config=config,
        )

    def transcribe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        source_name: str = "",
        page_number: int | None = None,
    ) -> str:
        """Transcreve uma página/imagem sem interpretar o conteúdo contratual.

        A saída serve apenas como texto de entrada para o pipeline estruturado.
        O Gemini não decide comparação nem equivalência nesta etapa.
        """
        if not image_bytes:
            raise ValueError("Imagem vazia para leitura multimodal.")
        if not mime_type.startswith("image/"):
            raise ValueError(f"MIME multimodal inválido: {mime_type}")

        label = source_name or "documento"
        if page_number is not None:
            label += f" · página {page_number}"
        prompt = (
            "Você é um transcritor documental. Leia a imagem de uma página de apólice/condição "
            "de seguro e devolva SOMENTE o texto visível, preservando títulos, itens, números, "
            "valores, datas e quebras de linha úteis. Não resuma, não explique, não traduza, "
            "não complete trechos ausentes e não invente conteúdo. Se algo estiver ilegível, "
            "use [ilegível]. Não use cercas Markdown. Fonte: " + label
        )

        attempt_log: list[str] = []
        for model in self._candidate_models():
            for attempt in range(1, self.max_retries_per_model + 1):
                try:
                    response = self._request_multimodal_text(
                        model=model,
                        prompt=prompt,
                        image_bytes=image_bytes,
                        mime_type=mime_type,
                    )
                    text = getattr(response, "text", None)
                    if not text:
                        raise RuntimeError(f"Gemini model {model} returned no text in multimodal response.")
                    cleaned = text.strip()
                    if cleaned.startswith("```") and cleaned.endswith("```"):
                        cleaned = re.sub(r"^```(?:text)?\s*", "", cleaned, flags=re.IGNORECASE)
                        cleaned = re.sub(r"\s*```$", "", cleaned)
                        cleaned = cleaned.strip()
                    self.model = model
                    self.models_used.append(model)
                    self.last_raw_output = cleaned
                    self.last_raw_output_model = model
                    self.last_generation_mode = "multimodal_text"
                    self.last_attempt_log = attempt_log
                    return cleaned
                except Exception as exc:
                    attempt_log.append(
                        f"{model} [multimodal] attempt {attempt}/{self.max_retries_per_model}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    if _is_fatal_configuration_error(exc):
                        self.last_attempt_log = attempt_log
                        raise RuntimeError(
                            "Gemini multimodal failed with a non-retryable authentication/configuration error:\n"
                            + "\n".join(attempt_log)
                        ) from exc
                    if _is_model_not_found(exc) or _is_bad_request(exc):
                        print(
                            f"[Gemini] Modelo {model} não aceitou a leitura multimodal. "
                            "Tentando modelo alternativo...",
                            flush=True,
                        )
                        break
                    if _is_transient_error(exc) and attempt < self.max_retries_per_model:
                        server_delay = _retry_after_seconds(exc)
                        exponential = self.base_delay_seconds * (2 ** (attempt - 1))
                        delay = max(exponential, server_delay or 0.0) + 1.0 + random.uniform(0.0, 0.75)
                        print(
                            f"[Gemini] Falha temporária na leitura multimodal. Nova tentativa em {delay:.1f}s...",
                            flush=True,
                        )
                        time.sleep(delay)
                        continue
                    if _is_transient_error(exc):
                        break
                    self.last_attempt_log = attempt_log
                    raise RuntimeError(
                        "Gemini multimodal transcription failed:\n" + "\n".join(attempt_log)
                    ) from exc

        self.last_attempt_log = attempt_log
        raise RuntimeError(
            "Gemini multimodal transcription failed after all configured models:\n"
            + "\n".join(attempt_log)
        )

    def _call_generate_content(
        self,
        *,
        model: str,
        prompt: str,
        schema: type[T],
        mode: str,
    ) -> T:
        response = self._request(model=model, prompt=prompt, mode=mode)
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError(f"Gemini model {model} returned no text in response.")

        self.last_raw_output = text
        self.last_raw_output_model = model
        self.last_generation_mode = mode
        payload = _clean_json_text(text)
        return schema.model_validate_json(payload)

    def generate_structured(self, prompt: str, schema: type[T]) -> T:
        attempt_log: list[str] = []
        schema_contract = _compact_schema_contract(schema)
        base_prompt = (
            prompt
            + "\n\nFORMATO DE SAIDA OBRIGATORIO:\n"
            + "Retorne UM unico objeto JSON, sem Markdown, sem comentarios e sem texto antes/depois. "
            + "O objeto deve obedecer ao JSON Schema abaixo. Nao copie o schema para os valores.\n"
            + schema_contract
        )

        for model in self._candidate_models():
            skip_model = False

            for mode in ("json_mime", "plain"):
                validation_error: Exception | None = None

                for attempt in range(1, self.max_retries_per_model + 1):
                    request_prompt = base_prompt
                    if validation_error is not None:
                        request_prompt += (
                            "\n\nCORRECAO DA RESPOSTA ANTERIOR:\n"
                            + _validation_feedback(validation_error)
                            + "\nGere novamente o objeto completo, compacto e valido. "
                            + "Nao repita chunks, prompt ou schema dentro dos campos. "
                            + "Use excerpts de evidencia curtos e literais."
                        )

                    try:
                        result = self._call_generate_content(
                            model=model,
                            prompt=request_prompt,
                            schema=schema,
                            mode=mode,
                        )
                        self.model = model
                        self.models_used.append(model)
                        self.last_attempt_log = attempt_log
                        return result
                    except Exception as exc:
                        attempt_log.append(
                            f"{model} [{mode}] attempt {attempt}/{self.max_retries_per_model}: "
                            f"{type(exc).__name__}: {exc}"
                        )

                        if _is_fatal_configuration_error(exc):
                            self.last_attempt_log = attempt_log
                            raise RuntimeError(
                                "Gemini request failed with a non-retryable authentication/configuration error:\n"
                                + "\n".join(attempt_log)
                            ) from exc

                        if _is_model_not_found(exc):
                            print(
                                f"[Gemini] Modelo {model} nao esta disponivel para esta conta. "
                                "Tentando modelo alternativo...",
                                flush=True,
                            )
                            skip_model = True
                            break

                        if _is_bad_request(exc):
                            if mode == "json_mime":
                                print(
                                    f"[Gemini] {model} rejeitou o modo JSON da API (400). "
                                    "Tentando o mesmo modelo em modo texto + validacao local...",
                                    flush=True,
                                )
                                break
                            print(
                                f"[Gemini] {model} rejeitou ate a chamada texto simples (400). "
                                "Tentando modelo alternativo...",
                                flush=True,
                            )
                            skip_model = True
                            break

                        if _is_model_output_error(exc):
                            validation_error = exc
                            raw_len = len(self.last_raw_output or "")
                            print(
                                f"[Gemini] JSON/estrutura invalida de {model} em {mode} "
                                f"({raw_len} caracteres). "
                                + (
                                    "Pedindo correcao..."
                                    if attempt < self.max_retries_per_model
                                    else "Mudando de modo/modelo..."
                                ),
                                flush=True,
                            )
                            if attempt < self.max_retries_per_model:
                                time.sleep(1.0)
                            continue

                        if _is_transient_error(exc):
                            if attempt < self.max_retries_per_model:
                                server_delay = _retry_after_seconds(exc)
                                exponential = self.base_delay_seconds * (2 ** (attempt - 1))
                                delay = max(exponential, server_delay or 0.0)
                                delay += 1.0 + random.uniform(0.0, 0.75)
                                print(
                                    f"[Gemini] Limite/indisponibilidade temporaria em {model}. "
                                    f"Nova tentativa em {delay:.1f}s...",
                                    flush=True,
                                )
                                time.sleep(delay)
                                continue
                            print(
                                f"[Gemini] {model} continua indisponivel/limitado. "
                                "Tentando modelo alternativo...",
                                flush=True,
                            )
                            skip_model = True
                            break

                        self.last_attempt_log = attempt_log
                        raise RuntimeError(
                            "Gemini extraction failed on GenerateContent:\n"
                            + "\n".join(attempt_log)
                        ) from exc

                if skip_model:
                    break

        self.last_attempt_log = attempt_log
        raise RuntimeError(
            "Gemini extraction failed after all configured models/modes:\n"
            + "\n".join(attempt_log)
        )
