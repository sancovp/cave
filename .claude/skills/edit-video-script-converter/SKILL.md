---
name: edit-video-script-converter
description: "WHAT: the dev flow for the blog to video-script converter. WHEN: you are about to edit video_script.py or wire it into the blog organ."
---

# edit-video-script-converter — dev-flow for the blog→video-script converter

**In full:** WHAT: the development-flow for the blog->video-script converter (cave/core/publishing/video_script.py) — the callable that turns a rendered fixpoint USER blog post into a YouTube video script by inserting the video-only paragraphs (channel/host intro, retention teaser, end CTA). Covers the ONE structural coupling (the splice anchor is the first H2, guaranteed == OVERVIEW by render_fixpoint_post), the coherence edit-set, the E2E test, and the pending wire-into-fire_blog_organ leg. WHEN: when editing video_script.py, blog_to_video_script / blog_file_to_video_script / the intro+teaser builders, the splice anchor, or wiring the converter into the blog organ; or when render_fixpoint_post's rendered section layout changes (any of).

The converter (`cave/core/publishing/video_script.py`) turns a rendered fixpoint USER blog post
into a YouTube video script by inserting ONLY the video-only paragraphs (Isaac 2026-08-01: "the only
two things that are different about a youtube video vs a blog") and leaving everything else
byte-identical. The blog post already reads aloud as a spoken script (the `youtube_script` rubric law).

## 1. WHAT IT IS (so you edit the right thing)
- `blog_to_video_script(user_post_md, *, intro, teaser=None, cta=DEFAULT_CTA, cta_position="end")` —
  pure splice. After the hook (before `## OVERVIEW`): `intro`, then `teaser` (the "stick around till
  the end, I'm giving away X" retention CTA). `cta` at the end (default) or `after_intro`.
- `blog_file_to_video_script(path, *, intro, teaser=None, ...)` — file round-trip; writes the sibling
  `{base}-video-script.md` (matching the organ's `{base}-agent-pov.md` / `{base}-system-pov.md`).
- Builders: `agent_host_intro(owner, host)` (agent-hosted channel), `person_host_intro(name, role,
  avatar, dream)` (human host), `retention_teaser(giveaway=DEFAULT_GIVEAWAY)`.

## 2. HOW YOU EDIT IT (the ONE coupling — this is the load-bearing coherence check)
The splice anchor is **the first `## ` heading**, which `render_fixpoint_post`
(`cave-unicorn/cave_unicorn/journey_suite.py`) guarantees is `## OVERVIEW` — the title is an H1, the
hook is a bold line, the pain/dream/solution are bold lines, so the first H2 is always OVERVIEW. The
intro/teaser insert at the end of that hook zone.

**COHERENCE EDIT-SET — if you change ANY of these, check the others in the SAME unit of work:**
1. **`render_fixpoint_post` changes its section layout** (renames OVERVIEW, adds a section before it,
   stops emitting the hook as `**{hook}**`, changes the title level) → the first-H2 anchor in
   `_split_at_first_h2` may no longer be "right after the hook". RE-CHECK the anchor + the E2E
   integration test. This is the one edit that can silently break the converter from the outside.
2. **You change the insert POSITIONS or add a new video-only paragraph** → update the module docstring
   (it carries Isaac's verbatim spec), the `blocks` assembly order in `blog_to_video_script`, and the
   ordering assertions in `tests/test_video_script.py`.
3. **You change a builder's wording** (intro/teaser/CTA) → update the builder + its format test.

## 3. HOW YOU TEST IT (E2E through the REAL renderer — never "it imported")
```bash
cd /home/GOD/gnosys-plugin-v2/application/cave
PYTHONPATH=.:../cave-unicorn python3 -m pytest tests/test_video_script.py -q
```
`tests/test_video_script.py` includes `TestAgainstRealRenderer` — it calls the REAL
`render_fixpoint_post` and asserts `hook < intro < teaser < ## OVERVIEW` and the end CTA. The
self-contained tests assert the delta over the blog is EXACTLY the inserted paragraphs (nothing else
changes). If you touched the anchor (coupling #1), the real-renderer test is the surface that catches
a break — run it, do not trust the unit tests alone.

## 4. THE PENDING WIRE-INTO-THE-ORGAN LEG (VISION — not built yet)
Isaac's plan (2026-08-01): the converter stays a standalone callable AND gets wired into
`fire_blog_organ` (`cave/core/publishing/blog_organ_nightly.py`) once finalized + verified. When you
do that wiring, the coherence set is:
- call `blog_file_to_video_script(output_md_path, intro=…, teaser=…)` AFTER the organ flips the node
  done + the USER post is fresh (`_artifact_fresh`), writing the sibling `{base}-video-script.md`;
- the intro/teaser vars (channel_owner, host_agent_name, giveaway) need a source — either new
  **`Blog_Request` properties** (extend `REQUIRED_PROPS` / the contract docstring) or params on the
  automation; if you add Blog_Request props, update the contract in the organ's module docstring;
- the video script hands off to the **host Remotion AIOS** (OUT OF SCOPE — do not build video gen).
Until that lands, mark it VISION in the vision(m), not done.

## Why
The converter's correctness depends entirely on one external contract (render_fixpoint_post's output
shape). Making that coupling explicit — and testing through the real renderer — is what keeps a
renderer change from silently producing a mis-spliced script. Composes with the global
`every-build-ends-in-a-development-flow-skill` and `check-code-not-markdown-in-our-repos`.
