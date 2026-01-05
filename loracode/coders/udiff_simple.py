from .udiff_coder import UnifiedDiffCoder
from .udiff_simple_prompts import UnifiedDiffSimplePrompts


class UnifiedDiffSimpleCoder(UnifiedDiffCoder):
    edit_format = "udiff-simple"

    gpt_prompts = UnifiedDiffSimplePrompts()
