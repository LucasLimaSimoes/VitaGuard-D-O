import pytest
from pydantic import ValidationError

from vitaguard_do.ingestion import IngestionConfig


def test_ingestion_config_defaults_are_valid():
    cfg = IngestionConfig()
    assert cfg.max_chunk_chars == 3000
    assert cfg.overlap_chars == 250


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValidationError):
        IngestionConfig(max_chunk_chars=1000, overlap_chars=1000)
