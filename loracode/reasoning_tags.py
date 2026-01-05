#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re

from loracode.dump import dump  # noqa

REASONING_TAG = "thinking-content-" + "7bbeb8e1441453ad999a0bbba8a46d4b"
REASONING_START = "--------------\n► **THINKING**"
REASONING_END = "------------\n► **ANSWER**"


def remove_reasoning_content(res, reasoning_tag):
    if not reasoning_tag:
        return res

    pattern = f"<{reasoning_tag}>.*?</{reasoning_tag}>"
    res = re.sub(pattern, "", res, flags=re.DOTALL).strip()

    closing_tag = f"</{reasoning_tag}>"
    if closing_tag in res:
        parts = res.split(closing_tag, 1)
        res = parts[1].strip() if len(parts) > 1 else res

    return res


def replace_reasoning_tags(text, tag_name):
    if not text:
        return text

    text = re.sub(f"\\s*<{tag_name}>\\s*", f"\n{REASONING_START}\n\n", text)

    text = re.sub(f"\\s*</{tag_name}>\\s*", f"\n\n{REASONING_END}\n\n", text)

    return text


def format_reasoning_content(reasoning_content, tag_name):
    if not reasoning_content:
        return ""

    formatted = f"<{tag_name}>\n\n{reasoning_content}\n\n</{tag_name}>"
    return formatted
