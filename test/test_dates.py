"""Stichtage aus dem Freitext der Kanten (graph/dates.py)."""

import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph.dates import parse_as_of

D = datetime.date


@pytest.mark.parametrize("text, expected", [
    ("2026-08-13", D(2026, 8, 13)),
    ("13.08.2026", D(2026, 8, 13)),
    ("August 13, 2026", D(2026, 8, 13)),
    ("Three Months Ended July 26, 2026", D(2026, 7, 26)),
    ("third quarter of fiscal year 2026 (until July 26, 2026)", D(2026, 9, 30)),
    ("Nov. 13, 2025", D(2025, 11, 13)),
    ("13 August 2026", D(2026, 8, 13)),
    ("Q3 FY2026", D(2026, 9, 30)),
    ("fiscal Q3 2026", D(2026, 9, 30)),
    ("Q4 FY25", D(2025, 12, 31)),
    ("third quarter 2026", D(2026, 9, 30)),
    ("fiscal third-quarter 2026", D(2026, 9, 30)),
    ("fiscal 2026 third-quarter", D(2026, 9, 30)),
    ("July 2023", D(2023, 7, 31)),
    ("fiscal 2025", D(2025, 12, 31)),
    ("FY2025", D(2025, 12, 31)),
    ("fiscal 2025 to fiscal 2027", D(2027, 12, 31)),
    ("2021", D(2021, 12, 31)),
])
def test_recognizes_common_forms(text, expected):
    assert parse_as_of(text) == expected


@pytest.mark.parametrize("text", [None, "", "today", "next quarter", "current fiscal year", "last week", "31.02.2026"])
def test_relative_or_broken_dates_give_none(text):
    assert parse_as_of(text) is None
