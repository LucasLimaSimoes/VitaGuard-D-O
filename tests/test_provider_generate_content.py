from pydantic import BaseModel

from vitaguard_do.extraction.provider import _compact_schema_contract


class Tiny(BaseModel):
    value: str


def test_v047_uses_prompt_schema_not_server_response_schema():
    contract = _compact_schema_contract(Tiny)
    assert '"value"' in contract
    assert 'response_schema' not in contract


def test_json_mode_contract_keeps_only_mime_control():
    # Regression: complex Pydantic schemas must NOT be sent as server-side
    # response_schema. The provider asks for JSON MIME and validates locally.
    expected = {
        "response_mime_type": "application/json",
        "max_output_tokens": 8192,
    }
    assert expected["response_mime_type"] == "application/json"
    assert "response_schema" not in expected

class _FakeTypes:
    @staticmethod
    def GenerateContentConfig(**kwargs):
        return dict(kwargs)

    class Part:
        @staticmethod
        def from_bytes(*, data, mime_type):
            return {"inline_data": {"data": data, "mime_type": mime_type}}


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return _FakeResponse('{"value":"ok"}')


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


def _provider_without_sdk_init():
    from vitaguard_do.extraction.provider import GeminiProvider

    p = GeminiProvider.__new__(GeminiProvider)
    p._types = _FakeTypes
    p._client = _FakeClient()
    p.requested_model = 'gemini-3.5-flash-lite'
    p.model = p.requested_model
    p.fallback_models = []
    p.max_retries_per_model = 1
    p.base_delay_seconds = 0.0
    p.min_request_interval_seconds = 0.0
    p.max_output_tokens = 8192
    p.models_used = []
    p.last_attempt_log = []
    p.last_raw_output = None
    p.last_raw_output_model = None
    p.last_generation_mode = None
    p._last_request_started_at = None
    return p


def test_request_json_mime_never_sends_response_schema():
    p = _provider_without_sdk_init()
    result = p._call_generate_content(
        model='gemini-3.5-flash-lite', prompt='x', schema=Tiny, mode='json_mime'
    )
    assert result.value == 'ok'
    config = p._client.models.calls[-1]['config']
    assert config['response_mime_type'] == 'application/json'
    assert config['max_output_tokens'] == 8192
    assert 'response_schema' not in config


def test_multimodal_transcription_sends_inline_image_and_returns_text():
    p = _provider_without_sdk_init()
    p._client.models.generate_content = lambda **kwargs: _FakeResponse("TEXTO DA APOLICE")
    result = p.transcribe_image(
        b"image-bytes",
        "image/png",
        source_name="scan.png",
        page_number=1,
    )
    assert result == "TEXTO DA APOLICE"
    assert p.last_generation_mode == "multimodal_text"
    assert p.model_summary == "gemini-3.5-flash-lite"
