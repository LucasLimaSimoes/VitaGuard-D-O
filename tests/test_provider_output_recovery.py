from pydantic import BaseModel, ValidationError

from vitaguard_do.extraction.provider import (
    _clean_json_text,
    _is_model_output_error,
    _is_transient_error,
)


class Tiny(BaseModel):
    value: str


def test_clean_json_code_fence():
    assert _clean_json_text('```json\n{"value":"ok"}\n```') == '{"value":"ok"}'


def test_validation_error_is_model_output_error():
    try:
        Tiny.model_validate_json('{"value":"broken}')
    except ValidationError as exc:
        assert _is_model_output_error(exc)
    else:
        raise AssertionError('expected validation error')


def test_quota_is_transient():
    assert _is_transient_error(RuntimeError('429 quota exceeded. Please retry in 12.3s'))


def test_clean_json_preamble():
    raw = 'Aqui esta o JSON:\n{"value":"ok"}\nObrigado.'
    assert _clean_json_text(raw) == '{"value":"ok"}'
