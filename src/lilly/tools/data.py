"""data.profile: a bounded, streaming profile of a CSV or XLSX file."""
from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext, ToolResult
from lilly.tools.base import Tool, int_arg, resolve_in_scope, str_arg

DEFAULT_ROWS = 10_000
MAX_ROWS = 200_000
MAX_COLUMNS = 200
_SAMPLES = 5


def _kind(value: str) -> str:
    low = value.strip().lower()
    if low in ("true", "false", "yes", "no"):
        return "bool"
    for caster, name in ((int, "int"), (float, "float")):
        try:
            caster(low)
            return name
        except ValueError:
            continue
    return "text"


def profile_rows(rows: Iterator[list[str]], limit: int) -> dict[str, Any]:
    """Column types, blanks, duplicates and odd values over at most `limit` data rows. Rows with no
    content at all (blank lines, empty spreadsheet rows) are not data and are skipped, header included."""
    rows = (r for r in rows if any(cell.strip() for cell in r))
    try:
        headers = [h.strip() or f"column{i + 1}" for i, h in enumerate(next(rows))][:MAX_COLUMNS]
    except StopIteration:
        return {"rows": 0, "columns": []}
    kinds: list[Counter[str]] = [Counter() for _ in headers]
    examples: list[dict[str, list[str]]] = [{} for _ in headers]
    blanks = [0] * len(headers)
    seen: set[tuple[str, ...]] = set()
    duplicates = count = 0
    for row in rows:
        if count >= limit:
            break
        count += 1
        key = tuple(row)
        duplicates += key in seen
        seen.add(key)
        for i in range(len(headers)):
            value = row[i].strip() if i < len(row) else ""
            if not value:
                blanks[i] += 1
                continue
            kind = _kind(value)
            kinds[i][kind] += 1
            bucket = examples[i].setdefault(kind, [])
            if len(bucket) < _SAMPLES:
                bucket.append(value[:60])
    columns = []
    for i, name in enumerate(headers):
        dominant = kinds[i].most_common(1)[0][0] if kinds[i] else "empty"
        odd = [v for k, vs in examples[i].items() if k != dominant for v in vs][:_SAMPLES]
        columns.append({"name": name, "type": dominant, "blank": blanks[i], "odd_values": odd})
    return {"rows": count, "row_limit": limit, "duplicate_rows": duplicates, "columns": columns}


def _csv_rows(path: Path) -> Iterator[list[str]]:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        yield from csv.reader(f, dialect)


def _xlsx_rows(path: Path) -> Iterator[list[str]]:
    import openpyxl  # deferred: it is slow to import and only needed here

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = wb.active
        if sheet is not None:
            for row in sheet.iter_rows(values_only=True):
                yield ["" if cell is None else str(cell) for cell in row]
    finally:
        wb.close()


class DataProfileTool(Tool):
    name = "data.profile"

    def __init__(self, scope: PathScope) -> None:
        self._scope = scope

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        path = resolve_in_scope(str_arg(args, "path"), self._scope)
        limit = int_arg(args, "max_rows", DEFAULT_ROWS, lo=1, hi=MAX_ROWS)
        suffix = path.suffix.lower()
        if suffix not in (".csv", ".tsv", ".txt", ".xlsx"):
            raise ValidationFailed("only CSV, TSV and XLSX files can be profiled")
        if not os.path.isfile(path):
            raise ToolError("file not found")
        source = _xlsx_rows if suffix == ".xlsx" else _csv_rows
        try:
            report = await asyncio.to_thread(lambda: profile_rows(source(path), limit))
        except Exception as exc:  # a malformed file can fail inside csv or openpyxl in many ways
            raise ToolError(f"could not read the file: {exc}") from exc
        return ToolResult(json.dumps({"file": path.name, **report}, indent=1), Label.PERSONAL, False)


