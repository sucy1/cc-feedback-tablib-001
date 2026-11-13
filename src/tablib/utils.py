__lazy_modules__ = {"io", "re"}

import re
from io import BytesIO, StringIO


def normalize_input(stream):
    """
    Accept either a str/bytes stream or a file-like object and always return a
    file-like object.
    """
    if isinstance(stream, str):
        return StringIO(stream, newline='')
    elif isinstance(stream, bytes):
        return BytesIO(stream)
    return stream


#: Characters not allowed in spreadsheet sheet titles (Excel/ODS convention).
INVALID_SHEET_TITLE_CHARS = re.compile(r'[\\/*?:\[\]]')

#: Maximum length of a sheet title.
MAX_SHEET_TITLE_LENGTH = 31


def sanitize_sheet_title(title, position):
    """Normalize a single sheet title.

    Leading/trailing whitespace and single quotes are stripped, characters
    invalid in sheet names (``\\ / * ? : [ ]``) are replaced with ``_`` and
    the result is truncated to 31 characters. An empty result falls back to
    ``Sheet{position}`` where `position` is the 1-based index of the sheet in
    its Databook.
    """
    title = (title or '').strip().strip("'").strip()
    title = INVALID_SHEET_TITLE_CHARS.sub('_', title)
    title = title[:MAX_SHEET_TITLE_LENGTH]
    return title or f'Sheet{position}'


def unique_sheet_titles(titles):
    """Return sanitized, de-duplicated sheet titles for a whole workbook.

    Duplicates (compared case-insensitively) get a ``_2``, ``_3``, ... suffix;
    the base name is truncated first so the result never exceeds 31
    characters (``_2`` truncates the base to 29, ``_3`` to 28, and so on).
    """
    used = set()
    unique = []
    for position, title in enumerate(titles, start=1):
        base = sanitize_sheet_title(title, position)
        candidate = base
        n = 1
        while candidate.lower() in used:
            n += 1
            candidate = f'{base[:MAX_SHEET_TITLE_LENGTH - n]}_{n}'
        used.add(candidate.lower())
        unique.append(candidate)
    return unique
