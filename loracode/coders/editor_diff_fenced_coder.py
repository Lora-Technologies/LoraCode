from .editblock_fenced_coder import EditBlockFencedCoder
from .editor_diff_fenced_prompts import EditorDiffFencedPrompts


class EditorDiffFencedCoder(EditBlockFencedCoder):
    edit_format = "editor-diff-fenced"
    gpt_prompts = EditorDiffFencedPrompts()
