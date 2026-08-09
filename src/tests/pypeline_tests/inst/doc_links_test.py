# pyright: reportInvalidTypeForm=none
"""Meta-test: every markdown link in the repo resolves.

Recursively scans all `.md` files under the repo root, builds a GitHub-style
heading-slug anchor set for each file, then checks every markdown link
`[text](target)`:
  - `#anchor` links must resolve to a heading anchor in the SAME file.
  - `path/to/file.md#anchor` / `path/to/file.md` links must resolve to an
    existing file (relative to the linking file's directory), and if an
    anchor is given, that anchor must exist in the target file's heading set.

Links to external URLs (`http://`, `https://`, `mailto:`) are skipped, as are
links into non-`.md` targets (source files, images, etc. -- existence of
those isn't this test's concern).

Also asserts, specific to the post-restructure `docs/pypeline_guide.md`:
  - no `§` (section-sign) character appears anywhere in the file.
  - no heading anchor in the file starts with a digit (i.e. no leftover
    `#11-types`-style numbered anchors from the old numbered-heading scheme).

Run standalone: python3 doc_links_test.py
"""

import os
import re
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINE_TESTS_DIR = os.path.dirname(INST_DIR)
REPO_ROOT = os.path.abspath(os.path.join(PYPELINE_TESTS_DIR, "..", "..", ".."))

# Directories not worth scanning (VCS internals, caches, node_modules-style
# vendored trees if any show up later).
_SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv"}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

GUIDE_PATH = os.path.join(REPO_ROOT, "docs", "pypeline_guide.md")


def _slugify(heading: str) -> str:
    """Mirror GitHub's markdown heading -> anchor slug algorithm closely
    enough for this repo's headings: strip backticks (inline code markup
    doesn't survive into the anchor), lowercase, drop anything that isn't a
    word character/space/hyphen (note: spaces are NOT collapsed before this
    step, so e.g. "A & B" -> "a--b" with a double hyphen, matching GitHub),
    then turn each remaining space into a hyphen."""
    s = heading.strip()
    s = s.replace("`", "")
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = s.replace(" ", "-")
    return s


def _find_md_files(root: str) -> list:
    md_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        for fn in filenames:
            if fn.endswith(".md"):
                md_files.append(os.path.join(dirpath, fn))
    return sorted(md_files)


def _anchor_set(text: str) -> set:
    """Build the de-duplicated (GitHub '-1', '-2', ...) anchor slug set for
    a markdown file's own headings."""
    seen_counts = {}
    anchors = set()
    in_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if not m:
            continue
        base = _slugify(m.group(2))
        if base == "":
            continue
        if base in seen_counts:
            seen_counts[base] += 1
            slug = f"{base}-{seen_counts[base]}"
        else:
            seen_counts[base] = 0
            slug = base
        anchors.add(slug)
    return anchors


def _extract_links(text: str) -> list:
    """Return list of (line_no, link_text, target), skipping fenced code
    blocks (backtick spans inside a line are fine to scan through, but a
    ```-fenced block full of e.g. shell examples shouldn't be scanned)."""
    links = []
    in_fence = False
    for i, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # Strip inline `code spans` before matching links: a construct like
        # `leaf_fns[j](...)` inside backticks isn't a markdown link, but
        # looks like one to a naive [text](target) regex.
        scrubbed = _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)
        for m in _LINK_RE.finditer(scrubbed):
            links.append((i, m.group(1), m.group(2)))
    return links


def _is_external(target: str) -> bool:
    return bool(
        re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target)
        or target.startswith("mailto:")
    )


def _check_repo_links():
    md_files = _find_md_files(REPO_ROOT)
    file_text = {}
    file_anchors = {}
    for f in md_files:
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        file_text[f] = text
        file_anchors[f] = _anchor_set(text)

    broken = []  # (source_file, line_no, target, reason)

    for f in md_files:
        text = file_text[f]
        for line_no, link_text, target in _extract_links(text):
            if _is_external(target):
                continue
            if target.startswith("#"):
                anchor = target[1:]
                if anchor and anchor not in file_anchors[f]:
                    broken.append((f, line_no, target, "in-page anchor not found"))
                continue

            # cross-file link: split off anchor fragment
            if "#" in target:
                path_part, anchor = target.split("#", 1)
            else:
                path_part, anchor = target, None

            path_part = path_part.split("?", 1)[0]  # drop query strings, if any
            if path_part == "":
                # pure "#anchor" already handled above; empty path with no
                # anchor is a malformed link, ignore
                continue

            resolved = os.path.normpath(os.path.join(os.path.dirname(f), path_part))

            if os.path.isdir(resolved):
                # A link straight to a directory (GitHub renders its file
                # listing) -- nothing further to validate.
                continue

            if not os.path.isfile(resolved):
                broken.append((f, line_no, target, f"target file not found: {resolved}"))
                continue

            if not resolved.endswith(".md"):
                # Non-markdown targets (source files, images, etc.): existence
                # already checked above; no heading-anchor set to validate.
                continue

            if anchor:
                target_anchors = file_anchors.get(resolved)
                if target_anchors is None:
                    with open(resolved, encoding="utf-8") as fh:
                        target_anchors = _anchor_set(fh.read())
                    file_anchors[resolved] = target_anchors
                if anchor not in target_anchors:
                    broken.append(
                        (f, line_no, target, f"anchor '{anchor}' not found in {resolved}")
                    )

    return broken, len(md_files)


def test_no_broken_markdown_links():
    broken, num_files = _check_repo_links()
    if broken:
        lines = [f"{len(broken)} broken markdown link(s) found across {num_files} files:"]
        for src, line_no, target, reason in broken:
            rel_src = os.path.relpath(src, REPO_ROOT)
            lines.append(f"  {rel_src}:{line_no}: [{target}] -- {reason}")
        raise AssertionError("\n".join(lines))
    print(f"doc_links_test: {num_files} markdown files scanned, 0 broken links")


def test_guide_has_no_section_sign():
    if not os.path.isfile(GUIDE_PATH):
        return
    with open(GUIDE_PATH, encoding="utf-8") as f:
        text = f.read()
    assert "§" not in text, (
        "docs/pypeline_guide.md still contains a '§' (section sign) "
        "character -- all internal cross-references should be plain named "
        "links after the anchor-stability restructure."
    )


def test_guide_has_no_numbered_anchors():
    if not os.path.isfile(GUIDE_PATH):
        return
    with open(GUIDE_PATH, encoding="utf-8") as f:
        text = f.read()
    anchors = _anchor_set(text)
    numbered = sorted(a for a in anchors if a[0].isdigit())
    assert not numbered, (
        f"docs/pypeline_guide.md has heading anchor(s) starting with a digit "
        f"(leftover numbered-heading scheme): {numbered}"
    )


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
