"""blog -> video-script converter.

A rendered fixpoint blog USER post ALREADY reads aloud as a spoken script (the
youtube_script law of the blog rubric). So converting a blog post to a YouTube
video script is NOT a rewrite — only TWO things differ between a video and the
blog (Isaac 2026-08-01, verbatim: "Those are the only two things that are
different about a youtube video vs a blog"):

  (1) an INTRO paragraph right after the hook — channel/host identification.
      Isaac: "you have the hook which is like 15s then you jump into
      'if you dont know who i am, my name is {name}, im a {role you should see
      me as} who works with {avatar} to {dream they achieve bc of me}.'" — and
      the agent-hosted form for a channel the AI hosts:
      "if you are new here and dont know who we are, this is {user's} youtube
      channel and im your host {agent name}, his personal AI agent...".
  (2) a subscribe CTA at the END. Isaac: "needs a CTA at the end of the video."
  (3) a RETENTION TEASER placed WITH the intro (the "who I am" section) — a CTA
      about the end-CTA. Isaac, verbatim: "we'll just put another CTA about the
      CTA being at the end at the who i am section 'make sure you stick around
      until the end because im giving away x (usually the code/demo code)'."

So the after-hook block is INTRO + TEASER, and the CTA lands at the end.
This module INSERTS those paragraphs at fixed positions and returns
the video-script markdown. Everything else is byte-for-byte unchanged (the post
is already the spoken script). Video GENERATION (the host Remotion AIOS) is out
of scope — this produces only the script TEXT.

The splice anchor is structural, coupled to render_fixpoint_post
(cave_unicorn.journey_suite): that renderer emits, joined by blank lines,
`# {title}`, then `**{hook}**`, then `## OVERVIEW`, then the rest. So the HOOK
ZONE is exactly everything before the FIRST `## ` heading — the intro goes at
the end of that zone (right after the hook, before OVERVIEW). If the renderer's
section layout changes, this anchor is what to re-check (see the dev-flow note
in the module's vision doc).
"""

from __future__ import annotations

import re
from pathlib import Path

# A generic subscribe CTA. Isaac left the CTA text/position open; this is the
# default (overridable via the `cta` / `cta_position` params). Position defaults
# to the end (a closing ask); pass cta_position="after_intro" for an early ask.
DEFAULT_CTA = (
    "If this is landing for you, hit subscribe — that's what tells me to keep "
    "hooking this stuff up and showing you how."
)


def agent_host_intro(channel_owner: str, host_agent_name: str,
                     descriptor: str = "his personal AI agent") -> str:
    """The agent-hosted channel intro (Isaac's for-us form): the AI agent is the
    on-camera host of the owner's channel.

    channel_owner   : whose YouTube channel this is (the human).
    host_agent_name : the AI agent hosting/narrating.
    descriptor      : the trailing descriptor of the host (default matches
                      Isaac's "his personal AI agent").
    """
    return (f"If you're new here and don't know who we are — this is "
            f"{channel_owner}'s YouTube channel, and I'm your host "
            f"{host_agent_name}, {descriptor}.")


def person_host_intro(name: str, role: str, avatar: str, dream: str) -> str:
    """The generic person-hosted intro (Isaac's generic form): the human is the
    host.

    Fills: my name is {name}, I'm a {role} who works with {avatar} to {dream}.
    """
    return (f"If you don't know who I am — my name is {name}, I'm a {role} "
            f"who works with {avatar} to {dream}.")


# Default giveaway for the retention teaser — Isaac: "usually the code/demo code".
DEFAULT_GIVEAWAY = "the code so you can build this yourself"


def retention_teaser(giveaway: str = DEFAULT_GIVEAWAY) -> str:
    """The retention teaser (Isaac 2026-08-01): a CTA about the end-CTA, placed
    WITH the intro / "who I am" section — "make sure you stick around until the
    end because I'm giving away {giveaway}" (usually the code / demo code)."""
    return (f"And make sure you stick around until the end — I'm giving away "
            f"{giveaway}.")


def _split_at_first_h2(md: str) -> tuple[str, str]:
    """Split a rendered fixpoint post into (hook_zone, body).

    hook_zone = everything before the FIRST `## ` heading = `# {title}` +
    `**{hook}**` (guaranteed by render_fixpoint_post: the title is an H1, the
    hook is a bold line, the pain/dream/solution are bold lines, so the first
    line starting with `## ` is always `## OVERVIEW`). body = that heading
    onward. If no `## ` heading is present, the whole thing is the hook zone.
    """
    m = re.search(r"(?m)^## ", md)
    if not m:
        return md.rstrip(), ""
    cut = m.start()
    return md[:cut].rstrip(), md[cut:]


def blog_to_video_script(user_post_md: str, *, intro: str,
                         teaser: str | None = None,
                         cta: str | None = DEFAULT_CTA,
                         cta_position: str = "end") -> str:
    """Convert a rendered fixpoint USER blog post to a YouTube video script.

    The after-hook block (inserted immediately AFTER the hook, before
    `## OVERVIEW`) is `intro` then, if given, the retention `teaser` (the "stick
    around until the end, I'm giving away X" CTA-about-the-CTA). `cta` lands
    either at the END (cta_position="end", the default — Isaac: "needs a CTA at
    the end") or right after the after-hook block (cta_position="after_intro").
    Pass teaser=None / cta=None to omit either. Everything else is byte-identical
    to the blog. Pure — no I/O.

    Raises ValueError on an unrecognized cta_position.
    """
    if cta_position not in ("end", "after_intro"):
        raise ValueError(
            f"cta_position must be 'end' or 'after_intro', got {cta_position!r}")

    head, body = _split_at_first_h2(user_post_md)

    # after-hook block: channel/host intro, then the retention teaser (if any).
    blocks = [head, intro]
    if teaser:
        blocks.append(teaser)
    if cta_position == "after_intro" and cta:
        blocks.append(cta)
    if body:
        blocks.append(body.rstrip())
    md = "\n\n".join(b for b in blocks if b)

    if cta_position == "end" and cta:
        md = md.rstrip() + "\n\n" + cta

    return md.rstrip() + "\n"


def blog_file_to_video_script(user_post_path: str, *, intro: str,
                              teaser: str | None = None,
                              cta: str | None = DEFAULT_CTA,
                              cta_position: str = "end",
                              out_path: str | None = None) -> str:
    """Read the USER-post markdown at `user_post_path`, convert it, and write the
    video-script markdown.

    out_path defaults to the sibling `{base}-video-script.md` (matching the blog
    organ's sibling convention, where the USER post is `{base}.md` and the other
    POVs are `{base}-agent-pov.md` / `{base}-system-pov.md`). Returns the path
    written.
    """
    src = Path(user_post_path)
    md = blog_to_video_script(src.read_text(), intro=intro, teaser=teaser,
                              cta=cta, cta_position=cta_position)
    if out_path is None:
        out_path = str(src.with_name(src.stem + "-video-script" + src.suffix))
    Path(out_path).write_text(md)
    return out_path
