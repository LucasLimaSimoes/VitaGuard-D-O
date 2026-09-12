from vitaguard_do.extraction.normalization import (
    canonicalize_coverage_trigger,
    canonicalize_geographic_scope,
    canonicalize_jurisdiction,
)


def test_worldwide_equivalents_are_canonicalized():
    assert canonicalize_geographic_scope("Mundial") == "WORLDWIDE"
    assert canonicalize_geographic_scope("qualquer lugar do mundo") == "WORLDWIDE"
    assert canonicalize_geographic_scope("Worldwide") == "WORLDWIDE"


def test_claims_made_notification_equivalents_are_canonicalized():
    assert canonicalize_coverage_trigger("Reclamações com Notificação") == "CLAIMS_MADE_WITH_NOTIFICATION"
    assert canonicalize_coverage_trigger("Claims-made with notification") == "CLAIMS_MADE_WITH_NOTIFICATION"


def test_brazil_jurisdiction_equivalents_are_canonicalized():
    assert canonicalize_jurisdiction("Brasil") == "BR"
    assert canonicalize_jurisdiction("Brazil") == "BR"
    assert canonicalize_jurisdiction("República Federativa do Brasil") == "BR"
