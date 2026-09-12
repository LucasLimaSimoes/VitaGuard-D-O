from pathlib import Path

from vitaguard_do.extraction.assembler import assemble_policy
from vitaguard_do.extraction.models import (
    CoreExtraction,
    DefinitionFact,
    EvidenceRef,
    FinancialFact,
    ItemFact,
    RawStatus,
    RiskExtraction,
    ScalarFact,
    SemanticExtraction,
)
from vitaguard_do.ingestion.pdf import ingest_pdf
from vitaguard_do.taxonomy.loader import load_taxonomies


ROOT = Path(__file__).resolve().parents[1]


def ev(chunk, excerpt):
    return [EvidenceRef(chunk_id=chunk.chunk_id, page_number=chunk.page_number, excerpt=excerpt)]


def test_assembler_builds_policy_and_validates_evidence():
    doc = ingest_pdf(ROOT / "data" / "synthetic" / "vitaguard_do_essencial.pdf")
    page1 = next(c for c in doc.chunks if c.page_number == 1)
    page2 = next(c for c in doc.chunks if c.page_number == 2)
    page3 = next(c for c in doc.chunks if c.page_number == 3)

    scalar = [
        ScalarFact(field_id="insurer", status=RawStatus.FOUND, raw_value="VitaGuard Seguros Ficticios S.A.", evidence=ev(page1, "VitaGuard Seguros Ficticios S.A.")),
        ScalarFact(field_id="product_name", status=RawStatus.FOUND, raw_value="VitaGuard D&O Essencial", evidence=ev(page1, "VitaGuard D&O Essencial")),
        ScalarFact(field_id="susep_process", status=RawStatus.NOT_FOUND),
        ScalarFact(field_id="policy_number", status=RawStatus.FOUND, raw_value="2026-DO-ESS-001", evidence=ev(page1, "2026-DO-ESS-001")),
        ScalarFact(field_id="insured", status=RawStatus.FOUND, raw_value="Atlas Tecnologia S.A.", evidence=ev(page1, "Atlas Tecnologia S.A.")),
        ScalarFact(field_id="policyholder", status=RawStatus.FOUND, raw_value="Atlas Tecnologia S.A.", evidence=ev(page1, "Atlas Tecnologia S.A.")),
        ScalarFact(field_id="document_version", status=RawStatus.FOUND, raw_value="Sintetico v1.0 - 18/08/2026", evidence=ev(page1, "Sintetico v1.0 - 18/08/2026")),
        ScalarFact(field_id="policy_period_start", status=RawStatus.FOUND, normalized_value="2026-01-01", evidence=ev(page1, "2026-01-01 a 2027-01-01")),
        ScalarFact(field_id="policy_period_end", status=RawStatus.FOUND, normalized_value="2027-01-01", evidence=ev(page1, "2026-01-01 a 2027-01-01")),
        ScalarFact(field_id="currency", status=RawStatus.FOUND, raw_value="BRL", evidence=ev(page1, "Moeda BRL")),
        ScalarFact(field_id="retroactive_date", status=RawStatus.FOUND, normalized_value="2023-01-01", evidence=ev(page1, "2023-01-01")),
        ScalarFact(field_id="extended_reporting_period", status=RawStatus.FOUND, raw_value="12 meses", normalized_value="12 meses", evidence=ev(page1, "12 meses")),
        ScalarFact(field_id="geographic_scope", status=RawStatus.FOUND, raw_value="Brasil", evidence=ev(page1, "Ambito geografico: Brasil")),
        ScalarFact(field_id="jurisdiction", status=RawStatus.FOUND, raw_value="Brasil", evidence=ev(page1, "Jurisdicao: Brasil")),
        ScalarFact(field_id="coverage_trigger", status=RawStatus.FOUND, raw_value="A base de reclamacoes", evidence=ev(page1, "Base de cobertura: A base de reclamacoes")),
    ]
    core = CoreExtraction(
        scalar_facts=scalar,
        financial_facts=[
            FinancialFact(field_id="premium", original_name="Premio total", raw_value="R$ 48.000,00", kind="MONEY", numeric_value=48000, currency="BRL", evidence=ev(page1, "Premio total R$ 48.000,00")),
            FinancialFact(field_id="maximum_guarantee_limit", original_name="Limite Maximo de Garantia", raw_value="R$ 10.000.000,00", kind="MONEY", numeric_value=10000000, currency="BRL", evidence=ev(page1, "Limite Maximo de Garantia R$ 10.000.000,00")),
            FinancialFact(field_id="aggregate_limit", original_name="Limite agregado", raw_value="R$ 10.000.000,00", kind="MONEY", numeric_value=10000000, currency="BRL", evidence=ev(page1, "Limite agregado R$ 10.000.000,00")),
        ],
    )
    risk = RiskExtraction(
        coverages=[
            ItemFact(canonical_id="side_a", original_name="Cobertura A - Pagamento a Pessoa Segurada", description="Pagamento direto", evidence=ev(page3, "Cobertura A - Pagamento a Pessoa Segurada")),
        ]
    )
    semantic = SemanticExtraction(
        definitions=[
            DefinitionFact(canonical_term="claim", original_term="Reclamacao", definition_text="Demanda escrita", evidence=ev(page2, "Reclamacao")),
        ]
    )

    policy, report = assemble_policy(
        document=doc,
        core=core,
        risk=risk,
        semantic=semantic,
        registry=load_taxonomies(ROOT / "vitaguard_do" / "taxonomy"),
        provider_model="mock",
    )

    assert policy.identification.policy_number.value == "2026-DO-ESS-001"
    assert policy.contractual_terms.premium.value.numeric_value == 48000
    assert policy.coverages[0].canonical_id == "side_a"
    assert policy.definitions[0].canonical_term == "claim"
    assert report.invalid_claims == 0
    assert report.valid_claims > 0
