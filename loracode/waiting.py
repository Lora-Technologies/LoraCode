#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import threading
import time
from enum import Enum
from typing import Optional

from rich.console import Console


class SpinnerStyle(Enum):
    DOTS = "dots"
    PULSE = "pulse"
    STAR = "star"
    ARROW = "arrow"
    BOUNCE = "bounce"
    SIMPLE = "simple"


SPINNER_FRAMES = {
    SpinnerStyle.DOTS: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
    SpinnerStyle.PULSE: ["◐", "◓", "◑", "◒"],
    SpinnerStyle.STAR: ["✦", "✧", "✦", "✧"],
    SpinnerStyle.ARROW: ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
    SpinnerStyle.BOUNCE: ["⠁", "⠂", "⠄", "⠂"],
    SpinnerStyle.SIMPLE: ["-", "\\", "|", "/"],
}

THINKING_FRAMES = [
    "●    ",
    "●●   ",
    "●●●  ",
    "●●●● ",
    "●●●●●",
    " ●●●●",
    "  ●●●",
    "   ●●",
    "    ●",
    "     ",
]

AGENT_ICONS = {
    "thinking": "◆",
    "analyzing": "◇",
    "writing": "+",
    "reading": "○",
    "searching": "◎",
    "running": "▶",
    "success": "+",
    "error": "x",
    "warning": "!",
    "info": "*",
}


class Spinner:
    last_frame_idx = 0

    def __init__(
        self, 
        text: str, 
        style: SpinnerStyle = SpinnerStyle.DOTS,
        color: str = "#E8912D",
        text_color: str = "#808080",
    ):
        self.text = text
        self.style = style
        self.color = color
        self.text_color = text_color
        self.start_time = time.time()
        self.last_update = 0.0
        self.visible = False
        self.is_tty = sys.stdout.isatty()
        self.console = Console()

        unicode_frames = SPINNER_FRAMES.get(style, SPINNER_FRAMES[SpinnerStyle.DOTS])
        ascii_frames = SPINNER_FRAMES[SpinnerStyle.SIMPLE]

        if self._supports_unicode():
            self.frames = unicode_frames
        else:
            self.frames = ascii_frames

        self.frame_idx = Spinner.last_frame_idx % len(self.frames)
        self.last_display_len = 0

    def _supports_unicode(self) -> bool:
        if not self.is_tty:
            return False
        try:
            test_char = "⠋"
            out = test_char
            out += "\b" * len(test_char)
            out += " " * len(test_char)
            out += "\b" * len(test_char)
            sys.stdout.write(out)
            sys.stdout.flush()
            return True
        except UnicodeEncodeError:
            return False
        except Exception:
            return False

    def _next_frame(self) -> str:
        frame = self.frames[self.frame_idx]
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        Spinner.last_frame_idx = self.frame_idx
        return frame

    def step(self, text: str = None) -> None:
        if text is not None:
            self.text = text

        if not self.is_tty:
            return

        now = time.time()
        if not self.visible and now - self.start_time >= 0.3:
            self.visible = True
            self.last_update = 0.0
            if self.is_tty:
                self.console.show_cursor(False)

        if not self.visible or now - self.last_update < 0.08:
            return

        self.last_update = now
        frame_str = self._next_frame()

        max_spinner_width = self.console.width - 2
        if max_spinner_width < 0:
            max_spinner_width = 0

        line_to_display = f"\033[38;2;232;145;45m{frame_str}\033[0m \033[38;5;245m{self.text}\033[0m"
        display_len = len(frame_str) + 1 + len(self.text)

        if display_len > max_spinner_width:
            visible_text = self.text[:max_spinner_width - 2]
            line_to_display = f"\033[38;2;232;145;45m{frame_str}\033[0m \033[38;5;245m{visible_text}\033[0m"
            display_len = len(frame_str) + 1 + len(visible_text)

        padding_to_clear = " " * max(0, self.last_display_len - display_len)

        sys.stdout.write(f"\r{line_to_display}{padding_to_clear}")
        self.last_display_len = display_len
        sys.stdout.flush()

    def end(self) -> None:
        if self.visible and self.is_tty:
            clear_len = self.last_display_len + 20
            sys.stdout.write("\r" + " " * clear_len + "\r")
            sys.stdout.flush()
            self.console.show_cursor(True)
        self.visible = False


class ThinkingIndicator:
    def __init__(
        self, 
        text: str = "Thinking...",
        show_elapsed: bool = True,
        color: str = "#E8912D",
    ):
        self.text = text
        self.show_elapsed = show_elapsed
        self.color = color
        self.start_time = time.time()
        self.last_update = 0.0
        self.visible = False
        self.is_tty = sys.stdout.isatty()
        self.console = Console()
        self.frame_idx = 0
        self.last_display_len = 0
        
        if self._supports_unicode():
            self.frames = THINKING_FRAMES
            self.icon = "◆"
        else:
            self.frames = [".", "..", "...", "....", ".....", "....", "...", "..", "."]
            self.icon = "*"

    def _supports_unicode(self) -> bool:
        if not self.is_tty:
            return False
        try:
            sys.stdout.write("◆\b \b")
            sys.stdout.flush()
            return True
        except:
            return False

    def _format_elapsed(self) -> str:
        elapsed = time.time() - self.start_time
        if elapsed < 60:
            return f"{elapsed:.0f}s"
        else:
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            return f"{mins}m{secs}s"

    def step(self, text: str = None) -> None:
        if text is not None:
            self.text = text

        if not self.is_tty:
            return

        now = time.time()
        if not self.visible and now - self.start_time >= 0.2:
            self.visible = True
            self.last_update = 0.0
            self.console.show_cursor(False)

        if not self.visible or now - self.last_update < 0.1:
            return

        self.last_update = now
        
        frame = self.frames[self.frame_idx]
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)

        elapsed_str = f" ({self._format_elapsed()})" if self.show_elapsed else ""
        
        line = f"\033[38;2;232;145;45m{self.icon}\033[0m \033[38;5;245m{self.text}{elapsed_str}\033[0m"
        display_len = len(self.icon) + 1 + len(self.text) + len(elapsed_str)

        padding = " " * max(0, self.last_display_len - display_len)
        sys.stdout.write(f"\r{line}{padding}")
        self.last_display_len = display_len
        sys.stdout.flush()

    def end(self, final_text: str = None) -> None:
        if self.visible and self.is_tty:
            if final_text:
                elapsed_str = f" ({self._format_elapsed()})" if self.show_elapsed else ""
                line = f"\033[38;2;78;201;176m+\033[0m \033[38;5;245m{final_text}{elapsed_str}\033[0m"
                padding = " " * max(0, self.last_display_len - len(final_text) - 10)
                sys.stdout.write(f"\r{line}{padding}\n")
            else:
                clear_len = self.last_display_len + 20
                sys.stdout.write("\r" + " " * clear_len + "\r")
            sys.stdout.flush()
            self.console.show_cursor(True)
        self.visible = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end()


class AgentSpinner:
    def __init__(
        self,
        text: str = "Working...",
        action: str = "thinking",
    ):
        self.text = text
        self.action = action
        self.start_time = time.time()
        self.last_update = 0.0
        self.visible = False
        self.is_tty = sys.stdout.isatty()
        self.console = Console()
        self.frame_idx = 0
        self.last_display_len = 0
        
        if self._supports_unicode():
            self.frames = SPINNER_FRAMES[SpinnerStyle.DOTS]
        else:
            self.frames = SPINNER_FRAMES[SpinnerStyle.SIMPLE]

    def _supports_unicode(self) -> bool:
        if not self.is_tty:
            return False
        try:
            sys.stdout.write("◆\b \b")
            sys.stdout.flush()
            return True
        except:
            return False

    def _get_icon(self) -> str:
        return AGENT_ICONS.get(self.action, AGENT_ICONS["thinking"])

    def set_action(self, action: str, text: str = None):
        self.action = action
        if text:
            self.text = text

    def step(self, text: str = None) -> None:
        if text is not None:
            self.text = text

        if not self.is_tty:
            return

        now = time.time()
        if not self.visible and now - self.start_time >= 0.3:
            self.visible = True
            self.last_update = 0.0
            self.console.show_cursor(False)

        if not self.visible or now - self.last_update < 0.08:
            return

        self.last_update = now
        
        frame = self.frames[self.frame_idx]
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        icon = self._get_icon()

        line = f"\033[38;2;232;145;45m{icon} {frame}\033[0m \033[38;5;245m{self.text}\033[0m"
        display_len = len(icon) + 1 + len(frame) + 1 + len(self.text)

        padding = " " * max(0, self.last_display_len - display_len)
        sys.stdout.write(f"\r{line}{padding}")
        self.last_display_len = display_len
        sys.stdout.flush()

    def end(self, success: bool = True, message: str = None) -> None:
        if self.visible and self.is_tty:
            if message:
                icon = "+" if success else "x"
                color = "\033[38;2;78;201;176m" if success else "\033[38;2;244;71;71m"
                line = f"{color}{icon}\033[0m \033[38;5;245m{message}\033[0m"
                padding = " " * max(0, self.last_display_len - len(message) - 5)
                sys.stdout.write(f"\r{line}{padding}\n")
            else:
                clear_len = self.last_display_len + 20
                sys.stdout.write("\r" + " " * clear_len + "\r")
            sys.stdout.flush()
            self.console.show_cursor(True)
        self.visible = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end(success=exc_type is None)


class WaitingSpinner:
    def __init__(
        self, 
        text: str = "Waiting for LLM", 
        delay: float = 0.1,
        style: SpinnerStyle = SpinnerStyle.DOTS,
    ):
        self.spinner = Spinner(text, style=style)
        self.delay = delay
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._text = text

    def _spin(self):
        while not self._stop_event.is_set():
            self.spinner.step()
            time.sleep(self.delay)
        self.spinner.end()

    def update_text(self, text: str):
        self._text = text
        self.spinner.text = text

    def start(self):
        if not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self.delay * 2)
        self.spinner.end()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class StatusLine:
    def __init__(self):
        self.is_tty = sys.stdout.isatty()
        self.console = Console()
        self.last_len = 0
        self.start_time = None
        
    def _supports_unicode(self) -> bool:
        try:
            sys.stdout.write("◆\b \b")
            sys.stdout.flush()
            return True
        except:
            return False

    def show(self, text: str, icon: str = "+", color: str = "#E8912D"):
        if not self.is_tty:
            print(f"{icon} {text}")
            return
            
        if self.start_time is None:
            self.start_time = time.time()
            
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        
        line = f"\033[38;2;{r};{g};{b}m{icon}\033[0m \033[38;5;245m{text}\033[0m"
        display_len = len(icon) + 1 + len(text)
        
        padding = " " * max(0, self.last_len - display_len)
        sys.stdout.write(f"\r{line}{padding}")
        sys.stdout.flush()
        self.last_len = display_len

    def clear(self):
        if self.is_tty:
            sys.stdout.write("\r" + " " * (self.last_len + 10) + "\r")
            sys.stdout.flush()
        self.last_len = 0
        self.start_time = None

    def done(self, text: str, success: bool = True):
        icon = "+" if success else "x"
        color = "#4EC9B0" if success else "#F44747"
        self.show(text, icon, color)
        if self.is_tty:
            print()
        self.last_len = 0
        self.start_time = None


def main():
    print("Testing spinners...\n")
    
    print("Basic spinner:")
    spinner = Spinner("Loading data...")
    try:
        for _ in range(30):
            time.sleep(0.1)
            spinner.step()
    finally:
        spinner.end()
    print("Done!\n")
    
    print("Thinking indicator:")
    thinking = ThinkingIndicator("Analyzing code...")
    try:
        for _ in range(30):
            time.sleep(0.1)
            thinking.step()
    finally:
        thinking.end("Analysis complete")
    
    print("\nAgent spinner:")
    agent = AgentSpinner("Reading files...", action="reading")
    try:
        for i in range(20):
            time.sleep(0.1)
            agent.step()
        agent.set_action("writing", "Writing changes...")
        for i in range(20):
            time.sleep(0.1)
            agent.step()
    finally:
        agent.end(success=True, message="Changes applied")
    
    print("\nAll tests complete!")


if __name__ == "__main__":
    main()
