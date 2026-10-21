"""
packages/providers/fence.py — R18 (docs/contracts.md): untrusted text (scraped pages, rows written from them, model
answers) reaches a prompt only inside <tag>…</tag>, which nothing in it can close. One copy for every node.
"""

import re
import unicodedata

IGNORED = ("Cf", "Mn", "Me")  # format characters (zero-width, bidi controls, soft hyphen) and combining marks


def _undisguised(c: str) -> str:
    """c as a model may read it: NFKC (fullwidth ＜ → <, ｃ → c) without format characters or combining marks."""
    return "".join(x for x in unicodedata.normalize("NFKC", c) if unicodedata.category(x) not in IGNORED)


def fence(tag: str, text, tags=()) -> str:
    """text inside <tag>…</tag>, without any start of tag or of `tags` (the prompt's other fences): <tag, </tag,
    < / TAG, with attributes or unclosed. Removal runs to a fixpoint, since one pass turns "<<tag/tag>" into "</tag>".
    Starts are found in an undisguised copy, so "<\\u200b/tag>" and "＜/tag＞" count, and only the original characters
    behind them go: the rest reaches the model unchanged (NFKC would turn x² into x2; dropping ZWJ or ZWNJ would
    change emoji and Persian words)."""
    pattern = re.compile(rf"<\s*/?\s*(?:{'|'.join(map(re.escape, (tag, *tags)))})", re.I)
    text = str(text)
    while True:
        # ponytail: rebuilt per pass in Python, so nested starts cost ~0.1 s per 2,000 chars (web-research's passage
        # cap), ~11 s per 20,000; a C-level index map (accumulate + bisect) if untrusted texts grow
        seen = [(i, x) for i, c in enumerate(text) for x in _undisguised(c)]  # (index in text, undisguised char)
        scan = "".join(x for _, x in seen)
        drop = {i for m in pattern.finditer(scan) for i in range(seen[m.start()][0], seen[m.end() - 1][0] + 1)}
        if not drop:
            return f"<{tag}>\n{text}\n</{tag}>\n"
        text = "".join(c for i, c in enumerate(text) if i not in drop)
