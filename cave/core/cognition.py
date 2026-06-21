"""Durable cognitive spaces and reified AgentInferenceLoop shapes.

This module gives CAVE a provider-neutral way to make an agent's current
inference loop inspectable by code, hooks, and MCP-style tools. The durable
object is a JSON cognitive space: it has a stable path, mutable KV state, and
verification gates that a Stop hook can report without forcing an unbounded
agent loop.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .hooks import CodeAgentHook, HookDecision, HookResult, HookType


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


def _make_id(prefix: str, name: str | None = None) -> str:
    raw = (name or prefix).strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-") or prefix
    return f"{prefix}-{slug}-{uuid.uuid4().hex[:8]}"


def _deep_get(data: Mapping[str, Any], key: str) -> tuple[bool, Any]:
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


@dataclass
class ReifiedAgentInferenceLoop:
    """Persisted, tool-addressable description of an AgentInferenceLoop shape."""

    id: str
    name: str
    description: str = ""
    provider: str = "codex"
    prompt: str = ""
    output_override: Optional[Dict[str, Any]] = None
    active_hooks: Dict[str, List[str]] = field(default_factory=dict)
    phase_graph: Dict[str, Any] = field(default_factory=dict)
    required_files: List[str] = field(default_factory=list)
    kv_defaults: Dict[str, Any] = field(default_factory=dict)
    verification_gates: List[Any] = field(default_factory=list)
    exit_policy: Dict[str, Any] = field(default_factory=dict)
    next: Optional[str] = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class CognitiveSpace:
    """Durable current-state object that any cog can load and mutate."""

    id: str
    name: str
    provider: str = "codex"
    loop_id: Optional[str] = None
    phase: str = "observe"
    active_shape: Dict[str, Any] = field(default_factory=dict)
    prompt_path: Optional[str] = None
    kv: Dict[str, Any] = field(default_factory=dict)
    evidence_files: List[str] = field(default_factory=list)
    verification_gates: List[Any] = field(default_factory=list)
    stop_conditions: Dict[str, Any] = field(default_factory=lambda: {
        "mode": "advisory",
        "strict": False,
    })
    next_action: Optional[str] = None
    status: str = "active"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class CognitionStore:
    """Filesystem-backed cognitive-space and loop-shape store."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "cognition"
        self.spaces_dir = self.root / "spaces"
        self.loops_dir = self.root / "loops"
        self.current_path = self.root / "current.json"
        self.spaces_dir.mkdir(parents=True, exist_ok=True)
        self.loops_dir.mkdir(parents=True, exist_ok=True)

    def loop_path(self, loop_id: str) -> Path:
        return self.loops_dir / f"{loop_id}.json"

    def space_path(self, space_id: str) -> Path:
        return self.spaces_dir / f"{space_id}.json"

    def create_loop_shape(
        self,
        *,
        name: str,
        description: str = "",
        provider: str = "codex",
        prompt: str = "",
        output_override: Optional[Dict[str, Any]] = None,
        active_hooks: Optional[Dict[str, List[str]]] = None,
        phase_graph: Optional[Dict[str, Any]] = None,
        required_files: Optional[Iterable[str]] = None,
        kv_defaults: Optional[Dict[str, Any]] = None,
        verification_gates: Optional[List[Any]] = None,
        exit_policy: Optional[Dict[str, Any]] = None,
        next: Optional[str] = None,
        loop_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        loop = ReifiedAgentInferenceLoop(
            id=loop_id or _make_id("loop", name),
            name=name,
            description=description,
            provider=provider,
            prompt=prompt,
            output_override=output_override,
            active_hooks=active_hooks or {},
            phase_graph=phase_graph or {},
            required_files=list(required_files or []),
            kv_defaults=kv_defaults or {},
            verification_gates=verification_gates or [],
            exit_policy=exit_policy or {},
            next=next,
        )
        payload = asdict(loop)
        self._write_json(self.loop_path(loop.id), payload)
        return self._with_path(payload, self.loop_path(loop.id))

    def load_loop(self, loop_id: str) -> Dict[str, Any]:
        return self._with_path(self._read_json(self.loop_path(loop_id)), self.loop_path(loop_id))

    def create_space(
        self,
        *,
        name: str = "cognitive_space",
        provider: str = "codex",
        loop_id: Optional[str] = None,
        phase: str = "observe",
        active_shape: Optional[Dict[str, Any]] = None,
        prompt_path: Optional[str | Path] = None,
        kv: Optional[Dict[str, Any]] = None,
        evidence_files: Optional[Iterable[str | Path]] = None,
        verification_gates: Optional[List[Any]] = None,
        stop_conditions: Optional[Dict[str, Any]] = None,
        next_action: Optional[str] = None,
        set_current: bool = True,
        space_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        loop: Optional[Dict[str, Any]] = None
        if loop_id:
            loop = self.load_loop(loop_id)

        merged_kv: Dict[str, Any] = {}
        if loop:
            merged_kv.update(loop.get("kv_defaults", {}))
        merged_kv.update(kv or {})

        if active_shape is None and loop:
            active_shape = {
                "loop_id": loop["id"],
                "loop_name": loop["name"],
                "phase_graph": loop.get("phase_graph", {}),
                "output_override": loop.get("output_override"),
            }

        gates = verification_gates
        if gates is None and loop:
            gates = loop.get("verification_gates", [])

        space = CognitiveSpace(
            id=space_id or _make_id("space", name),
            name=name,
            provider=provider,
            loop_id=loop_id,
            phase=phase,
            active_shape=active_shape or {},
            prompt_path=str(prompt_path) if prompt_path else None,
            kv=merged_kv,
            evidence_files=[str(path) for path in evidence_files or []],
            verification_gates=gates or [],
            stop_conditions=stop_conditions or {"mode": "advisory", "strict": False},
            next_action=next_action,
        )
        payload = asdict(space)
        self._write_json(self.space_path(space.id), payload)
        if set_current:
            self.set_current_space(space.id)
        return self._with_path(payload, self.space_path(space.id))

    def load_space(self, space_id: str) -> Dict[str, Any]:
        return self._with_path(self._read_json(self.space_path(space_id)), self.space_path(space_id))

    def get_current_space(self, *, required: bool = False) -> Optional[Dict[str, Any]]:
        if not self.current_path.exists():
            if required:
                raise FileNotFoundError("No current cognitive space is set")
            return None
        pointer = self._read_json(self.current_path)
        space_id = pointer.get("space_id")
        if not space_id:
            if required:
                raise FileNotFoundError("Current cognitive-space pointer has no space_id")
            return None
        return self.load_space(space_id)

    def set_current_space(self, space_id: str) -> Dict[str, Any]:
        space = self.load_space(space_id)
        pointer = {
            "space_id": space_id,
            "path": space["path"],
            "updated_at": _now(),
        }
        self._write_json(self.current_path, pointer)
        return pointer

    def put_kv(
        self,
        *,
        space_id: Optional[str] = None,
        key: Optional[str] = None,
        value: Any = None,
        updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        space = self.load_space(space_id) if space_id else self.get_current_space(required=True)
        if updates is None:
            if key is None:
                raise ValueError("put_kv requires either updates or key")
            updates = {key: value}

        space.setdefault("kv", {}).update(updates)
        space["updated_at"] = _now()
        self._write_json(self.space_path(space["id"]), space)
        return self.load_space(space["id"])

    def add_evidence_file(self, *, space_id: Optional[str] = None, path: str | Path) -> Dict[str, Any]:
        space = self.load_space(space_id) if space_id else self.get_current_space(required=True)
        evidence = space.setdefault("evidence_files", [])
        path_str = str(path)
        if path_str not in evidence:
            evidence.append(path_str)
        space["updated_at"] = _now()
        self._write_json(self.space_path(space["id"]), space)
        return self.load_space(space["id"])

    def stop_check(
        self,
        *,
        space_id: Optional[str] = None,
        hook_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        dna_check = self._dna_sequence_stop_check()
        try:
            space = self.load_space(space_id) if space_id else self.get_current_space(required=True)
        except FileNotFoundError:
            check = {
                "ok": dna_check.get("ok", True),
                "blocked": dna_check.get("blocked", False),
                "result": "block" if dna_check.get("blocked") else "continue",
                "current_space": None,
                "current_space_path": None,
                "missing_gates": [],
                "passed_gates": [],
                "optional_missing_gates": [],
                "dna_sequence": dna_check,
                "hook_payload_seen": bool(hook_payload),
            }
            check["additionalContext"] = self.format_stop_context(check)
            return check

        missing: list[Dict[str, Any]] = []
        optional_missing: list[Dict[str, Any]] = []
        passed: list[Dict[str, Any]] = []
        for index, gate in enumerate(space.get("verification_gates", [])):
            result = self._evaluate_gate(gate, space, index)
            if result["passed"]:
                passed.append(result)
            elif result["required"]:
                missing.append(result)
            else:
                optional_missing.append(result)

        conditions = space.get("stop_conditions", {})
        strict = bool(
            conditions.get("strict")
            or conditions.get("block_on_missing_gates")
            or conditions.get("mode") == "blocking"
        )
        blocked = (strict and bool(missing)) or dna_check.get("blocked", False)
        check = {
            "ok": not missing and dna_check.get("ok", True),
            "blocked": blocked,
            "result": "block" if blocked else "continue",
            "current_space": space["id"],
            "current_space_path": space["path"],
            "phase": space.get("phase"),
            "missing_gates": missing,
            "passed_gates": passed,
            "optional_missing_gates": optional_missing,
            "stop_conditions": conditions,
            "dna_sequence": dna_check,
            "hook_payload_seen": bool(hook_payload),
        }
        check["additionalContext"] = self.format_stop_context(check)
        return check

    def format_stop_context(self, check: Mapping[str, Any]) -> str:
        lines = []
        if not check.get("current_space_path"):
            lines.append("CAVE cognitive space: none active.")
        else:
            lines.extend([
                f"CAVE cognitive space: {check['current_space_path']}",
                f"CAVE cognition stop-check: {'green' if not check.get('missing_gates') else 'missing gates'}",
                f"CAVE cognition mode: {check.get('stop_conditions', {}).get('mode', 'advisory')}",
            ])

        missing = check.get("missing_gates", [])
        if missing:
            lines.append("Missing required gates:")
            for gate in missing:
                lines.append(f"- {gate['name']}: {gate['reason']}")
        passed = check.get("passed_gates", [])
        if passed:
            names = ", ".join(gate["name"] for gate in passed)
            lines.append(f"Passed gates: {names}")

        dna = check.get("dna_sequence") or {}
        if dna.get("active"):
            lines.extend([
                f"CAVE DNA sequence: {dna.get('path')}",
                f"CAVE DNA follow-through: {'green' if dna.get('ok') else 'incomplete'}",
                f"CAVE DNA mode: {dna.get('mode', 'advisory')}",
            ])
            next_step = dna.get("next_step")
            if next_step:
                lines.append(f"Next DNA step [{next_step.get('id')}]: {next_step.get('title')}")
                if next_step.get("prompt"):
                    lines.append(f"Next prompt: {next_step['prompt']}")
            missing_steps = dna.get("missing_steps") or []
            if missing_steps:
                lines.append("Incomplete required DNA steps:")
                for step in missing_steps[:5]:
                    lines.append(f"- {step.get('id')}: {step.get('title')} ({step.get('status')})")
        elif not check.get("current_space_path"):
            lines.append("CAVE stop-check: advisory and green.")
        return "\n".join(lines)

    def _dna_sequence_stop_check(self) -> Dict[str, Any]:
        try:
            from .dna import DNAConfigStore

            return DNAConfigStore(self.data_dir).sequence_stop_check()
        except Exception as exc:
            return {
                "active": False,
                "ok": True,
                "blocked": False,
                "error": str(exc),
                "missing_steps": [],
                "next_step": None,
            }

    def _evaluate_gate(self, gate: Any, space: Mapping[str, Any], index: int) -> Dict[str, Any]:
        normalized = self._normalize_gate(gate, index)
        gate_type = normalized["type"]
        required = normalized["required"]
        name = normalized["name"]

        if gate_type == "kv_truthy":
            key = normalized.get("key") or normalized.get("kv_key")
            found, value = _deep_get(space.get("kv", {}), key or "")
            passed = bool(found and value)
            reason = f"kv[{key!r}] is not truthy"
            return self._gate_result(normalized, passed, reason, required)

        if gate_type == "kv_present":
            key = normalized.get("key") or normalized.get("kv_key")
            found, _value = _deep_get(space.get("kv", {}), key or "")
            reason = f"kv[{key!r}] is missing"
            return self._gate_result(normalized, found, reason, required)

        if gate_type == "kv_equals":
            key = normalized.get("key") or normalized.get("kv_key")
            found, value = _deep_get(space.get("kv", {}), key or "")
            expected = normalized.get("expected")
            passed = found and value == expected
            reason = f"kv[{key!r}] != {expected!r}"
            return self._gate_result(normalized, passed, reason, required)

        if gate_type == "file_exists":
            raw_path = normalized.get("path") or normalized.get("file")
            path = self._resolve_check_path(raw_path)
            passed = path.exists()
            reason = f"file does not exist: {path}"
            result = self._gate_result(normalized, passed, reason, required)
            result["path"] = str(path)
            return result

        if gate_type == "evidence_file_exists":
            evidence_files = [self._resolve_check_path(path) for path in space.get("evidence_files", [])]
            missing = [path for path in evidence_files if not path.exists()]
            passed = bool(evidence_files) and not missing
            reason = "no evidence files are registered" if not evidence_files else f"missing evidence files: {[str(path) for path in missing]}"
            result = self._gate_result(normalized, passed, reason, required)
            result["paths"] = [str(path) for path in evidence_files]
            return result

        reason = f"unknown gate type: {gate_type}"
        return self._gate_result(normalized, False, reason, required)

    def _normalize_gate(self, gate: Any, index: int) -> Dict[str, Any]:
        if isinstance(gate, str):
            return {
                "name": gate,
                "type": "kv_truthy",
                "key": gate,
                "required": True,
            }
        normalized = dict(gate or {})
        normalized.setdefault("name", normalized.get("key") or normalized.get("path") or f"gate_{index}")
        normalized.setdefault("type", "kv_truthy")
        normalized.setdefault("required", True)
        return normalized

    def _gate_result(
        self,
        gate: Mapping[str, Any],
        passed: bool,
        reason: str,
        required: bool,
    ) -> Dict[str, Any]:
        return {
            "name": str(gate.get("name")),
            "type": str(gate.get("type")),
            "required": bool(required),
            "passed": bool(passed),
            "reason": "" if passed else reason,
        }

    def _resolve_check_path(self, raw_path: str | Path | None) -> Path:
        path = Path(raw_path or "")
        if path.is_absolute():
            return path
        return Path.cwd() / path

    def _read_json(self, path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text())

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n")

    def _with_path(self, payload: Mapping[str, Any], path: Path) -> Dict[str, Any]:
        data = dict(payload)
        data["path"] = str(path)
        return data


class CognitiveSpaceStopHook(CodeAgentHook):
    """Advisory-or-blocking Stop hook that returns the active cognition path."""

    hook_type = HookType.STOP

    def __init__(self, name: str = "cognitive_space_stop_check", data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else None
        super().__init__(name=name)

    def handle(self, payload: Dict[str, Any], state: Dict[str, Any]) -> HookResult:
        data_dir = (
            self.data_dir
            or state.get("cognition_data_dir")
            or os.environ.get("HEAVEN_DATA_DIR")
            or "/tmp/heaven_data"
        )
        store = CognitionStore(data_dir)
        check = store.stop_check(hook_payload=payload)
        if check.get("blocked"):
            return HookResult(
                HookDecision.BLOCK,
                reason="CAVE stop-check has unmet DNA sequence or cognitive-space gates",
                additional_context=check["additionalContext"],
                stop_reason="CAVE stop-check has unmet DNA sequence or cognitive-space gates",
                metadata={"cognition": check},
            )
        return HookResult(
            HookDecision.CONTINUE,
            additional_context=check["additionalContext"],
            metadata={"cognition": check},
        )


def render_cognitive_stop_hook(class_name: str = "CaveCognitiveSpaceStopHook") -> str:
    return (
        '"""CAVE cognitive-space Stop hook.\n\n'
        'Generated by CAVE cognition tooling. Returns the current cognitive-space\n'
        'path and verification-gate status to provider Stop hooks.\n'
        '"""\n'
        "from cave.core.cognition import CognitiveSpaceStopHook\n\n\n"
        f"class {class_name}(CognitiveSpaceStopHook):\n"
        "    pass\n"
    )


def write_cognitive_stop_hook(
    hook_dir: str | Path,
    *,
    filename: str = "cognitive_space_stop_check.py",
) -> Path:
    path = Path(hook_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_cognitive_stop_hook())
    return path
