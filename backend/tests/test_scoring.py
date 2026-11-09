import pytest

from tests.golden.scoring import compare_results


def ok(ref, gen, **kw):
    return compare_results(ref, gen, **kw).correct


def test_identical_and_order_insensitive():
    assert ok([[1, "a"], [2, "b"]], [[2, "b"], [1, "a"]])


def test_ordered_requires_same_sequence():
    assert not ok([[1], [2]], [[2], [1]], ordered=True)
    assert ok([[1], [2]], [[1], [2]], ordered=True)


def test_row_count_and_value_differences_fail():
    assert not ok([[1], [2]], [[1]])
    assert not ok([[1], [2]], [[1], [3]])
    assert not ok([[5]], [[6]])


def test_both_empty_matches_but_empty_vs_nonempty_does_not():
    assert ok([], [])
    assert not ok([], [[1]])
    assert not ok([[1]], [])


def test_numeric_tolerance_for_rounding():
    assert ok([[3.0518556701]], [[3.05]])
    assert ok([[112.00515]], [[112.0]])
    assert ok([[26.78]], [[26.784641068]])
    assert ok([[1000]], [[1000.0]])
    assert not ok([[26.78]], [[26.9]])
    assert not ok([[1000]], [[1001]])


def test_extra_columns_allowed_but_missing_columns_not():
    verdict = compare_results([["x"], ["y"]], [[1, "x"], [2, "y"]])
    assert verdict.correct and verdict.extra_columns == 1
    assert not ok([[1, "x"]], [["x"]])


def test_column_order_and_names_do_not_matter():
    assert ok([[1, "a"], [2, "b"]], [["a", 1], ["b", 2]])


def test_columns_matching_individually_but_misaligned_rows_fail():
    # same per-column values, but the pairing is different
    assert not ok([[1, "a"], [2, "b"]], [[1, "b"], [2, "a"]])


def test_duplicate_valued_reference_columns():
    assert ok([[1, 1], [2, 2]], [[1, 1], [2, 2]])
    assert ok([[1, 1], [2, 2]], [[1, 9, 1], [2, 8, 2]])


def test_text_ignores_padding_and_whitespace_but_not_case_or_content():
    assert ok([["English             "]], [["English"]])
    assert not ok([["ACADEMY"]], [["Academy"]])


@pytest.mark.parametrize(
    "a,b",
    [
        ("2005-07-01T00:00:00", "2005-07-01"),
        ("2005-07-01T00:00:00", "2005-07"),
        ("2005-07-31", "2005-07-31T00:00:00"),
    ],
)
def test_date_forms_are_equivalent(a, b):
    assert ok([[a]], [[b]])


def test_timestamps_with_time_are_not_collapsed_to_dates():
    assert not ok([["2005-05-24T22:53:30"]], [["2005-05-24"]])
    assert ok([["2005-05-24T22:53:30"]], [["2005-05-24 22:53:30"]])


def test_none_handling():
    assert ok([[None, 1]], [[None, 1]])
    assert not ok([[None]], [[0]])
