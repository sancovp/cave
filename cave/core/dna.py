"""AutoModeDNA - Orchestrates a sequence of AgentInferenceLoops.

DNA = a list of loops + cycle/one_shot behavior.
When in auto mode, DNA activates loops, checks exit conditions,
and transitions to next loop (or cycles/stops).
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .loops import AgentInferenceLoop, AVAILABLE_LOOPS

if TYPE_CHECKING:
    from .cave_agent import CAVEAgent

logger = logging.getLogger(__name__)


class ExitBehavior(str, Enum):
    """What to do when the last loop completes."""
    ONE_SHOT = "one_shot"  # Stop after one pass through all loops
    CYCLE = "cycle"        # Restart from first loop


@dataclass
class AutoModeDNA:
    """Orchestrates a sequence of loops for autonomous operation.

    Usage:
        dna = AutoModeDNA(
            name="standard",
            loops=[AUTOPOIESIS_LOOP, GURU_LOOP],
            exit_behavior=ExitBehavior.CYCLE,
        )

        # Start auto mode
        dna.start(cave_agent)

        # On each hook pass, check for transitions
        dna.check_and_transition(cave_agent)
    """
    name: str
    loops: List[AgentInferenceLoop] = field(default_factory=list)
    exit_behavior: ExitBehavior = ExitBehavior.ONE_SHOT

    # Runtime state
    current_index: int = 0
    active: bool = False

    @property
    def current_loop(self) -> Optional[AgentInferenceLoop]:
        """Get the currently active loop."""
        if not self.loops or self.current_index >= len(self.loops):
            return None
        return self.loops[self.current_index]

    def start(self, cave_agent: "CAVEAgent") -> Dict[str, Any]:
        """Start auto mode - activate first loop."""
        if not self.loops:
            return {"error": "No loops defined in DNA"}

        self.current_index = 0
        self.active = True

        loop = self.current_loop
        result = loop.activate(cave_agent)

        logger.info(f"DNA '{self.name}' started, activated loop '{loop.name}'")

        return {
            "dna": self.name,
            "status": "started",
            "current_loop": loop.name,
            "loop_result": result,
        }

    def stop(self, cave_agent: "CAVEAgent") -> Dict[str, Any]:
        """Stop auto mode - deactivate current loop."""
        loop = self.current_loop
        if loop:
            loop.deactivate(cave_agent)

        self.active = False

        logger.info(f"DNA '{self.name}' stopped")

        return {
            "dna": self.name,
            "status": "stopped",
        }

    def check_and_transition(self, cave_agent: "CAVEAgent") -> Dict[str, Any]:
        """Check exit condition and transition if needed.

        Call this on each hook pass to check for loop completion.
        Supports both string loop names and TransitionAction chains.
        """
        if not self.active:
            return {"status": "inactive"}

        loop = self.current_loop
        if not loop:
            return {"status": "no_loop"}

        state = cave_agent._hook_state

        # Check exit condition
        if not loop.check_exit(state):
            return {"status": "running", "loop": loop.name}

        # Exit condition met - transition
        logger.info(f"Loop '{loop.name}' exit condition met")
        loop.deactivate(cave_agent)

        # Determine next action
        next_target = loop.next
        transition_results = None
        
        if next_target is None:
            # No explicit next - advance to next in sequence
            self.current_index += 1
        
        elif isinstance(next_target, str):
            # Old behavior: find loop by name
            found_loop = self._find_loop(next_target)
            if found_loop:
                self.current_index = self.loops.index(found_loop)
            else:
                logger.warning(f"Next loop '{next_target}' not found, advancing index")
                self.current_index += 1
        
        else:
            # NEW: TransitionAction - execute the chain
            try:
                from sdna import ContextEngineeringLib, ActivateLoop
                
                lib = ContextEngineeringLib()
                
                # Execute the action chain (fail-fast)
                transition_results = next_target.execute_chain(lib)
                logger.info(f"Transition chain executed: {len(transition_results)} actions")
                
                # Find the final ActivateLoop in the chain (if any)
                final_loop_name = None
                current = next_target
                while current is not None:
                    if isinstance(current, ActivateLoop):
                        final_loop_name = current.loop_name
                    current = getattr(current, 'then', None)
                
                if final_loop_name:
                    found_loop = self._find_loop(final_loop_name)
                    if found_loop:
                        self.current_index = self.loops.index(found_loop)
                    else:
                        logger.warning(f"Final loop '{final_loop_name}' not in DNA, advancing index")
                        self.current_index += 1
                else:
                    # No ActivateLoop in chain, advance normally
                    self.current_index += 1
                    
            except RuntimeError as e:
                logger.error(f"Transition chain failed: {e}")
                self.active = False
                return {
                    "status": "chain_failed", 
                    "error": str(e),
                    "previous_loop": loop.name,
                }
            except ImportError as e:
                logger.error(f"SDNA not available for TransitionAction: {e}")
                self.current_index += 1

        # Check if we've completed all loops
        if self.current_index >= len(self.loops):
            if self.exit_behavior == ExitBehavior.CYCLE:
                logger.info(f"DNA '{self.name}' cycling back to start")
                self.current_index = 0
            else:
                logger.info(f"DNA '{self.name}' completed (one_shot)")
                self.active = False
                return {
                    "status": "completed",
                    "dna": self.name,
                    "transition_results": transition_results,
                }

        # Activate next loop
        next_loop = self.current_loop
        result = next_loop.activate(cave_agent)

        return {
            "status": "transitioned",
            "previous_loop": loop.name,
            "current_loop": next_loop.name,
            "loop_result": result,
            "transition_results": transition_results,
        }

    def _find_loop(self, name: str) -> Optional[AgentInferenceLoop]:
        """Find a loop by name in our list."""
        for loop in self.loops:
            if loop.name == name:
                return loop
        return None

    def get_status(self) -> Dict[str, Any]:
        """Get current DNA status."""
        return {
            "dna": self.name,
            "active": self.active,
            "exit_behavior": self.exit_behavior.value,
            "current_index": self.current_index,
            "current_loop": self.current_loop.name if self.current_loop else None,
            "total_loops": len(self.loops),
            "loop_names": [l.name for l in self.loops],
        }


def create_dna(
    name: str,
    loop_names: List[str],
    exit_behavior: str = "one_shot",
) -> AutoModeDNA:
    """Factory to create DNA from loop names.

    Args:
        name: DNA identifier
        loop_names: List of loop names from AVAILABLE_LOOPS
        exit_behavior: "one_shot" or "cycle"
    """
    loops = []
    for loop_name in loop_names:
        if loop_name in AVAILABLE_LOOPS:
            loops.append(AVAILABLE_LOOPS[loop_name])
        else:
            logger.warning(f"Loop '{loop_name}' not found in AVAILABLE_LOOPS")

    return AutoModeDNA(
        name=name,
        loops=loops,
        exit_behavior=ExitBehavior(exit_behavior),
    )
