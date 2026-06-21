"""AutoModeDNA - Orchestrates a sequence of AgentInferenceLoops.

DNA = a list of loops + cycle/one_shot behavior.
When in auto mode, DNA activates loops, checks exit conditions,
and transitions to next loop (or cycles/stops).
"""
import logging
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .loops import AgentInferenceLoop, AVAILABLE_LOOPS

if TYPE_CHECKING:
    from .cave_agent import CAVEAgent

logger = logging.getLogger(__name__)

DNA_REF_PREFIX = "dna:"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_dna_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(DNA_REF_PREFIX)


def _dna_ref_name(value: str) -> str:
    return value[len(DNA_REF_PREFIX):].strip()


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


@dataclass
class AutoModeDNAConfig:
    """Serializable DNA config that can be selected before runtime activation.

    `loop_names` is intentionally backward-compatible: entries can be normal
    AgentInferenceLoop names or nested DNA refs using `dna:<config_name>`.
    """

    name: str
    loop_names: List[str]
    exit_behavior: str = ExitBehavior.ONE_SHOT.value
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class DNASequenceStep:
    """One follow-through step in the current live DNA sequence."""

    id: str
    title: str
    prompt: str = ""
    status: str = "pending"
    required: bool = True
    completion_key: Optional[str] = None
    evidence_files: List[str] = field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class DNASequence:
    """Current live sequence that Stop hooks can enforce."""

    name: str
    steps: List[Dict[str, Any]]
    description: str = ""
    mode: str = "advisory"
    current_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class DNAConfigStore:
    """Filesystem-backed library of selectable AutoModeDNA configs."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "dna"
        self.configs_dir = self.root / "configs"
        self.current_path = self.root / "current.json"
        self.sequence_path = self.root / "sequence.json"
        self.configs_dir.mkdir(parents=True, exist_ok=True)

    def config_path(self, name: str) -> Path:
        return self.configs_dir / f"{self._safe_name(name)}.json"

    def create_config(
        self,
        *,
        name: str,
        loop_names: List[str],
        exit_behavior: str = ExitBehavior.ONE_SHOT.value,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        set_current: bool = False,
    ) -> Dict[str, Any]:
        self.resolve_loop_names(loop_names, seen=[name])

        config = AutoModeDNAConfig(
            name=name,
            description=description,
            loop_names=loop_names,
            exit_behavior=ExitBehavior(exit_behavior).value,
            metadata=metadata or {},
        )
        payload = asdict(config)
        path = self.config_path(name)
        self._write_json(path, payload)
        if set_current:
            self.select_config(name)
        return self._with_path(payload, path)

    def get_config(self, name: str) -> Dict[str, Any]:
        path = self.config_path(name)
        if not path.exists():
            raise FileNotFoundError(f"DNA config not found: {name}")
        return self._with_path(self._read_json(path), path)

    def list_configs(self) -> Dict[str, Any]:
        current = self.get_current_selection()
        configs = []
        for path in sorted(self.configs_dir.glob("*.json")):
            data = self._read_json(path)
            configs.append(self._with_path(data, path))
        return {
            "current": current,
            "count": len(configs),
            "configs": configs,
        }

    def select_config(self, name: str) -> Dict[str, Any]:
        config = self.get_config(name)
        pointer = {
            "name": config["name"],
            "path": config["path"],
            "updated_at": _now(),
        }
        self._write_json(self.current_path, pointer)
        return pointer

    def get_current_selection(self) -> Optional[Dict[str, Any]]:
        if not self.current_path.exists():
            return None
        return self._read_json(self.current_path)

    def get_current_config(self) -> Optional[Dict[str, Any]]:
        selection = self.get_current_selection()
        if not selection:
            return None
        return self.get_config(selection["name"])

    def build_dna(self, name: Optional[str] = None) -> AutoModeDNA:
        config = self.get_config(name) if name else self.get_current_config()
        if not config:
            raise FileNotFoundError("No AutoModeDNA config selected")
        resolved_loop_names = self.resolve_loop_names(
            config["loop_names"],
            seen=[config["name"]],
        )
        return create_dna(
            name=config["name"],
            loop_names=resolved_loop_names,
            exit_behavior=config["exit_behavior"],
            strict=True,
        )

    def resolve_loop_names(
        self,
        loop_names: List[str],
        *,
        seen: Optional[List[str]] = None,
    ) -> List[str]:
        """Resolve nested `dna:<config>` refs into a flat loop-name sequence."""
        trail = list(seen or [])
        seen_names = set(trail)
        resolved: List[str] = []
        unknown_loops: List[str] = []

        for entry in loop_names:
            if _is_dna_ref(entry):
                ref_name = _dna_ref_name(entry)
                if not ref_name:
                    raise ValueError(f"Invalid AutoModeDNA config reference: {entry!r}")
                if ref_name in seen_names:
                    chain = " -> ".join([*trail, ref_name])
                    raise ValueError(f"Recursive AutoModeDNA config reference detected: {chain}")
                try:
                    child_config = self.get_config(ref_name)
                except FileNotFoundError as exc:
                    raise ValueError(f"Unknown AutoModeDNA config references: {[ref_name]}") from exc
                resolved.extend(
                    self.resolve_loop_names(
                        child_config.get("loop_names", []),
                        seen=[*trail, ref_name],
                    )
                )
                continue

            if entry in AVAILABLE_LOOPS:
                resolved.append(entry)
            else:
                unknown_loops.append(entry)

        if unknown_loops:
            raise ValueError(f"Unknown AgentInferenceLoop names: {unknown_loops}")
        return resolved

    def set_sequence(
        self,
        *,
        steps: List[Any],
        name: str = "current",
        description: str = "",
        mode: str = "advisory",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Set the live follow-through sequence used by Stop hooks."""
        normalized_steps = [
            self._normalize_sequence_step(step, index)
            for index, step in enumerate(steps)
        ]
        sequence = DNASequence(
            name=name,
            description=description,
            mode=mode,
            steps=normalized_steps,
            metadata=metadata or {},
        )
        payload = asdict(sequence)
        self._write_json(self.sequence_path, payload)
        return self.get_sequence(required=True)

    def get_sequence(self, *, required: bool = False) -> Optional[Dict[str, Any]]:
        """Return the live DNA sequence, if one is set."""
        if not self.sequence_path.exists():
            if required:
                raise FileNotFoundError("No DNA sequence is set")
            return None
        sequence = self._with_path(self._read_json(self.sequence_path), self.sequence_path)
        sequence["next_step"] = self.get_next_step(sequence=sequence).get("next_step")
        return sequence

    def clear_sequence(self) -> Dict[str, Any]:
        """Clear the live DNA sequence."""
        existed = self.sequence_path.exists()
        if existed:
            self.sequence_path.unlink()
        return {
            "cleared": existed,
            "path": str(self.sequence_path),
        }

    def get_next_step(self, *, sequence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return the next incomplete step in the live DNA sequence."""
        sequence = sequence or self.get_sequence()
        if not sequence:
            return {
                "active": False,
                "ok": True,
                "path": str(self.sequence_path),
                "next_step": None,
                "completed_count": 0,
                "total_steps": 0,
            }

        steps = sequence.get("steps", [])
        next_step = None
        next_index = None
        for index, step in enumerate(steps):
            if step.get("status") not in ("completed", "skipped"):
                next_step = step
                next_index = index
                break

        completed_count = sum(1 for step in steps if step.get("status") in ("completed", "skipped"))
        return {
            "active": True,
            "ok": next_step is None,
            "path": sequence.get("path", str(self.sequence_path)),
            "name": sequence.get("name"),
            "mode": sequence.get("mode", "advisory"),
            "current_index": next_index,
            "next_step": next_step,
            "completed_count": completed_count,
            "total_steps": len(steps),
        }

    def complete_step(
        self,
        *,
        step_id: Optional[str] = None,
        status: str = "completed",
        summary: str = "",
        evidence_files: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Mark one step complete/skipped/in-progress and persist the sequence."""
        if status not in ("pending", "in_progress", "completed", "skipped"):
            raise ValueError(f"Invalid DNA sequence step status: {status}")

        sequence = self.get_sequence(required=True)
        next_info = self.get_next_step(sequence=sequence)
        target_id = step_id or (next_info.get("next_step") or {}).get("id")
        if not target_id:
            raise ValueError("No DNA sequence step to update")

        updated = False
        for index, step in enumerate(sequence.get("steps", [])):
            if step.get("id") == target_id:
                step["status"] = status
                if summary:
                    step["summary"] = summary
                if evidence_files:
                    existing = step.setdefault("evidence_files", [])
                    for path in evidence_files:
                        if path not in existing:
                            existing.append(path)
                if metadata:
                    step.setdefault("metadata", {}).update(metadata)
                step["updated_at"] = _now()
                sequence["current_index"] = min(index + 1, len(sequence.get("steps", [])))
                updated = True
                break

        if not updated:
            raise ValueError(f"DNA sequence step not found: {target_id}")

        sequence["updated_at"] = _now()
        sequence.pop("path", None)
        sequence.pop("next_step", None)
        self._write_json(self.sequence_path, sequence)
        return self.get_sequence(required=True)

    def sequence_stop_check(self) -> Dict[str, Any]:
        """Return Stop-hook enforcement state for the live sequence."""
        sequence = self.get_sequence()
        if not sequence:
            return {
                "active": False,
                "ok": True,
                "blocked": False,
                "path": str(self.sequence_path),
                "missing_steps": [],
                "next_step": None,
            }

        steps = sequence.get("steps", [])
        missing_steps = [
            step for step in steps
            if step.get("required", True) and step.get("status") != "completed"
        ]
        next_info = self.get_next_step(sequence=sequence)
        mode = sequence.get("mode", "advisory")
        strict = bool(mode in ("blocking", "strict") or sequence.get("enforce_completion"))
        blocked = strict and bool(missing_steps)

        return {
            "active": True,
            "ok": not missing_steps,
            "blocked": blocked,
            "path": sequence["path"],
            "name": sequence.get("name"),
            "mode": mode,
            "strict": strict,
            "missing_steps": missing_steps,
            "next_step": next_info.get("next_step"),
            "completed_count": next_info.get("completed_count", 0),
            "total_steps": next_info.get("total_steps", len(steps)),
        }

    def _normalize_sequence_step(self, step: Any, index: int) -> Dict[str, Any]:
        if isinstance(step, str):
            data = {"title": step, "prompt": step}
        else:
            data = dict(step or {})

        title = data.get("title") or data.get("name") or f"step_{index + 1}"
        normalized = DNASequenceStep(
            id=data.get("id") or self._safe_name(str(title)).lower() or f"step_{index + 1}",
            title=title,
            prompt=data.get("prompt", ""),
            status=data.get("status", "pending"),
            required=bool(data.get("required", True)),
            completion_key=data.get("completion_key"),
            evidence_files=list(data.get("evidence_files", [])),
            summary=data.get("summary", ""),
            metadata=dict(data.get("metadata", {})),
        )
        if normalized.status not in ("pending", "in_progress", "completed", "skipped"):
            raise ValueError(f"Invalid DNA sequence step status: {normalized.status}")
        return asdict(normalized)

    def _safe_name(self, name: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)

    def _read_json(self, path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text())

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def _with_path(self, payload: Dict[str, Any], path: Path) -> Dict[str, Any]:
        data = dict(payload)
        data["path"] = str(path)
        return data


def unknown_loop_names(loop_names: List[str]) -> List[str]:
    """Return loop names that are not in CAVE's available loop registry."""
    return [name for name in loop_names if name not in AVAILABLE_LOOPS]


def create_dna(
    name: str,
    loop_names: List[str],
    exit_behavior: str = "one_shot",
    strict: bool = False,
) -> AutoModeDNA:
    """Factory to create DNA from loop names.

    Args:
        name: DNA identifier
        loop_names: List of loop names from AVAILABLE_LOOPS
        exit_behavior: "one_shot" or "cycle"
    """
    missing = unknown_loop_names(loop_names)
    if missing and strict:
        raise ValueError(f"Unknown AgentInferenceLoop names: {missing}")

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
