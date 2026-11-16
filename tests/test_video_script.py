"""Tests for the blog -> video-script converter (cave.core.publishing.video_script).

The converter inserts exactly TWO paragraphs into a rendered fixpoint USER post
(Isaac 2026-08-01): a channel/host INTRO right after the hook, and a subscribe
CTA. Everything else is unchanged. SAMPLE_POST below is structurally identical
to render_fixpoint_post's real output (verified E2E through the real renderer),
so these tests are self-contained (no cave-unicorn / fork import needed). One
optional test exercises the REAL renderer when it's importable.
"""
import pytest

from cave.core.publishing.video_script import (
    blog_to_video_script,
    blog_file_to_video_script,
    agent_host_intro,
    person_host_intro,
    retention_teaser,
    DEFAULT_CTA,
    DEFAULT_GIVEAWAY,
)

# Structurally identical to render_fixpoint_post output: `# title`, `**hook**`,
# then `## OVERVIEW`, the 7-stage JOURNEY, and `## THE FRAMEWORK`.
HOOK = "I stopped writing my own videos. My AI does it now."
SAMPLE_POST = f"""# How I Made My AI Publish My Channel

**{HOOK}**

## OVERVIEW

**The pain:** No time to turn ideas into videos.

**The dream:** Wake up and the video is written.

**My solution:** One system that scripts everything you build.

## THE JOURNEY

### STATUS QUO

Doing it all by hand, burning out.

### THE DEBATE

Real creators write every word, part of me said.

### THE TRIALS

The first drafts were robotic.

### THE NEW VIEW

Blog and video are the same story.

### THE RIGHT WAY

Write once, splice in what a video needs.

### THE BOON

I record instead of write.

### THE WORLD OF MASTERY

A channel that publishes itself.

## THE FRAMEWORK

**We solved this.** Instructions that turn any build story into a spoken script.

**Build it yourself:** an afternoon

**[Start here](https://github.com/example/x)**
"""

INTRO = agent_host_intro("Isaac", "GNOSYS")


def _norm(s: str) -> str:
    return "\n".join(l.rstrip() for l in s.strip().splitlines() if l.strip())


class TestIntroPlacement:
    def test_intro_sits_after_hook_before_overview(self):
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO)
        i_hook = script.index(f"**{HOOK}**")
        i_intro = script.index(INTRO)
        i_overview = script.index("## OVERVIEW")
        assert i_hook < i_intro < i_overview

    def test_intro_is_present_verbatim(self):
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO)
        assert INTRO in script


class TestCtaPlacement:
    def test_cta_at_end_by_default(self):
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO)
        assert script.rstrip().endswith(DEFAULT_CTA.rstrip())

    def test_cta_after_intro(self):
        cta = "Subscribe if you want the next one."
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO, cta=cta,
                                      cta_position="after_intro")
        i_intro = script.index(INTRO)
        i_cta = script.index(cta)
        i_overview = script.index("## OVERVIEW")
        assert i_intro < i_cta < i_overview

    def test_cta_none_omits_it(self):
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO, cta=None)
        assert DEFAULT_CTA not in script
        # still ends on the blog's own closing line
        assert script.rstrip().endswith("[Start here](https://github.com/example/x)**")

    def test_invalid_cta_position_raises(self):
        with pytest.raises(ValueError) as exc:
            blog_to_video_script(SAMPLE_POST, intro=INTRO, cta_position="middle")
        assert "cta_position" in str(exc.value)
        assert "middle" in str(exc.value)


class TestRetentionTeaser:
    def test_teaser_sits_after_intro_before_overview(self):
        teaser = retention_teaser("the demo code")
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO, teaser=teaser)
        i_hook = script.index(f"**{HOOK}**")
        i_intro = script.index(INTRO)
        i_teaser = script.index(teaser)
        i_overview = script.index("## OVERVIEW")
        assert i_hook < i_intro < i_teaser < i_overview

    def test_teaser_and_end_cta_both_present(self):
        # Isaac's shape: intro + teaser after the hook, real CTA at the end.
        teaser = retention_teaser()
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO, teaser=teaser)
        assert teaser in script  # up top with the intro
        assert script.rstrip().endswith(DEFAULT_CTA.rstrip())  # real CTA at end
        assert script.index(teaser) < script.index(DEFAULT_CTA)

    def test_teaser_none_is_omitted(self):
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO, teaser=None)
        assert "stick around until the end" not in script

    def test_retention_teaser_format(self):
        s = retention_teaser("the demo code")
        assert "stick around until the end" in s
        assert "the demo code" in s

    def test_retention_teaser_default_giveaway(self):
        assert DEFAULT_GIVEAWAY in retention_teaser()

    def test_delta_with_teaser_is_exactly_intro_teaser_cta(self):
        teaser = retention_teaser("the demo code")
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO, teaser=teaser)
        delta = (script.replace(INTRO, "").replace(teaser, "")
                       .replace(DEFAULT_CTA, ""))
        assert _norm(delta) == _norm(SAMPLE_POST)


class TestOnlyTwoParagraphsChange:
    def test_delta_over_blog_is_exactly_intro_plus_cta(self):
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO)
        delta = script.replace(INTRO, "").replace(DEFAULT_CTA, "")
        assert _norm(delta) == _norm(SAMPLE_POST)

    def test_every_original_section_survives(self):
        script = blog_to_video_script(SAMPLE_POST, intro=INTRO)
        for marker in ("## OVERVIEW", "## THE JOURNEY", "### STATUS QUO",
                       "### THE BOON", "### THE WORLD OF MASTERY",
                       "## THE FRAMEWORK"):
            assert marker in script

    def test_post_with_no_h2_still_appends_inserts(self):
        # degenerate input (only a title + hook, no sections) -> intro + cta
        # still land; nothing is lost.
        tiny = "# Title\n\n**a hook line**\n"
        script = blog_to_video_script(tiny, intro=INTRO)
        assert INTRO in script and DEFAULT_CTA in script
        assert "**a hook line**" in script


class TestIntroBuilders:
    def test_agent_host_intro_format(self):
        s = agent_host_intro("Isaac", "GNOSYS")
        assert "Isaac's YouTube channel" in s
        assert "your host GNOSYS" in s
        assert "his personal AI agent" in s

    def test_agent_host_intro_custom_descriptor(self):
        s = agent_host_intro("Ada", "Byron", descriptor="her research assistant")
        assert "Ada's YouTube channel" in s and "her research assistant" in s

    def test_person_host_intro_format(self):
        s = person_host_intro("Isaac", "builder", "AI agents", "ship overnight")
        assert "my name is Isaac" in s
        assert "I'm a builder" in s
        assert "who works with AI agents to ship overnight" in s


class TestFileRoundtrip:
    def test_file_to_video_script_default_sibling(self, tmp_path):
        src = tmp_path / "blog1.md"
        src.write_text(SAMPLE_POST)
        out = blog_file_to_video_script(str(src), intro=INTRO)
        assert out == str(tmp_path / "blog1-video-script.md")
        written = (tmp_path / "blog1-video-script.md").read_text()
        assert INTRO in written and written.rstrip().endswith(DEFAULT_CTA.rstrip())

    def test_file_to_video_script_explicit_out(self, tmp_path):
        src = tmp_path / "blog1.md"
        src.write_text(SAMPLE_POST)
        dst = tmp_path / "custom.md"
        out = blog_file_to_video_script(str(src), intro=INTRO, out_path=str(dst))
        assert out == str(dst) and dst.exists()


class TestAgainstRealRenderer:
    """Optional: exercise the REAL render_fixpoint_post surface if importable."""

    def test_real_render_then_convert(self):
        journey_suite = pytest.importorskip("cave_unicorn.journey_suite")
        from types import SimpleNamespace
        core = SimpleNamespace(
            journey_name="T", hook=HOOK,
            overview_pain="p", overview_dream="d", overview_solution="s",
            status_quo="sq", debate="db", trials="tr", new_view="nv",
            right_way="rw", the_boon="bn", world_of_mastery="wm",
            framework_statement="fs", build_time="an afternoon",
            github_url="https://github.com/example/x",
            plugin_url="https://github.com/example/x", deep_dive_url=None,
        )
        post = journey_suite.render_fixpoint_post(core)
        script = blog_to_video_script(post, intro=INTRO)
        assert script.index(f"**{HOOK}**") < script.index(INTRO) < script.index("## OVERVIEW")
        assert script.rstrip().endswith(DEFAULT_CTA.rstrip())
