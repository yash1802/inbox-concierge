from app.utils.category_norm import normalize_category_name


def test_normalize_category_name() -> None:
    assert normalize_category_name("  Jobs  ") == "jobs"
    assert normalize_category_name("Foo   Bar") == "foo bar"
