"""
RemoteAgent - Agent that runs via SDNA (claude -p under the hood).

This is the bridge between CAVE harness and SDNA executor.
SDNA handles the actual claude -p execution, giving us:
- Resume capabilities
- Proper session management
- Unified Python runtime
"""

from typing import Any, Dict, Optional
from dataclasses import dataclass, field
import logging
import traceback

logger = logging.getLogger(__name__)

# Try to import SDNA - graceful fallback if not installed
try:
    from sdna import agent_step, HermesConfig, StepResult, StepStatus
    SDNA_AVAILABLE = True
except ImportError as e:
    logger.debug(f"SDNA not available: {e}\n{traceback.format_exc()}")
    SDNA_AVAILABLE = False
    HermesConfig = None
    StepResult = None
    StepStatus = None


@dataclass
class RemoteAgentConfig:
    """Configuration for a remote agent."""
    name: str = "remote-agent"
    system_prompt: str = ""
    goal_template: str = ""
    max_turns: int = 10
    model: str = "claude-sonnet-4-20250514"
    working_directory: Optional[str] = None

    # SDNA-specific
    brain_query: Optional[str] = None
    brain_project_root: Optional[str] = None


@dataclass
class RemoteAgentResult:
    """Result from remote agent execution."""
    success: bool
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    blocked: bool = False
    blocked_reason: Optional[str] = None


class RemoteAgent:
    """
    Agent that runs via SDNA (claude -p under the hood).

    This replaces Claude Code's native Task tool subagents with
    SDNA-powered agents that run in the unified CAVE runtime.
    """

    def __init__(self, config: RemoteAgentConfig):
        self.config = config

        if not SDNA_AVAILABLE:
            logger.warning("SDNA not installed - RemoteAgent will not function")

    async def run(self, inputs: Optional[Dict[str, Any]] = None) -> RemoteAgentResult:
        """
        Execute the agent via SDNA.

        Args:
            inputs: Variable inputs for goal template interpolation

        Returns:
            RemoteAgentResult with output or error
        """
        if not SDNA_AVAILABLE:
            return RemoteAgentResult(
                success=False,
                error="SDNA not installed. Run: pip install sanctuary-dna"
            )

        # Build HermesConfig from our config
        hermes_config = HermesConfig(
            name=self.config.name,
            system_prompt=self.config.system_prompt,
            goal_template=self.config.goal_template,
            max_turns=self.config.max_turns,
            model=self.config.model,
            working_directory=self.config.working_directory,
            brain_query=self.config.brain_query,
            brain_project_root=self.config.brain_project_root,
        )

        try:
            # SDNA handles the claude -p execution
            result = await agent_step(hermes_config, inputs or {})

            if result.status == StepStatus.SUCCESS:
                return RemoteAgentResult(
                    success=True,
                    output=result.output
                )
            elif result.status == StepStatus.BLOCKED:
                return RemoteAgentResult(
                    success=False,
                    blocked=True,
                    blocked_reason=result.blocked.reason if result.blocked else "Unknown"
                )
            else:
                return RemoteAgentResult(
                    success=False,
                    error=result.error or "Unknown error"
                )

        except Exception as e:
            logger.error(f"RemoteAgent execution failed: {e}\n{traceback.format_exc()}")
            return RemoteAgentResult(
                success=False,
                error=str(e)
            )


def create_remote_agent(
    name: str,
    system_prompt: str,
    goal_template: str,
    **kwargs
) -> RemoteAgent:
    """Helper to create a RemoteAgent with common defaults."""
    config = RemoteAgentConfig(
        name=name,
        system_prompt=system_prompt,
        goal_template=goal_template,
        **kwargs
    )
    return RemoteAgent(config)
