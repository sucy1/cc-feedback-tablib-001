"""Tests for the reconciliation I/O pipeline:

- CSV/TSV byte-stream loading with encoding and delimiter auto-detection
- Unified sheet-title rules for XLSX and ODS databooks
- Streaming Dataset.export_to_file()
"""

import tempfile
import unittest
from io import BytesIO, StringIO
from pathlib import Path

import tablib
from tablib.exceptions import UnsupportedFormat


HEADERS = ['name', 'score', 'region']
ROWS = [
    ['张三', '90', '华东'],
    ['李四', '67', '华南'],
    ['王五', '82', '华西'],
]


def make_csv_text(delimiter=','):
    def quote(field):
        if delimiter in field:
            return f'"{field}"'
        return field

    lines = [delimiter.join(HEADERS)]
    lines += [delimiter.join(quote(f) for f in row) for row in ROWS]
    return '\r\n'.join(lines) + '\r\n'


def assert_dataset_matches(testcase, dset):
    testcase.assertEqual(dset.headers, HEADERS)
    testcase.assertEqual([list(row) for row in dset._data], ROWS)


class CSVDialectLoadTests(unittest.TestCase):
    """The same data exported with different encodings/delimiters must load
    into identical headers and rows."""

    def variants(self):
        return {
            'utf8_comma': make_csv_text(',').encode('utf-8'),
            'utf8_bom_comma': make_csv_text(',').encode('utf-8-sig'),
            'gbk_semicolon': make_csv_text(';').encode('gbk'),
            'gb18030_pipe': make_csv_text('|').encode('gb18030'),
            'utf8_tab': make_csv_text('\t').encode('utf-8'),
        }

    def test_bytes_all_dialects_load_identically(self):
        for name, payload in self.variants().items():
            with self.subTest(variant=name):
                dset = tablib.Dataset().load(payload, 'csv')
                assert_dataset_matches(self, dset)

    def test_bytes_auto_format_detection(self):
        for name, payload in self.variants().items():
            with self.subTest(variant=name):
                dset = tablib.Dataset().load(payload)
                assert_dataset_matches(self, dset)

    def test_file_path_input(self):
        for name, payload in self.variants().items():
            with self.subTest(variant=name):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / 'upstream.csv'
                    path.write_bytes(payload)
                    dset = tablib.Dataset().load(str(path), 'csv')
                    assert_dataset_matches(self, dset)

    def test_open_binary_file_object(self):
        payload = make_csv_text(';').encode('gbk')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'upstream.csv'
            path.write_bytes(payload)
            with open(path, 'rb') as fh:
                dset = tablib.Dataset().load(fh, 'csv')
        assert_dataset_matches(self, dset)

    def test_open_text_file_object(self):
        payload = make_csv_text(',')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'upstream.csv'
            path.write_text(payload, encoding='utf-8')
            with open(path, encoding='utf-8') as fh:
                dset = tablib.Dataset().load(fh, 'csv')
        assert_dataset_matches(self, dset)

    def test_quoted_delimiters_do_not_confuse_sniffer(self):
        # Fields contain every other candidate delimiter, quoted.
        rows = [
            ['name', 'note', 'score'],
            ['"a,b"', '"x;y"', '1'],
            ['"c|d"', '"e\tf"', '2'],
        ]
        for delimiter in (',', ';', '\t', '|'):
            with self.subTest(delimiter=delimiter):
                text = '\n'.join(delimiter.join(r) for r in rows) + '\n'
                dset = tablib.Dataset().load(text.encode('utf-8'), 'csv')
                self.assertEqual(dset.headers, ['name', 'note', 'score'])
                self.assertEqual(dset.width, 3)
                self.assertEqual(dset.height, 2)

    def test_explicit_delimiter_kwarg_wins_over_sniffing(self):
        payload = make_csv_text(';').encode('utf-8')
        dset = tablib.Dataset().load(payload, 'csv', delimiter=';')
        assert_dataset_matches(self, dset)

    def test_skip_lines_with_bytes(self):
        payload = ('junk,line\n' + make_csv_text(',')).encode('utf-8')
        dset = tablib.Dataset().load(payload, 'csv', skip_lines=1)
        assert_dataset_matches(self, dset)

    def test_tsv_bytes(self):
        payload = make_csv_text('\t').encode('gbk')
        dset = tablib.Dataset().load(payload, 'tsv')
        assert_dataset_matches(self, dset)

    def test_binary_garbage_raises_unsupported_format(self):
        with self.assertRaises(UnsupportedFormat):
            tablib.Dataset().load(b'\xff' * 64, 'csv')

    def test_undelimited_text_raises_unsupported_format(self):
        with self.assertRaises(UnsupportedFormat):
            tablib.Dataset().load('just some words'.encode('utf-8'), 'csv')

    def test_empty_bytes_raise_unsupported_format(self):
        with self.assertRaises(UnsupportedFormat):
            tablib.Dataset().load(b'', 'csv')

    def test_empty_file_raises_unsupported_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'empty.csv'
            path.write_bytes(b'')
            with self.assertRaises(UnsupportedFormat):
                tablib.Dataset().load(str(path), 'csv')


class SheetTitleTests(unittest.TestCase):
    """XLSX and ODS must share the exact same sheet-title rules."""

    LONG_TITLE = '2026年第一季度区域指标汇总-华东区域明细表（含内部调整核对）'

    def make_book(self, titles):
        book = tablib.Databook()
        for title in titles:
            dset = tablib.Dataset(headers=['a'], title=title)
            dset.append(['1'])
            book.add_sheet(dset)
        return book

    def xlsx_sheetnames(self, book):
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(book.export('xlsx')))
        return wb.sheetnames

    def ods_sheetnames(self, book):
        from odf import opendocument, table
        doc = opendocument.load(BytesIO(book.export('ods')))
        return [
            t.getAttribute('name')
            for t in doc.spreadsheet.getElementsByType(table.Table)
        ]

    def assert_both_formats_agree(self, titles, expected):
        book = self.make_book(titles)
        xlsx_names = self.xlsx_sheetnames(book)
        ods_names = self.ods_sheetnames(book)
        self.assertEqual(xlsx_names, expected)
        self.assertEqual(ods_names, expected)
        # Round-trip: importing the exports back must yield the same titles.
        xlsx_book = tablib.Databook().load(book.export('xlsx'), 'xlsx')
        ods_book = tablib.Databook().load(book.export('ods'), 'ods')
        self.assertEqual([s.title for s in xlsx_book.sheets()], expected)
        self.assertEqual([s.title for s in ods_book.sheets()], expected)

    def test_long_title_truncated_to_31(self):
        self.assertGreater(len(self.LONG_TITLE), 31)
        self.assert_both_formats_agree([self.LONG_TITLE], [self.LONG_TITLE[:31]])

    def test_invalid_chars_replaced_with_underscore(self):
        self.assert_both_formats_agree(
            ['旧模板[汇总]:华东/明细\\*?'],
            ['旧模板_汇总__华东_明细___'],
        )

    def test_strip_whitespace_and_quotes(self):
        self.assert_both_formats_agree(
            ["  '华东区:明细'  "],
            ['华东区_明细'],
        )

    def test_empty_title_falls_back_to_position(self):
        self.assert_both_formats_agree(
            ['甲', None, '', "  ''  "],
            ['甲', 'Sheet2', 'Sheet3', 'Sheet4'],
        )

    def test_duplicate_titles_get_numeric_suffix(self):
        self.assert_both_formats_agree(
            ['华东明细', '华东明细', '华东明细 '],
            ['华东明细', '华东明细_2', '华东明细_3'],
        )

    def test_duplicate_titles_case_insensitive(self):
        self.assert_both_formats_agree(
            ['Report', 'REPORT', 'report'],
            ['Report', 'REPORT_2', 'report_3'],
        )

    def test_duplicate_long_titles(self):
        title = 'x' * 40
        self.assert_both_formats_agree(
            [title, title, title],
            ['x' * 31, 'x' * 29 + '_2', 'x' * 28 + '_3'],
        )

    def test_export_set_sanitizes_title(self):
        dset = tablib.Dataset(headers=['a'], title='bad:name[1]')
        dset.append(['1'])
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(dset.export('xlsx')))
        self.assertEqual(wb.sheetnames, ['bad_name_1_'])
        from odf import opendocument, table
        doc = opendocument.load(BytesIO(dset.export('ods')))
        names = [
            t.getAttribute('name')
            for t in doc.spreadsheet.getElementsByType(table.Table)
        ]
        self.assertEqual(names, ['bad_name_1_'])


class RecordingWriter:
    """Text-file-like object recording every write() call."""

    def __init__(self):
        self.chunks = []

    def write(self, text):
        self.chunks.append(text)
        return len(text)

    def getvalue(self):
        return ''.join(self.chunks)


class ExportToFileTests(unittest.TestCase):
    def make_dataset(self, rows=3000):
        dset = tablib.Dataset(headers=['id', 'name', 'amount', 'note'])
        for i in range(rows):
            dset.append([str(i), f'供应商{i}', f'{i}.50', '月末对账明细' * 3])
        return dset

    def test_content_matches_export(self):
        dset = self.make_dataset(rows=100)
        expected = dset.export('csv')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'out.csv'
            dset.export_to_file(str(path), format='csv')
            self.assertEqual(path.read_bytes(), expected.encode('utf-8'))

    def test_open_text_file_object(self):
        dset = self.make_dataset(rows=100)
        expected = dset.export('csv')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'out.csv'
            with open(path, 'w', newline='', encoding='utf-8') as fh:
                dset.export_to_file(fh, format='csv')
            self.assertEqual(path.read_bytes(), expected.encode('utf-8'))

    def test_open_binary_file_object(self):
        dset = self.make_dataset(rows=100)
        expected = dset.export('csv')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'out.csv'
            with open(path, 'wb') as fh:
                dset.export_to_file(fh, format='csv')
            self.assertEqual(path.read_bytes(), expected.encode('utf-8'))

    def test_writes_are_chunked_below_64k(self):
        dset = self.make_dataset(rows=3000)
        # A single row larger than 64KB must also be split.
        dset.append(['big', 'x' * 150_000, '1', ''])
        expected = dset.export('csv')
        self.assertGreater(len(expected), 64 * 1024)

        writer = RecordingWriter()
        dset.export_to_file(writer, format='csv')

        self.assertGreater(len(writer.chunks), 1)
        for chunk in writer.chunks:
            self.assertLessEqual(len(chunk), 64 * 1024)
        self.assertEqual(writer.getvalue(), expected)

    def test_kwargs_pass_through(self):
        dset = self.make_dataset(rows=10)
        expected = dset.export('csv', delimiter=';')
        writer = RecordingWriter()
        dset.export_to_file(writer, format='csv', delimiter=';')
        self.assertEqual(writer.getvalue(), expected)

    def test_tsv(self):
        dset = self.make_dataset(rows=10)
        expected = dset.export('tsv')
        writer = RecordingWriter()
        dset.export_to_file(writer, format='tsv')
        self.assertEqual(writer.getvalue(), expected)

    def test_unsupported_format_raises(self):
        dset = self.make_dataset(rows=1)
        with self.assertRaises(UnsupportedFormat):
            dset.export_to_file(StringIO(), format='no_such_format')


if __name__ == '__main__':
    unittest.main()
