from uuid import uuid4

from app.imports.matching import normalize, similarity, suggest

CATALOG = [
    (uuid4(), "Сыр Моцарелла"),
    (uuid4(), "Сыр Пармезан"),
    (uuid4(), "Сыр Грана Падано"),
    (uuid4(), "Куриное филе"),
    (uuid4(), "Руккола"),
    (uuid4(), "Масло оливковое"),
    (uuid4(), "Сливки 33%"),
    (uuid4(), "Салат романо"),
]


def test_normalize() -> None:
    assert normalize("  Сыр  МОЦАРЕЛЛА. ") == normalize("сыр моцарелла") == "сыр моцарелла"
    assert normalize("Свёкла") == "свекла"
    assert normalize("Сливки 33%") == "сливки 33%"


def test_names_from_another_system_rank_the_right_product_first() -> None:
    cases = {
        "Моцарелла фиор ди латте 45%": "Сыр Моцарелла",
        "Филе куриное охл.": "Куриное филе",
        "Руккола свежая, кг": "Руккола",
        "Масло оливк. Extra Virgin": "Масло оливковое",
        "Сыр пармезан выдержка 12 мес": "Сыр Пармезан",
    }
    for source, expected in cases.items():
        best = suggest(source, CATALOG)
        assert best and best[0].name == expected, (source, best)


def test_unrelated_name_gets_no_suggestions() -> None:
    assert suggest("Мука пшеничная", CATALOG) == []
    assert similarity("Говядина", "Руккола") < 0.3


def test_suggestions_are_limited_and_ordered() -> None:
    result = suggest("Сыр", CATALOG, threshold=0.0)
    assert len(result) == 3
    assert [c.score for c in result] == sorted((c.score for c in result), reverse=True)
