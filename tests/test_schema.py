import pytest
from pydantic import ValidationError
from vitaguard_do.models.schema import ExtractedField, ExtractionStatus


def test_found_requires_value():
    with pytest.raises(ValidationError):
        ExtractedField[str](status=ExtractionStatus.FOUND)


def test_not_found_rejects_value():
    with pytest.raises(ValidationError):
        ExtractedField[str](status=ExtractionStatus.NOT_FOUND, value="x")
