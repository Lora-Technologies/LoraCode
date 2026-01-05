#!/usr/bin/env python

import io
import time
from rich import box
from rich.console import Console
from rich.live import Live
from rich.markdown import CodeBlock, Heading, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from loracode.dump import dump

_text_prefix = """
# Header

Lorem Ipsum is simply dummy text of the printing and typesetting industry.
Lorem Ipsum has been the industry's standard dummy text ever since the 1500s,
when an unknown printer took a galley of type and scrambled it to make a type
specimen book. It has survived not only five centuries, but also the leap into
electronic typesetting, remaining essentially unchanged. It was popularised in
the 1960s with the release of Letraset sheets containing Lorem Ipsum passages,
and more recently with desktop publishing software like Aldus PageMaker
including versions of Lorem Ipsum.



## Sub header

- List 1
- List 2
- List me
- List you



```python
"""

_text_suffix = """
```

## Sub header too

The end.

"""


class NoInsetCodeBlock(CodeBlock):

    def __rich_console__(self, console, options):
        code = str(self.text).rstrip()
        syntax = Syntax(
            code, 
            self.lexer_name, 
            theme=self.theme, 
            word_wrap=True, 
            padding=(1, 2),
            background_color="#1E1E1E"
        )
        yield syntax


class LeftHeading(Heading):
    def __rich_console__(self, console, options):
        text = self.text
        text.justify = "left"
        if self.tag == "h1":
            yield Panel(
                text,
                box=box.ROUNDED,
                style="bold #D4D4D4",
                border_style="#3C3C3C",
                padding=(0, 1),
            )
        else:
            if self.tag == "h2":
                yield Text("")
            yield text


class NoInsetMarkdown(Markdown):

    elements = {
        **Markdown.elements,
        "fence": NoInsetCodeBlock,
        "code_block": NoInsetCodeBlock,
        "heading_open": LeftHeading,
    }


class MarkdownStream:

    live = None
    when = 0
    min_delay = 1.0 / 20
    live_window = 6

    def __init__(self, mdargs=None):
        """Initialize the markdown stream.

        Args:
            mdargs (dict, optional): Additional arguments to pass to rich Markdown renderer
        """
        self.printed = []

        if mdargs:
            self.mdargs = mdargs
        else:
            self.mdargs = dict()

        self.live = None
        self._live_started = False

    def _render_markdown_to_lines(self, text):
        string_io = io.StringIO()
        console = Console(file=string_io, force_terminal=True)
        markdown = NoInsetMarkdown(text, **self.mdargs)
        console.print(markdown)
        output = string_io.getvalue()

        return output.splitlines(keepends=True)

    def __del__(self):
        if self.live:
            try:
                self.live.stop()
            except Exception:
                pass

    def update(self, text, final=False):
        if not getattr(self, "_live_started", False):
            self.live = Live(Text(""), refresh_per_second=1.0 / self.min_delay)
            self.live.start()
            self._live_started = True

        now = time.time()
        if not final and now - self.when < self.min_delay:
            return
        self.when = now

        start = time.time()
        lines = self._render_markdown_to_lines(text)
        render_time = time.time() - start

        self.min_delay = min(max(render_time * 10, 1.0 / 20), 2)

        num_lines = len(lines)

        if not final:
            num_lines -= self.live_window

        if final or num_lines > 0:
            num_printed = len(self.printed)
            show = num_lines - num_printed

            if show <= 0:
                return

            show = lines[num_printed:num_lines]
            show = "".join(show)
            show = Text.from_ansi(show)
            self.live.console.print(show)

            self.printed = lines[:num_lines]

        if final:
            self.live.update(Text(""))
            self.live.stop()
            self.live = None
            return

        rest = lines[num_lines:]
        rest = "".join(rest)
        rest = Text.from_ansi(rest)
        self.live.update(rest)

    def find_minimal_suffix(self, text, match_lines=50):
        """Find minimal suffix for incremental rendering."""
        pass


if __name__ == "__main__":
    with open("loracode/io.py", "r") as f:
        code = f.read()
    _text = _text_prefix + code + _text_suffix
    _text = _text * 10

    pm = MarkdownStream()
    print("Using NoInsetMarkdown for code blocks with padding=0")
    for i in range(6, len(_text), 5):
        pm.update(_text[:i])
        time.sleep(0.01)

    pm.update(_text, final=True)
