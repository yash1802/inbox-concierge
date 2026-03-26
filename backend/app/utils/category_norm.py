import re


def normalize_category_name(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s
