# DNA Definition - User's Exact Words

**Date:** 2026-01-26
**Source:** Conversation about DNA/OMNISANC architecture

---

## CRITICAL FIRST STATEMENT

> "basically **caveagent should have a workflow system** that gets impl, which is called DNA"

**CAVEAgent HAS the workflow system. DNA is what gets plugged in. CAVEAgent runs it, DNA is just data.**

---

## User's Statements About DNA (Chronological)

### On what DNA is:

> "DNA = **a bundle of loops** (data only, no execution logic)"

> "basically caveagent should have a workflow system that gets impl, which is called DNA, and it has a sequence of agent inference loops and transitions between them. it is designed to always make a cycle for 24/7 operation including a learning system... but all it really does is just execute this stuff in a sequence and process the transition logic lol"

### On OMNISANC's relationship to DNA:

> "OMNISANC is just a bundle of specific loop types, and then the caveagent method impls are what you make to run it all, so you make a new method 'run_omnisanc' and then you have caveagent.run calls run_impl and run_impl is defined as pass until you then add run_impl override that forwards to run_omnisanc"

> "DNA still necessary just that OMNISANC should factor into it somehow"

### On DNA being data, not execution:

> "you need to PUT THE STUFF ON THE CAVE AGENT, PERIOD. THE LOWER PARTS DO NOT NEED TO KNOW ABOUT THE CAVEAGENT AT ALL"

> "The caveagent needs to wire in everything using the pieces provided"

### On OMNISANC as a configuration:

> "OMNISANC doesnt need to be configurable, it is a configuration. but it needs to be replaceable as a configuration in something else which doesnt exist right now."

### On DAY/NIGHT:

> "day night is just a flag per paia which means 'user is actively talking to this agent right now'"

> "all day and night are are different home prompts for now, we dont need to actually filter fly i dont think. we can just prompt the LLM into acting like it's filtered"

### On AUTO vs MANUAL mode (separate from DAY/NIGHT):

> "night is autonomous but it isnt the same as auto mode. auto mode means there is a closed loop where even if the user never responds, it will continue, and eventually go into night mode automatically, and then come out automatically when its day again. see the difference?"

> "maybe its easier to think of DAY NIGHT and Auto/Manual as separate things entirely. Like, theres day work and night work and then later we can put in manual vs auto mode."

---

### On DNA structure (sequence + transitions):

> "DNA is a sequence of agent inference loops and a sequence of transition functions between them (like ie our file check state functions)"

### On hooks refactor:

> "the hooks need to be rewritten in pure python in cave's hook system"

### On OMNISANC as default impl:

> "OMNISANC is a specific impl of whatever the DNA workflow system is"

> "that is how we preserve configurability while also making the system hardcoded as what we want... it can be polymorphically overridden to customize but it all runs with our defaults"

> "OMNISANC is our default system, and you might only be able to override certain parts of IT, and only actually CHANGE the config from omnisanc if you go in and hack with your PAIA"

---

## Summary

- **CAVEAgent** = HAS the workflow system, does all orchestration
- **DNA** = data bundle (sequence of loops + sequence of transition functions), no execution logic
- **OMNISANC** = specific impl/instance of DNA (the default)
- **Configurability** = polymorphic override for customization, but runs with OMNISANC defaults
- **To change from OMNISANC** = go hack with your PAIA
- **Hooks** = need to be rewritten in pure Python in CAVE's hook system
- **Lower pieces (loops, transitions, hooks)** = DUMB, no CAVEAgent reference
- **DAY/NIGHT** = just a flag (user presence), different HOME prompts
- **AUTO/MANUAL** = separate concern (loop mechanism), implement later
