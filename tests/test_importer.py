import pytest

from src.importer import (
    MAX_FILE_BYTES,
    CsvValidationError,
    build_template_csv,
    parse_feedback_csv,
)


VALID_CSV = """feedback_text,country,user_type,product_category,rating,created_at,feedback_id,impact_level
包裹一直没有送到, SG ,新用户,电子产品,1,2026-10-20,,
支付一直失败,MY,活跃用户,美妆,2,2026/10/21,p-2,5
""".encode("utf-8")


def test_valid_csv_is_normalized_and_fingerprinted():
    preview = parse_feedback_csv(VALID_CSV)

    assert preview.errors == []
    assert preview.duplicate_count == 0
    assert len(preview.records) == 2
    assert preview.records[0]["country"] == "SG"
    assert preview.records[0]["created_at"] == "2026-10-20"
    assert preview.records[0]["impact_level"] is None
    assert len(preview.records[0]["fingerprint"]) == 64


def test_duplicate_rows_are_reported_once_and_not_returned_twice():
    duplicated = VALID_CSV + VALID_CSV.decode("utf-8").splitlines()[1].encode("utf-8") + b"\n"

    preview = parse_feedback_csv(duplicated)

    assert preview.duplicate_count == 1
    assert len(preview.records) == 2


@pytest.mark.parametrize(
    ("csv_text", "expected_error"),
    [
        ("feedback_text,country\nhello,SG\n", "缺少必填列"),
        (
            "feedback_text,country,user_type,product_category,rating,created_at\n"
            "hello,SG,new,electronics,6,2026-10-20\n",
            "rating 必须是 1–5 的整数",
        ),
        (
            "feedback_text,country,user_type,product_category,rating,created_at\n"
            "hello,SG,new,electronics,3,not-a-date\n",
            "created_at 不是有效日期",
        ),
    ],
)
def test_invalid_csv_returns_actionable_errors(csv_text, expected_error):
    preview = parse_feedback_csv(csv_text.encode("utf-8"))

    assert preview.errors
    assert expected_error in preview.errors[0].message


def test_file_size_limit_is_checked_before_parsing():
    with pytest.raises(CsvValidationError, match="10 MB"):
        parse_feedback_csv(b"x" * (MAX_FILE_BYTES + 1))


def test_template_contains_only_headers_and_no_fake_rows():
    lines = build_template_csv().decode("utf-8-sig").splitlines()

    assert len(lines) == 1
    assert lines[0].startswith("feedback_text,country,user_type")

