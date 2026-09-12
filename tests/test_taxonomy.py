from vitaguard_do.taxonomy import load_taxonomies


def test_taxonomy_loads():
    reg = load_taxonomies()
    assert len(reg.items) >= 40


def test_alias_resolution():
    reg = load_taxonomies()
    assert reg.resolve("coverages", "Reembolso da Empresa").id == "side_b"
    assert reg.resolve("coverages", "Entity Coverage").id == "side_c"
    assert reg.resolve("financial_fields", "LMG").id == "maximum_guarantee_limit"
