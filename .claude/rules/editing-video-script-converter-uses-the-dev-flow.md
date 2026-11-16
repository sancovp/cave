# Editing The Blog→Video-Script Converter Uses The `edit-video-script-converter` Dev-Flow FIRST — repo-scoped, NON-NEGOTIABLE

When you are about to edit `cave/core/publishing/video_script.py` — `blog_to_video_script`,
`blog_file_to_video_script`, the intro/teaser/CTA builders, the splice anchor (`_split_at_first_h2`),
the insert positions, or wire the converter into `fire_blog_organ` — you MUST FIRST use the
`edit-video-script-converter` skill and do its COMPLETE Part-2 coherence edit-set, then its Part-3 E2E
test. NEVER edit the converter in one place only.

The converter's correctness is COUPLED to an external contract: the splice anchor is the first `##`
heading, guaranteed to be `## OVERVIEW` **by** `render_fixpoint_post`
(`cave-unicorn/cave_unicorn/journey_suite.py`). A change to that renderer's section layout can silently
break the splice from the outside — so a renderer edit is ALSO a converter-coherence event. The only
valid test is E2E through the REAL `render_fixpoint_post` surface (`tests/test_video_script.py` ::
`TestAgainstRealRenderer`), never "it imported" and never the unit tests alone.

**Why:** this is the project-scoped enforcement required by the global law
`every-build-ends-in-a-development-flow-skill`. See `edit-video-script-converter` for the full edit-set
(incl. the pending wire-into-`fire_blog_organ` leg and the Blog_Request-contract coherence it will
need) and the E2E test through the real renderer.
