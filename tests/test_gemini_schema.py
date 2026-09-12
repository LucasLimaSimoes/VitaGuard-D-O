import json

from vitaguard_do.extraction.gemini_schema import gemini_json_schema
from vitaguard_do.extraction.models import CoreExtraction, RiskExtraction, SemanticExtraction


def test_gemini_schemas_strip_unsupported_pydantic_keywords():
    for model in (CoreExtraction, RiskExtraction, SemanticExtraction):
        raw = model.model_json_schema()
        safe = gemini_json_schema(model)
        raw_text = json.dumps(raw, ensure_ascii=False)
        safe_text = json.dumps(safe, ensure_ascii=False)

        assert safe["type"] == "object"
        assert len(safe_text) <= len(raw_text)
        for forbidden in ("default", "minLength", "maxLength"):
            assert f'"{forbidden}"' not in safe_text


def test_gemini_schema_keeps_refs_and_core_shape():
    safe = gemini_json_schema(CoreExtraction)
    assert "properties" in safe
    assert "scalar_facts" in safe["properties"]
    assert "$defs" in safe
    assert "$ref" in json.dumps(safe)
