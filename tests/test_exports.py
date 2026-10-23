from io import BytesIO

import pandas as pd

from src.exports import export_csv


def test_export_preserves_requested_columns_and_utf8_chinese():
    content = export_csv(
        [{"category": "物流", "frequency": 3, "priority_score": 12.0}],
        columns=("category", "frequency", "priority_score"),
    )

    frame = pd.read_csv(BytesIO(content))
    assert frame.to_dict(orient="records") == [
        {"category": "物流", "frequency": 3, "priority_score": 12.0}
    ]


def test_export_neutralizes_spreadsheet_formula_prefixes():
    content = export_csv(
        [
            {"feedback_text": "=HYPERLINK(\"https://evil.example\")"},
            {"feedback_text": "+SUM(1,1)"},
            {"feedback_text": "-2+3"},
            {"feedback_text": "@cmd"},
            {"feedback_text": "普通文本"},
        ],
        columns=("feedback_text",),
    )
    values = pd.read_csv(BytesIO(content))["feedback_text"].tolist()

    assert values[:4] == [
        "'=HYPERLINK(\"https://evil.example\")",
        "'+SUM(1,1)",
        "'-2+3",
        "'@cmd",
    ]
    assert values[4] == "普通文本"

