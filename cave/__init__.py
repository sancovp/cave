"""
CAVE - Code Agent Virtualization Environment

Virtualize any terminal-based code agent (Claude Code, Aider, etc.)
to create AI-legible architectures where you can vibe code together.
"""

# === Core Agent Classes ===
from .core.agent import (
    CodeAgent,
    CodeAgentConfig,
    ClaudeCodeAgent,
    ClaudeCodeAgentConfig,
    InboxMessage,
    UserPromptMessage,
    SystemEventMessage,
    BlockedMessage,
    CompletedMessage,
    IngressType,
    create_user_message,
    create_system_event,
)

# === CAVEAgent (The God Object) ===
from .core.cave_agent import CAVEAgent
from .core.config import CAVEConfig
from .core.models import MainAgentConfig, PAIAState, AgentRegistration, RemoteAgentHandle
from .core.state_reader import ClaudeStateReader

# === Mixins ===
from .core.mixins import (
    PAIAStateMixin,
    AgentRegistryMixin,
    MessageRouterMixin,
    HookRouterMixin,
    RemoteAgentMixin,
    SSEMixin,
)

# === Hooks (define hooks in code) ===
from .core.hooks import (
    ClaudeCodeHook,
    HookType,
    HookDecision,
    HookResult,
    HookRegistry,
    RegistryEntry,
)

__version__ = "0.1.0"
__all__ = [
    # Core agents
    "CodeAgent",
    "CodeAgentConfig",
    "ClaudeCodeAgent",
    "ClaudeCodeAgentConfig",
    "InboxMessage",
    "UserPromptMessage",
    "SystemEventMessage",
    "BlockedMessage",
    "CompletedMessage",
    "IngressType",
    "create_user_message",
    "create_system_event",
    # CAVEAgent
    "CAVEAgent",
    "CAVEConfig",
    # Models
    "PAIAState",
    "AgentRegistration",
    "RemoteAgentHandle",
    "ClaudeStateReader",
    # Mixins
    "PAIAStateMixin",
    "AgentRegistryMixin",
    "MessageRouterMixin",
    "HookRouterMixin",
    "RemoteAgentMixin",
    "SSEMixin",
    # Hooks
    "ClaudeCodeHook",
    "HookType",
    "HookDecision",
    "HookResult",
    "HookRegistry",
    "RegistryEntry",
]
