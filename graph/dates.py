"""
dates.py
--------
Stichtage aus dem Freitext der Kanten ("July 26, 2026", "Q3 FY2026", "13.08.2026",
"third quarter 2026") -> Datum, um Kanten nach Aktualitaet zu ordnen. Nur zum
Sortieren: ein Quartal zaehlt als Ende des Kalenderquartals, auch wenn das
Geschaeftsjahr der Firma anders liegt. Relative Angaben ("next quarter",
"today") sagen ohne Erscheinungsdatum nichts - None.
"""

import calendar
import datetime
import re
from typing import Optional

MONTHS = {name: i for i, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")), 1) for name in names}
MONTH = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
ORDINAL = "(" + "|".join(ORDINALS) + ")"
YEAR = r"((?:19|20)\d\d)"
SHORT_YEAR = r"(?:FY|fiscal )\s?(\d\d)\b"


def _end_of_quarter(quarter: int, year: int) -> datetime.date:
    return datetime.date(year, quarter * 3, calendar.monthrange(year, quarter * 3)[1])


def _safe_date(year: int, month: int, day: int) -> Optional[datetime.date]:
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def parse_as_of(text) -> Optional[datetime.date]:
    """Spaetestes genanntes Datum: "fiscal 2025 to fiscal 2027" gilt bis 2027. None, wenn keins erkennbar ist."""
    if text is None:
        return None
    text = str(text).lower()
    found = []
    # Genaue Formen zuerst und aus dem Text nehmen: das Jahr in "13.08.2026" ist kein Jahresende
    def take(pattern, build):
        nonlocal text
        for match in re.finditer(pattern, text):
            value = build(*match.groups())
            if value:
                found.append(value)
        text = re.sub(pattern, " ", text)

    take(YEAR + r"-(\d\d)-(\d\d)", lambda y, m, d: _safe_date(int(y), int(m), int(d)))
    take(r"\b(\d{1,2})\.(\d{1,2})\." + YEAR, lambda d, m, y: _safe_date(int(y), int(m), int(d)))
    take(r"\b" + MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+" + YEAR,
         lambda m, d, y: _safe_date(int(y), MONTHS[m], int(d)))
    take(r"\b(\d{1,2})\.?\s+" + MONTH + r",?\s+" + YEAR, lambda d, m, y: _safe_date(int(y), MONTHS[m], int(d)))
    take(r"\bq([1-4])\s*(?:of\s+)?(?:fy|fiscal(?: year)?)?\s*'?" + YEAR, lambda q, y: _end_of_quarter(int(q), int(y)))
    take(r"\bq([1-4])\s*(?:of\s+)?(?:fy|fiscal(?: year)?)\s*'?(\d\d)\b", lambda q, y: _end_of_quarter(int(q), 2000 + int(y)))
    take(r"\b" + YEAR + r"\s+q([1-4])\b", lambda y, q: _end_of_quarter(int(q), int(y)))
    take(r"\b" + ORDINAL + r"[- ](?:fiscal[- ])?quarter(?: of)?(?: the)?(?: fiscal)?(?: year)?\s*(?:fy\s*)?" + YEAR,
         lambda o, y: _end_of_quarter(ORDINALS[o], int(y)))
    take(r"\b(?:fiscal|fy)\s*(?:year\s*)?" + YEAR + r"\s+" + ORDINAL + r"[- ]quarter",
         lambda y, o: _end_of_quarter(ORDINALS[o], int(y)))
    take(r"\b" + MONTH + r"\s+" + YEAR, lambda m, y: _safe_date(int(y), MONTHS[m], calendar.monthrange(int(y), MONTHS[m])[1]))
    take(SHORT_YEAR, lambda y: datetime.date(2000 + int(y), 12, 31))
    take(r"\b(?:fy)?" + YEAR + r"\b", lambda y: datetime.date(int(y), 12, 31))
    return max(found) if found else None
