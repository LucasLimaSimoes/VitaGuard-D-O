from pathlib import Path
import pymupdf as fitz
from vitaguard_do import real_sources


def test_real_source_text_fingerprint(monkeypatch, tmp_path):
    pdf = tmp_path / 'aig.pdf'
    doc = fitz.open(); page = doc.new_page(); page.insert_text((72,72), 'AIG Seguros Brasil S.A. GARANTIA A - Segurados 15414.901229/2017-25'); doc.save(pdf); doc.close()
    meta = {
        'display_name':'AIG test','insurer':'AIG Seguros Brasil S.A.',
        'official_page_url':'https://example.test','pdf_url':'https://example.test/aig.pdf',
        'target_file':'aig.pdf','expected_sha256':None,'expected_pages':1,
        'expected_text_markers':['AIG Seguros Brasil S.A.','Garantia A - Segurados','15414.901229/2017-25'],
    }
    monkeypatch.setattr(real_sources,'load_real_sources',lambda:{'aig':meta})
    monkeypatch.setattr(real_sources,'ROOT',tmp_path)
    assert real_sources.validate_real_source('aig', pdf, strict=True) == pdf
