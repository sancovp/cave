"""CAVE Core - Agent classes and harness components."""

from .agent import (
    CodeAgent,
    CodeAgentConfig,
    ClaudeCodeAgent,
    ClaudeCodeAgentConfig,
)

from .hooks import (
    CodeAgentHook,
    ClaudeCodeHook,
    CodexHook,
    HookProvider,
    HookType,
    HookDecision,
    HookResult,
)

from .cognition import (
    CognitiveSpace,
    CognitiveSpaceStopHook,
    CognitionStore,
    ReifiedAgentInferenceLoop,
)

from .aios import (
    AIOSBridge,
    discover_aios_root,
)

from .dna import (
    AutoModeDNA,
    AutoModeDNAConfig,
    DNAConfigStore,
    DNASequence,
    DNASequenceStep,
)
