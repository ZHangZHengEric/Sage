"""Segment streamed agent text for incremental speech synthesis."""

import re

_STRONG_BREAKS = frozenset("。！？!?；;\n")
_SOFT_BREAKS = frozenset("，,、：:")
_BLOCK_PREFIX = re.compile(r"^ {0,3}(?:#{1,6}|>|[-+*]|\d{1,9}[.)])[ \t]$")
_HORIZONTAL_RULE = re.compile(
    r"^ {0,3}(?P<marker>[-*_])(?:[ \t]*(?P=marker)){2,}[ \t]*\n?$"
)
_TABLE_DIVIDER = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*"
    r"(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*\n?$"
)


class MarkdownSpeechNormalizer:
    """Incrementally project common Markdown into text suitable for speech."""

    def __init__(self) -> None:
        self._reset()

    def push(self, delta: str) -> str:
        """Consume one model delta without waiting for the complete response."""

        output: list[str] = []
        for char in delta:
            if char in {"`", "~"} and (
                not self._in_fenced_code or char == self._fence_marker
            ):
                if self._marker_run and char != self._marker_run:
                    self._finish_marker_run()
                    if self._in_fenced_code and char != self._fence_marker:
                        self._consume(char, output)
                        continue
                self._marker_run = char
                self._marker_count += 1
                continue
            self._finish_marker_run()
            self._consume(char, output)
        return "".join(output)

    def flush(self) -> str:
        """Return pending visible text and reset for the next model response."""

        output: list[str] = []
        self._finish_marker_run()
        if not self._in_fenced_code and not self._skip_fence_line:
            self._flush_line_prefix(output)
            if self._pending_bang:
                output.append("!")
        self._reset()
        return "".join(output)

    def _reset(self) -> None:
        self._at_line_start = True
        self._line_prefix = ""
        self._marker_run = ""
        self._marker_count = 0
        self._fence_marker = ""
        self._in_fenced_code = False
        self._skip_fence_line = False
        self._emit_after_fence = False
        self._link_depth = 0
        self._after_link_label = False
        self._pending_bang = False

    def _finish_marker_run(self) -> None:
        if self._marker_count >= 3 and self._at_line_start:
            if self._in_fenced_code:
                self._in_fenced_code = False
                self._fence_marker = ""
            else:
                self._in_fenced_code = True
                self._fence_marker = self._marker_run
            self._skip_fence_line = True
            self._emit_after_fence = not self._in_fenced_code
            self._line_prefix = ""
        self._marker_run = ""
        self._marker_count = 0

    def _consume(self, char: str, output: list[str]) -> None:
        if self._skip_fence_line:
            if char == "\n":
                if self._emit_after_fence:
                    output.append("\n")
                self._skip_fence_line = False
                self._emit_after_fence = False
                self._at_line_start = True
            return

        if self._in_fenced_code:
            if char == "\n":
                self._at_line_start = True
            elif not char.isspace():
                self._at_line_start = False
            return

        if self._link_depth:
            if char == "(":
                self._link_depth += 1
            elif char == ")":
                self._link_depth -= 1
            return

        if self._after_link_label:
            self._after_link_label = False
            if char == "(":
                self._link_depth = 1
                return

        if self._pending_bang:
            self._pending_bang = False
            if char == "[":
                return
            output.append("!")

        if self._at_line_start:
            self._consume_line_start(char, output)
            return
        self._consume_visible(char, output)

    def _consume_line_start(self, char: str, output: list[str]) -> None:
        self._line_prefix += char
        if char == "\n":
            self._flush_line_prefix(output)
            return
        if _BLOCK_PREFIX.fullmatch(self._line_prefix):
            self._line_prefix = ""
            self._at_line_start = False
            return
        if self._could_be_line_prefix(self._line_prefix):
            return
        self._flush_line_prefix(output)

    def _flush_line_prefix(self, output: list[str]) -> None:
        text = self._line_prefix
        self._line_prefix = ""
        if not text:
            return
        if _HORIZONTAL_RULE.fullmatch(text) or _TABLE_DIVIDER.fullmatch(text):
            if text.endswith("\n"):
                output.append("\n")
                self._at_line_start = True
            return

        self._at_line_start = False
        for char in text:
            self._consume_visible(char, output)

    @staticmethod
    def _could_be_line_prefix(text: str) -> bool:
        leading = len(text) - len(text.lstrip(" "))
        if leading > 3:
            return False
        value = text[leading:]
        if not value:
            return True
        if set(value) <= {"#"}:
            return len(value) <= 6
        if value in {">", "-", "+", "*"}:
            return True
        if value.isdigit():
            return len(value) <= 9
        if value[-1:] in {".", ")"} and value[:-1].isdigit():
            return len(value[:-1]) <= 9
        if set(value) <= {"-", "*", "_", " ", "\t"}:
            return True
        return value.startswith("|") and set(value) <= {"|", ":", "-", " ", "\t"}

    def _consume_visible(self, char: str, output: list[str]) -> None:
        if char == "\n":
            output.append(char)
            self._at_line_start = True
            return
        if char == "!":
            self._pending_bang = True
            return
        if char == "[":
            return
        if char == "]":
            self._after_link_label = True
            return
        if char in {"*", "~"}:
            return
        if char == "_":
            output.append(" ")
            return
        if char == "|":
            output.append("，")
            return
        output.append(char)


class TextSegmenter:
    """Collect text deltas into chunks suitable for streaming TTS."""

    def __init__(
        self,
        *,
        first_chunk_chars: int = 6,
        chunk_chars: int = 24,
    ) -> None:
        """Configure the first and subsequent hard chunk limits."""

        if first_chunk_chars <= 0:
            raise ValueError("first_chunk_chars must be greater than zero")
        if chunk_chars <= 0:
            raise ValueError("chunk_chars must be greater than zero")

        self._first_chunk_chars = first_chunk_chars
        self._chunk_chars = chunk_chars
        self._limit = first_chunk_chars
        self._buffer = ""

    def push(self, delta: str) -> list[str]:
        """Append one text delta and return chunks ready for synthesis."""

        self._buffer += delta
        chunks: list[str] = []

        while self._buffer:
            end = self._break_index()
            if end is None:
                break

            text = self._take(end)
            if text:
                chunks.append(text)
                self._limit = self._chunk_chars

        return chunks

    def flush(self) -> str | None:
        """Return remaining text and prepare for a new response."""

        text = self._take(len(self._buffer))
        self._limit = self._first_chunk_chars
        return text or None

    def reset(self) -> None:
        """Discard remaining text and prepare for a new response."""

        self._buffer = ""
        self._limit = self._first_chunk_chars

    def _break_index(self) -> int | None:
        for index, char in enumerate(self._buffer[: self._limit]):
            end = index + 1
            if char in _STRONG_BREAKS:
                return end
            if char in _SOFT_BREAKS and end >= 3:
                return end

        if len(self._buffer) >= self._limit:
            return self._limit
        return None

    def _take(self, end: int) -> str:
        text = self._buffer[:end].strip()
        self._buffer = self._buffer[end:]
        return text


class StreamingTextProcessor:
    """Normalize and segment streamed text for incremental speech synthesis."""

    def __init__(
        self,
        *,
        normalize_markdown: bool = True,
        first_chunk_chars: int = 6,
        chunk_chars: int = 24,
    ) -> None:
        """Configure streamed text normalization and chunk limits."""

        self._normalize_markdown = normalize_markdown
        self._normalizer = (
            MarkdownSpeechNormalizer() if normalize_markdown else None
        )
        self._segmenter = TextSegmenter(
            first_chunk_chars=first_chunk_chars,
            chunk_chars=chunk_chars,
        )

    def push(self, delta: str) -> list[str]:
        """Consume one text delta and return chunks ready for synthesis."""

        if self._normalizer is not None:
            delta = self._normalizer.push(delta)
        return self._segmenter.push(delta)

    def flush(self) -> list[str]:
        """Return remaining chunks and prepare for a new response."""

        chunks: list[str] = []
        if self._normalizer is not None:
            normalized = self._normalizer.flush()
            if normalized:
                chunks.extend(self._segmenter.push(normalized))

        remaining = self._segmenter.flush()
        if remaining:
            chunks.append(remaining)
        return chunks

    def reset(self) -> None:
        """Discard pending text and prepare for a new response."""

        self._normalizer = (
            MarkdownSpeechNormalizer() if self._normalize_markdown else None
        )
        self._segmenter.reset()
