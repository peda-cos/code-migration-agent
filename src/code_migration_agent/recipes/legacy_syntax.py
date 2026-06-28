"""Stage-0 normalization for Python 2 syntax that libcst cannot parse.

Only files that fail ``ast.parse`` are touched. Edits are derived from token
positions, so string literals and comments are never rewritten.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from typing import Callable, Sequence

_PRINT_FIRST_OPS = {"-", "+", "~", ">>", "[", "{"}
_NUMBER_OCTAL = re.compile(r"0[0-7]+$")


@dataclass(frozen=True)
class LegacyEdit:
    rule: str
    line: int
    before: str
    after: str


@dataclass(frozen=True)
class LegacyResult:
    module_code: str
    edits: list[LegacyEdit]


@dataclass(frozen=True)
class _CodeLine:
    line_no: int
    tokens: list[tokenize.TokenInfo]
    stmt_start: bool
    text: str
    newline: str


def normalize_source(source: str, filename: str = "<memory>") -> LegacyResult:
    """Return normalized code plus a record of each mechanical rewrite."""
    try:
        ast.parse(source, filename=filename)
    except (SyntaxError, ValueError):
        pass
    else:
        return LegacyResult(module_code=source, edits=[])

    current = source
    edits: list[LegacyEdit] = []
    for _rule_id, rewriter in _RULES:
        if _parses(current, filename):
            break
        try:
            updated, rule_edits = rewriter(current, filename)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            break
        if updated != current:
            current = updated
            edits.extend(rule_edits)
    return LegacyResult(module_code=current, edits=edits)


def _parses(source: str, filename: str) -> bool:
    try:
        ast.parse(source, filename=filename)
    except (SyntaxError, ValueError):
        return False
    return True


def _tokenize(source: str) -> list[tokenize.TokenInfo]:
    return list(tokenize.generate_tokens(io.StringIO(source).readline))


def _code_lines(source: str) -> list[_CodeLine]:
    tokens = _tokenize(source)
    raw_lines = source.splitlines(keepends=True)
    by_line: dict[int, list[tokenize.TokenInfo]] = {}
    starts: dict[int, bool] = {}
    boundary = True
    depth = 0
    for token in tokens:
        if token.type == tokenize.NEWLINE:
            boundary = True
            continue
        if token.type in {tokenize.NL, tokenize.INDENT, tokenize.DEDENT}:
            continue
        if token.type == tokenize.ENCODING:
            continue
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.ENDMARKER:
            continue
        line_no = token.start[0]
        by_line.setdefault(line_no, []).append(token)
        if boundary and depth == 0:
            starts.setdefault(line_no, True)
        boundary = False
        if token.string in "([{":
            depth += 1
        elif token.string in ")]}":
            depth = max(0, depth - 1)
        elif token.string == ";" and depth == 0:
            boundary = True

    lines: list[_CodeLine] = []
    for line_no in sorted(by_line):
        code = by_line[line_no]
        if any(tok.start[0] != tok.end[0] for tok in code):
            continue
        raw = raw_lines[line_no - 1] if line_no - 1 < len(raw_lines) else ""
        if raw.endswith("\r\n"):
            text, newline = raw[:-2], "\r\n"
        elif raw.endswith("\n"):
            text, newline = raw[:-1], "\n"
        else:
            text, newline = raw, ""
        lines.append(
            _CodeLine(
                line_no=line_no,
                tokens=code,
                stmt_start=starts.get(line_no, False),
                text=text,
                newline=newline,
            )
        )
    return lines


def _top_level_commas(tokens: Sequence[tokenize.TokenInfo]) -> list[tokenize.TokenInfo]:
    depth = 0
    result: list[tokenize.TokenInfo] = []
    for token in tokens:
        if token.string in "([{":
            depth += 1
        elif token.string in ")]}":
            depth = max(0, depth - 1)
        elif token.string == "," and depth == 0:
            result.append(token)
    return result


def _apply_spans(
    text: str, spans: Sequence[tuple[int, int, str]]
) -> tuple[str, list[tuple[int, int, str]]]:
    ordered = sorted(spans, key=lambda item: (item[0], item[1]), reverse=True)
    pieces = text
    applied: list[tuple[int, int, str]] = []
    previous_start = len(text) + 1
    for start, end, replacement in ordered:
        if end > previous_start:
            continue  # overlapping edits are skipped rather than corrupted
        pieces = pieces[:start] + replacement + pieces[end:]
        applied.append((start, end, replacement))
        previous_start = start
    applied.reverse()
    return pieces, applied


def _line_edit(
    line: _CodeLine, spans: Sequence[tuple[int, int, str]]
) -> tuple[str, LegacyEdit] | None:
    if not spans:
        return None
    updated, applied = _apply_spans(line.text, spans)
    if not applied:
        return None
    after = updated
    before = line.text
    edit = LegacyEdit(rule="", line=line.line_no, before=before, after=after)
    return updated + line.newline, edit


def _replace_lines(
    source: str, edits_by_line: dict[int, list[tuple[int, int, str]]], rule: str
) -> tuple[str, list[LegacyEdit]]:
    lines = _code_lines(source)
    raw = source.splitlines(keepends=True)
    replacements: dict[int, str] = {}
    records: list[LegacyEdit] = []
    for line in lines:
        if line.line_no not in edits_by_line:
            continue
        result = _line_edit(line, edits_by_line[line.line_no])
        if result is None:
            continue
        new_text, edit = result
        replacements[line.line_no] = new_text
        records.append(
            LegacyEdit(
                rule=rule, line=edit.line, before=edit.before, after=edit.after.rstrip("\r\n")
            )
        )
    if not replacements:
        return source, []
    for line_no, text in replacements.items():
        raw[line_no - 1] = text
    return "".join(raw), records


def _rewrite_print(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        toks = line.tokens
        if not line.stmt_start or not toks:
            continue
        first = toks[0]
        if first.type != tokenize.NAME or first.string != "print":
            continue
        if any(tok.string == ";" for tok in toks):
            continue
        rest = toks[1:]
        if not rest:
            replacement = "print()"
            edits[line.line_no] = [
                (first.start[1], toks[-1].end[1], replacement)
            ]
            continue
        nxt = rest[0]
        if not (
            nxt.type in {tokenize.NAME, tokenize.NUMBER, tokenize.STRING}
            or nxt.type == getattr(tokenize, "FSTRING_START", -1)
            or nxt.string in _PRINT_FIRST_OPS
        ):
            continue
        end_col = toks[-1].end[1]
        args = line.text[first.end[1] : end_col].strip()
        if nxt.string == ">>":
            commas = _top_level_commas(rest[1:])
            comma = next((item for item in commas if item.start[1] <= end_col), None)
            if comma is None:
                stream = line.text[nxt.end[1] : end_col].strip()
                replacement = f"print(file={stream})" if stream else "print()"
            else:
                stream = line.text[nxt.end[1] : comma.start[1]].strip()
                value = line.text[comma.end[1] : end_col].strip()
                replacement = (
                    f"print({value}, file={stream})" if value else f"print(file={stream})"
                )
        else:
            replacement = f"print({args})"
        edits[line.line_no] = [(first.start[1], end_col, replacement)]
    return _replace_lines(source, edits, "print_stmt")


def _rewrite_except(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        toks = line.tokens
        if not line.stmt_start or not toks:
            continue
        if toks[0].type != tokenize.NAME or toks[0].string != "except":
            continue
        colon = next(
            (tok for tok in toks if tok.string == ":"
             and _depth_before(toks, tok) == 0),
            None,
        )
        if colon is None:
            continue
        commas = [
            tok
            for tok in _top_level_commas(toks[1:])
            if tok.start[1] < colon.start[1]
        ]
        if len(commas) != 1:
            continue
        if any(tok.type == tokenize.NAME and tok.string == "as" for tok in toks):
            continue
        comma = commas[0]
        end = comma.end[1]
        while end < len(line.text) and line.text[end] in " \t":
            end += 1
        edits[line.line_no] = [(comma.start[1], end, " as ")]
    return _replace_lines(source, edits, "except_comma")


def _depth_before(tokens: Sequence[tokenize.TokenInfo], target: tokenize.TokenInfo) -> int:
    depth = 0
    for token in tokens:
        if token is target:
            return depth
        if token.string in "([{":
            depth += 1
        elif token.string in ")]}":
            depth = max(0, depth - 1)
    return depth


def _rewrite_raise(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        toks = line.tokens
        if not line.stmt_start or not toks:
            continue
        if toks[0].type != tokenize.NAME or toks[0].string != "raise":
            continue
        if any(tok.string == ";" for tok in toks):
            continue
        commas = _top_level_commas(toks[1:])
        if len(commas) != 1:
            continue
        if any(tok.type == tokenize.NAME and tok.string == "from" for tok in toks):
            continue
        comma = commas[0]
        end_col = toks[-1].end[1]
        exc = line.text[toks[0].end[1] : comma.start[1]].strip()
        arg = line.text[comma.end[1] : end_col].strip()
        if not exc or not arg:
            continue
        replacement = f"raise {exc}({arg})"
        edits[line.line_no] = [(toks[0].start[1], end_col, replacement)]
    return _replace_lines(source, edits, "raise_comma")


def _rewrite_exec(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        toks = line.tokens
        if not line.stmt_start or not toks:
            continue
        if toks[0].type != tokenize.NAME or toks[0].string != "exec":
            continue
        if len(toks) != 2:
            continue
        value = toks[1]
        if value.type != tokenize.STRING:
            continue
        replacement = f"exec({line.text[value.start[1] : value.end[1]]})"
        edits[line.line_no] = [(toks[0].start[1], value.end[1], replacement)]
    return _replace_lines(source, edits, "exec_stmt")


def _rewrite_backticks(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        ticks = [tok for tok in line.tokens if tok.string == "`"]
        if not ticks or len(ticks) % 2:
            continue
        spans: list[tuple[int, int, str]] = []
        for index, tick in enumerate(ticks):
            spans.append(
                (tick.start[1], tick.end[1], "repr(" if index % 2 == 0 else ")")
            )
        edits[line.line_no] = spans
    return _replace_lines(source, edits, "backticks")


def _rewrite_not_equal(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        spans: list[tuple[int, int, str]] = []
        for first, second in zip(line.tokens, line.tokens[1:]):
            if (
                first.string == "<"
                and second.string == ">"
                and first.end[1] == second.start[1]
            ):
                spans.append((first.start[1], second.end[1], "!="))
        if spans:
            edits[line.line_no] = spans
    return _replace_lines(source, edits, "ne_operator")


def _rewrite_octal(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        spans: list[tuple[int, int, str]] = []
        for tok in line.tokens:
            if tok.type != tokenize.NUMBER:
                continue
            value = tok.string
            if (
                len(value) > 1
                and _NUMBER_OCTAL.fullmatch(value)
                and any(ch != "0" for ch in value)
            ):
                start = tok.start[1]
                spans.append((start, start + 1, "0o"))
        if spans:
            edits[line.line_no] = spans
    return _replace_lines(source, edits, "octal")


def _rewrite_long_suffix(source: str, filename: str) -> tuple[str, list[LegacyEdit]]:
    del filename
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for line in _code_lines(source):
        spans: list[tuple[int, int, str]] = []
        for first, second in zip(line.tokens, line.tokens[1:]):
            if (
                first.type == tokenize.NUMBER
                and second.type == tokenize.NAME
                and second.string == "L"
                and first.end[1] == second.start[1]
            ):
                spans.append((second.start[1], second.end[1], ""))
        if spans:
            edits[line.line_no] = spans
    return _replace_lines(source, edits, "long_suffix")


_RULES: tuple[
    tuple[str, Callable[[str, str], tuple[str, list[LegacyEdit]]]], ...
] = (
    ("backticks", _rewrite_backticks),
    ("ne_operator", _rewrite_not_equal),
    ("octal", _rewrite_octal),
    ("long_suffix", _rewrite_long_suffix),
    ("print_stmt", _rewrite_print),
    ("except_comma", _rewrite_except),
    ("raise_comma", _rewrite_raise),
    ("exec_stmt", _rewrite_exec),
)
