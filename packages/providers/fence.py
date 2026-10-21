"""
packages/providers/fence.py — R18 (docs/contracts.md): untrusted text (scraped pages, rows written from them, model
answers) reaches a prompt only inside <tag>…</tag>, which nothing in it can close. One copy for every node.
"""

import re
import unicodedata

def _undisguised(c: str) -> str:
    """c as a model may read it: the Unicode tag block (U+E0020-E007E, "ASCII smuggling") as its ASCII, then NFKC
    (fullwidth \uff1c -> <, \uff43 -> c) without control, format, private-use or unassigned characters and marks."""
    if 0xE0020 <= ord(c) <= 0xE007E:
        c = chr(ord(c) - 0xE0000)
    return "".join(x for x in unicodedata.normalize("NFKC", c) if unicodedata.category(x)[0] not in "CM")


def fence(tag: str, text, tags) -> str:
    """text inside <tag>…</tag>, without any start of tag or of `tags` (the prompt's other fences): <tag, </tag,
    < / TAG, with attributes or unclosed. Removal runs to a fixpoint, since one pass turns "<<tag/tag>" into "</tag>".
    Starts are found in an undisguised copy, so "<\\u200b/tag>" and "＜/tag＞" count, and only the original characters
    behind them go: the rest reaches the model unchanged (NFKC would turn x² into x2; dropping ZWJ or ZWNJ would
    change emoji and Persian words)."""
    # [\s/\\]* cannot backtrack (the old <\s*/?\s* was cubic on "<" + spaces) and also catches <\/tag, <//tag, </ /tag
    pattern = re.compile(rf"<[\s/\\]*(?:{'|'.join(map(re.escape, (tag, *tags)))})", re.I)
    text = str(text)
    while True:
        # ponytail: the undisguised copy is rebuilt per pass in Python (~0.1 s per 2,000 chars of nested starts); a
        # C-level index map (accumulate + bisect) if untrusted texts grow
        seen = [(i, x) for i, c in enumerate(text) for x in _undisguised(c)]  # (index in text, undisguised char)
        scan = "".join(x for _, x in seen)
        drop = {i for m in pattern.finditer(scan) for i in range(seen[m.start()][0], seen[m.end() - 1][0] + 1)}
        if not drop:
            return f"<{tag}>\n{text}\n</{tag}>\n"
        text = "".join(c for i, c in enumerate(text) if i not in drop)
