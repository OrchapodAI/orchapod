# platform-w6 report — wave 5, item 1: one shared R18 fence

**Status:** DONE.

**Branch:** hack/platform-w6, in the worktree /Users/hari/src/orchapod-hack/.claude/worktrees/platform-w6. The base is 5354f75 (`git merge-base --is-ancestor 5354f75 HEAD` passed). Nothing was pushed.

**Commits:**
- fe4f447 docs(contracts): R18's fence is one function in packages/providers, NFKC and zero-width/bidi aware
- cdda800 feat(providers): shared R18 fence; disguised tag starts (zero-width, bidi, NFKC forms) cannot close a tag
- b6c42ed refactor(containers): synth-distilabel, data-prep and judge-eval use the shared R18 fence

**Cost:** $0. No key was used, and no network or cloud call was made.

## What changed

### packages/providers/fence.py (new, 33 lines)
- **Signature:** `fence(tag, text, tags=()) -> "<tag>\n{text}\n</tag>\n"`.
- **What it removes:** every start of `tag` and of the names in `tags`, repeated until none is left (a fixpoint). A start is `<tag`, `</tag` or `< / TAG`, with attributes or unclosed. The regex is the same as in the three old copies.
- **How it finds them:** it scans an "undisguised" copy of the text. For each character the copy holds:
  - the character's NFKC form, so `＜` becomes `<` and `ｃ` becomes `c`;
  - minus Unicode categories **Cf** (zero-width, bidi controls, soft hyphen, BOM) and **Mn/Me** (combining grapheme joiner, variation selectors, combining marks).
- **What it deletes:** each character in the copy remembers the index of its original character. Only the original characters behind a match are removed, including any invisible characters inside the match.
- **Normal text:** text that contains no tag start reaches the model byte-identical.
- `str(text)` is applied first, as judge-eval's copy did.

### The three containers (`git diff --stat`: 13 insertions, 30 deletions)
- Each container's regex and `fence` function are deleted.
- Each keeps a `TAGS` tuple and passes it to the shared fence: synth `("passage", "reference")`, data-prep `("passage", "example")`, judge-eval its existing five.
- synth's old fence appended its UNTRUSTED line itself, so its two call sites now append it. The prompts are byte-identical to before.
- data-prep's `import re` became unused and was removed.

### docs/contracts.md
One line under "Provider interfaces → Shared rules", which is platform's section. It describes the function, the scan-copy rule and the untrusted instruction that follows the fences.

## Answers to the dispatch's questions

1. **Why there is a `tags` argument.** The three copies' tag sets differ. The existing tests also require cross-tag stripping:
   - a passage fence must also remove `<reference` (tests/containers/test_synth_distilabel.py:213-215) and `<example` (test_data_prep.py:318-320);
   - each of judge-eval's five tags may appear only twice in the whole prompt (test_judge_eval.py:158-160).

   So the helper takes its own tag plus the prompt's other fences. `fence(tag, text)` on its own strips only its own tag.
2. **NFKC applies only to the copy that is scanned.** Normalising the fenced text would change meaning, as `unicodedata` confirms: `x²` becomes `x2`, `ﬁ` becomes `fi`, `①` becomes `1`, and `ＡＢＣ１２３` becomes `ABC123`.
3. **The zero-width/bidi strip also applies only to the scanned copy.** Removing these characters from the text itself would change meaning:
   - dropping ZWJ splits emoji sequences (👨‍👩‍👧 becomes three emoji);
   - ZWNJ is part of the spelling in Persian and Hindi (می‌خواهم);
   - RLM/LRM order mixed-direction text.

   They stay in the text. The only ones removed are those inside a matched tag start, which are deleted along with it.
4. **Why NFKC runs per character.** The index map needs it. Per-character NFKC differs from whole-string NFKC only in canonical composition across characters: for example, `<` followed by U+0338 becomes `≮` as a whole string. Combining marks are dropped from the copy, so per-character is the stricter of the two for finding tag starts.
5. **Why Mn/Me as well as Cf.** The combining grapheme joiner (U+034F) and the variation selectors (U+FE00–FE0F) are zero-width but have category Mn, not Cf.
6. **No existing test asserted the old, weaker behaviour.** All three containers' test files pass unchanged.

## Proof

- **Container tests plus the new file:** `python -m pytest -q tests/containers/test_synth_distilabel.py tests/containers/test_data_prep.py tests/containers/test_judge_eval.py tests/providers/test_fence.py` → `162 passed` (133 existing + 29 new).
  - `git diff --quiet 5354f75 -- tests/containers` confirms those test files are unchanged.
- **Red before green:** I ran the new test file against the old algorithm, moved unchanged into the shared module: `16 failed, 13 passed`.
  - Failed: every zero-width, bidi, combining-mark, fullwidth, small-form (`﹤`), maths-bold (`𝐜𝐨𝐧𝐭𝐞𝐱𝐭`) and cross-disguise reassembly case (`<​<context/context>`, `＜＜context/context＞`).
  - Passed: the plain ASCII, reassembly and normal-text cases.
  - With the scan the result is `29 passed`. The test's own checker uses whole-string NFKC, so it is independent of the module, and it asserts it can see every attack, so no case can pass because the checker misses it.
- **Behaviour on text without disguises (differential):** a scratch script, not committed, compared the old regex fixpoint with the shared fence on 20,000 random strings. The strings mixed tag fragments, ASCII and non-ASCII characters that are not disguises. Result: `20000/20000 identical; 4244 of them had a tag start the old fixpoint removed`.
- **Inside the images, without building:** I mounted the committed fence.py read-only into the existing `orchapod/{synth-distilabel,data-prep,judge-eval}:dev` images (`docker run --rm --network none`). Importing `packages.providers.fence` and fencing `"a <​/context> ＜/context＞ b"` gave `<context>\na > ＞ b\n</context>\n` in all three. No container is left behind.
- **The gate:** `make check PY=python` (shared venv) on b6c42ed → rc=0.
  - ruff: `All checks passed!`
  - pytest: `729 passed, 2 warnings`
  - web tests: `ℹ pass 27`, `ℹ fail 0`
  - `SKIP stub e2e: set E2E=1 (orchestrator/integration only)`
- **Timing:**

  | Input | 2,000 chars | 20,000 chars |
  | --- | --- | --- |
  | Normal text | 1.3 ms | 8 ms |
  | Adversarial nesting (`"<"*k + "context"*k`) | 0.10 s | 11.2 s |
  | The old C-level fixpoint on the same nesting | 2.4 ms | 243 ms |

  The nesting cost is quadratic, as the old fixpoint's was. In practice the fenced texts are web-research passages (at most 2,000 chars), rows, or answers bounded by `max_tokens`. A `ponytail:` comment in fence.py names the ceiling and the upgrade path: a C-level index map with accumulate and bisect.

## Packaging
- All three Dockerfiles copy the whole directory (`COPY packages/providers /app/packages/providers`) onto python:3.12-slim (judge-eval uses slim-trixie), and `unicodedata` is stdlib. So no Dockerfile changed.
- I built no images. After the merge, the Orchestrator rebuilds `orchapod/{synth-distilabel,data-prep,judge-eval}:dev`.

## What it does not catch (residual risk, outside the brief)
- **Homoglyphs that NFKC does not fold:**
  - `‹ 〈 ⟨ ˂ ᐸ` for `<`;
  - `∕ ⁄` for `/`;
  - Cyrillic or Greek letters inside the tag name, e.g. `</сontext>` with a Cyrillic с.

  Catching these needs the Unicode TR39 confusables data, which is not in the stdlib.
- **Escaped forms:** `&lt;/context&gt;`, `<\/context>`, `</context>`.
- **A tag start written entirely in Unicode tag characters** (U+E003C U+E002F …, "ASCII smuggling"). The scanned copy drops them as Cf instead of decoding them.

In every one of these cases the text still sits inside its fence, followed by the untrusted-data instruction. The fence is defence in depth, not a guarantee.

## Open questions
1. Should the fence also cover some of the vectors above? None of these changes would affect text without a tag start.
   - Decoding U+E0020–E007E to ASCII in the scanned copy is one line.
   - Adding `\\?` before `/` in the regex catches `<\/tag>`.
   - HTML entities would need `html.unescape` on the copy, which needs its own index map.
   - Confusables need a data table.
2. The contracts line (fe4f447) sits under "Provider interfaces → Shared rules". Approve it there, or move it under R18.

## For the Orchestrator to record
- **DECISION 2026-10-24:** R18's fence is `packages/providers/fence.py` `fence(tag, text, tags=())`, with `tags` = the prompt's other fences. NFKC and the zero-width/bidi/combining-mark strip apply only to the copy that is scanned for tag starts, never to the text the model sees. Reason: NFKC turns x² into x2, and dropping ZWJ/ZWNJ breaks emoji and Persian spelling. (platform-w6)
- **STATE:** "P1 shared fence()" → DONE (platform-w6, b6c42ed). After the merge, rebuild the three images.
