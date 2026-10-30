"""Offline HTML5 and CSS syntax diagnostics, without executing submitted code.

These checks do not validate visual appearance, accessibility, CSS property values,
JavaScript, or linked resources. Browser error recovery is not proof of validity.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re


def _diagnostic(path, line, column, code, message, source):
    return dict(path=path, line=line, column=column, code=code,
                message=message, source=source, severity='error')


def _delimiters(text):
    """Report delimiters that CSS tokenization silently repairs at EOF."""
    stack = []
    i, size = 0, len(text)
    while i < size:
        start = i
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                yield i, 'Unclosed CSS comment'
                break
            i = end + 2
            continue
        if text[i] == '\\':
            match = re.match(r'\\(?:[0-9a-fA-F]{1,6}\s?|.)', text[i:], re.S)
            i += len(match[0]) if match else 1
            continue
        if text[i] in "\"'":
            quote = text[i]
            i += 1
            while i < size:
                if text[i] == '\\':
                    i += 2
                elif text[i] == quote:
                    i += 1
                    break
                elif text[i] in '\n\r\f':
                    yield start, 'Unterminated CSS string'
                    break
                else:
                    i += 1
            else:
                yield start, 'Unterminated CSS string'
            continue
        # Unquoted URL tokens may legally contain braces and brackets.
        match = re.match(r'url\(\s*', text[i:], re.I)
        if match and i + len(match[0]) < size and text[i + len(match[0])] not in "\"'":
            i += len(match[0])
            while i < size and text[i] != ')':
                i += 2 if text[i] == '\\' else 1
            if i == size:
                yield start, 'Unclosed CSS url()'
            i += 1
            continue
        char = text[i]
        if char in '{([':
            stack.append((char, i))
        elif char in '})]':
            if stack and stack[-1][0] == {'}': '{', ')': '(', ']': '['}[char]:
                stack.pop()
            else:
                yield i, f'Unexpected closing {char}'
        i += 1
    for char, index in stack:
        yield index, f'Unclosed {char}; missing ' + {'{': '}', '(': ')', '[': ']'}[char]


def css_diagnostics(text, path, *, line=1, column=1, declarations=False):
    import tinycss2
    diagnostics = []

    def add(row, col, code, message):
        diagnostics.append(_diagnostic(path, line + row - 1,
            col + (column - 1 if row == 1 else 0), code, message, 'css-syntax'))

    for index, message in _delimiters(text):
        row = text.count('\n', 0, index) + 1
        col = index - text.rfind('\n', 0, index)
        add(row, col, 'unbalanced-syntax', message)

    def tokens(values):
        for value in values:
            if value.type == 'error':
                add(value.source_line, value.source_column, value.kind, value.message)
            for attr in ('arguments', 'content'):
                if getattr(value, attr, None) is not None:
                    tokens(getattr(value, attr))

    def rules(values):
        for value in values:
            if value.type == 'error':
                add(value.source_line, value.source_column, value.kind, value.message)
            elif value.type in ('qualified-rule', 'at-rule'):
                tokens(value.prelude)
                if value.content is not None:
                    rules(tinycss2.parse_blocks_contents(value.content, skip_comments=True, skip_whitespace=True))
            elif value.type == 'declaration':
                tokens(value.value)

    parse = tinycss2.parse_declaration_list if declarations else tinycss2.parse_stylesheet
    rules(parse(text, skip_comments=True, skip_whitespace=True))
    return diagnostics


def html_diagnostics(text, path):
    import html5lib
    from html5lib.constants import E
    parser = html5lib.HTMLParser()
    parser.parse(text)
    diagnostics = []
    for (line, column), code, values in parser.errors:
        message = E.get(code, code)
        try:
            message = message % values
        except (KeyError, TypeError, ValueError):
            pass
        diagnostics.append(_diagnostic(path, line, max(1, column), code, message, 'html5'))

    class Styles(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_style = False

        def handle_starttag(self, tag, attrs):
            if tag == 'style':
                style_type = dict(attrs).get('type')
                self.in_style = style_type in (None, '', 'text/css')
            for key, value in attrs:
                if key == 'style' and value is not None:
                    row, col = self.getpos()
                    diagnostics.extend(css_diagnostics(value, path, line=row,
                        column=col + 1, declarations=True))

        def handle_endtag(self, tag):
            if tag == 'style':
                self.in_style = False

        def handle_data(self, value):
            if self.in_style:
                row, col = self.getpos()
                diagnostics.extend(css_diagnostics(value, path, line=row, column=col + 1))

    styles = Styles()
    styles.feed(text)
    styles.close()
    return diagnostics
