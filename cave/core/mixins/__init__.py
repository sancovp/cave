"""CAVE Mixins.

Mixin classes that compose into CAVEAgent.
"""
from .paia_state import PAIAStateMixin
from .agent_registry import AgentRegistryMixin
from .message_router import MessageRouterMixin
from .hook_router import HookRouterMixin
from .loop_manager import LoopManagerMixin
from .remote_agent import RemoteAgentMixin
from .sse import SSEMixin
from .omnisanc import OmnisancMixin
from .anatomy import AnatomyMixin, Organ, Heart, Blood, Ears, Tick
from .automation_mixin import AutomationMixin
from .tui import TUIMixin
from .cognition import CognitionMixin
from .aios import AIOSMixin

__all__ = [
    "PAIAStateMixin",
    "AgentRegistryMixin",
    "MessageRouterMixin",
    "HookRouterMixin",
    "LoopManagerMixin",
    "RemoteAgentMixin",
    "SSEMixin",
    "OmnisancMixin",
    "AnatomyMixin",
    "AutomationMixin",
    "CognitionMixin",
    "AIOSMixin",
    "Organ",
    "Heart",
    "Blood",
    "Ears",
    "Tick",
    "TUIMixin",
]
