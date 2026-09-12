from __future__ import annotations

import argparse
import os

from pydantic import BaseModel

from vitaguard_do.extraction.provider import GeminiProvider


class SmokeResult(BaseModel):
    ok: bool
    message: str


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='gemini-3.5-flash-lite')
    args = parser.parse_args()

    key = os.getenv('GEMINI_API_KEY')
    if not key:
        raise SystemExit('GEMINI_API_KEY nao configurada.')

    provider = GeminiProvider(
        api_key=key,
        model=args.model,
        fallback_models=['gemini-3.1-flash-lite'],
        max_retries_per_model=2,
        min_request_interval_seconds=0,
        max_output_tokens=512,
    )
    parsed = provider.generate_structured(
        'Retorne ok=true e message="VitaGuard API OK".',
        SmokeResult,
    )
    print('[OK] Gemini JSON + validacao Pydantic local:', parsed.model_dump())
    print('[OK] Modelo usado:', provider.model)
    print('[OK] Modo usado:', provider.last_generation_mode)


if __name__ == '__main__':
    main()
