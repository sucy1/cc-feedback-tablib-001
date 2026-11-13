""" Tablib - *SV Support.
"""

__lazy_modules__ = {"csv", "io", "tablib.exceptions"}

import csv
from io import StringIO

from ..exceptions import UnsupportedFormat

#: Encodings tried, in order, when decoding byte streams without a BOM.
DETECT_ENCODINGS = ('utf-8', 'gb18030')

#: Delimiters considered when sniffing the dialect of a byte stream.
SNIFF_DELIMITERS = (',', ';', '\t', '|')

_UTF8_BOM = b'\xef\xbb\xbf'


def _decode_bytes(raw, errors='strict'):
    """Decode `raw` bytes into text.

    A UTF-8 BOM forces utf-8-sig; otherwise utf-8 and gb18030 (a superset of
    GBK) are tried in order. With ``errors='strict'`` (the default), input
    that decodes under neither encoding raises :class:`UnsupportedFormat`.
    """
    if raw.startswith(_UTF8_BOM):
        return raw.decode('utf-8-sig', errors=errors)
    for encoding in DETECT_ENCODINGS:
        try:
            return raw.decode(encoding, errors=errors)
        except UnicodeDecodeError:
            continue
    if errors == 'strict':
        raise UnsupportedFormat(
            'Unable to decode byte stream: not valid utf-8 or gb18030.'
        )
    return raw.decode(DETECT_ENCODINGS[0], errors='replace')


def _sniff_delimiter(text):
    """Detect the delimiter used in `text` among ``, ; \\t |``.

    Quoted fields are honored: a delimiter wrapped in quotes does not count.
    Raises :class:`UnsupportedFormat` when no delimiter fits.
    """
    try:
        return csv.Sniffer().sniff(
            text[:8192], delimiters=''.join(SNIFF_DELIMITERS)
        ).delimiter
    except csv.Error:
        pass
    # Fallback: parse a sample with each candidate and keep the one producing
    # the most consistent multi-column rows.
    best_delimiter = None
    best_score = 0
    sample = StringIO(text[:8192], newline='')
    for delimiter in SNIFF_DELIMITERS:
        sample.seek(0)
        rows = [row for row in csv.reader(sample, delimiter=delimiter) if row]
        if not rows or len(rows[0]) < 2:
            continue
        width = len(rows[0])
        score = sum(len(row) == width for row in rows)
        if score > best_score:
            best_delimiter, best_score = delimiter, score
    if best_delimiter is None:
        raise UnsupportedFormat('Unable to detect the CSV delimiter.')
    return best_delimiter


class CSVFormat:
    title = 'csv'
    extensions = ('csv',)

    DEFAULT_DELIMITER = ','

    #: Maximum number of characters written to the target file in one call.
    WRITE_CHUNK_SIZE = 64 * 1024

    @classmethod
    def export_stream_set(cls, dataset, **kwargs):
        """Returns CSV representation of Dataset as file-like."""
        stream = StringIO()

        kwargs.setdefault('delimiter', cls.DEFAULT_DELIMITER)

        _csv = csv.writer(stream, **kwargs)

        for row in dataset._package(dicts=False):
            _csv.writerow(row)

        stream.seek(0)
        return stream

    @classmethod
    def export_set(cls, dataset, **kwargs):
        """Returns CSV representation of Dataset."""
        stream = cls.export_stream_set(dataset, **kwargs)
        return stream.getvalue()

    @classmethod
    def write_set(cls, dataset, file, **kwargs):
        """Streams CSV representation of Dataset into a text file object.

        Rows are generated and written incrementally; every single
        ``file.write()`` call stays below ``WRITE_CHUNK_SIZE``.
        """
        kwargs.setdefault('delimiter', cls.DEFAULT_DELIMITER)

        buffer = StringIO()
        writer = csv.writer(buffer, **kwargs)

        for row in dataset._package(dicts=False):
            writer.writerow(row)
            if buffer.tell() >= cls.WRITE_CHUNK_SIZE:
                cls._flush_buffer(file, buffer)
        cls._flush_buffer(file, buffer)

    @classmethod
    def _flush_buffer(cls, file, buffer):
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        for start in range(0, len(text), cls.WRITE_CHUNK_SIZE):
            file.write(text[start:start + cls.WRITE_CHUNK_SIZE])

    @classmethod
    def import_set(cls, dset, in_stream, headers=True, skip_lines=0, **kwargs):
        """Returns dataset from CSV stream."""

        dset.wipe()

        in_stream = cls._coerce_text_stream(in_stream, kwargs)

        kwargs.setdefault('delimiter', cls.DEFAULT_DELIMITER)

        rows = csv.reader(in_stream, **kwargs)
        for i, row in enumerate(rows):
            if i < skip_lines:
                continue
            if i == skip_lines and headers:
                dset.headers = row
            elif row:
                if i > 0 and len(row) < dset.width:
                    row += [''] * (dset.width - len(row))
                dset.append(row)

    @classmethod
    def _coerce_text_stream(cls, in_stream, kwargs):
        """Return a text stream for `in_stream`.

        Binary streams (bytes input, files opened in binary mode) are decoded
        — encoding is detected from the BOM or content, and the delimiter is
        sniffed unless the caller pinned one explicitly. Text streams are
        returned untouched (legacy behavior).
        """
        try:
            probe = in_stream.read(0)
        except Exception:
            return in_stream
        if not isinstance(probe, bytes):
            return in_stream

        text = _decode_bytes(in_stream.read())
        if not text.strip():
            raise UnsupportedFormat('CSV input is empty.')
        if 'delimiter' not in kwargs and 'dialect' not in kwargs:
            kwargs['delimiter'] = _sniff_delimiter(text)
        return StringIO(text, newline='')

    @classmethod
    def detect(cls, stream, delimiter=None):
        """Returns True if given stream is valid CSV."""
        try:
            sample = stream.read(2048)
            if isinstance(sample, bytes):
                # Lenient decoding: a multi-byte character may straddle the
                # sample boundary, and only ASCII delimiters matter here.
                sample = _decode_bytes(sample, errors='replace')
                delimiters = delimiter or ''.join(SNIFF_DELIMITERS)
            else:
                delimiters = delimiter or cls.DEFAULT_DELIMITER
            csv.Sniffer().sniff(sample, delimiters=delimiters)
            return True
        except Exception:
            return False
