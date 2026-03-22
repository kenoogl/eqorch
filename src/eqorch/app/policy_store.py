"""Policy loading and normalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import tomllib

import yaml

from eqorch.domain.policy import ModeRule, PolicyContext, RetryPolicy, TriggerThresholds


class PolicyLoadError(ValueError):
    """Raised when a policy file or patch is invalid."""


@dataclass(slots=True, frozen=True)
class PolicyRevision:
    revision_id: int
    source: str
    status: str
    summary: str
    patch: dict[str, Any] | None = None


class PolicyContextStore:
    """Loads, validates, and updates PolicyContext instances."""

    def __init__(self, initial_policy: PolicyContext | None = None) -> None:
        self._current = initial_policy
        self._pending: PolicyContext | None = None
        self._history: list[PolicyRevision] = []
        self._next_revision_id = 1

    @property
    def current(self) -> PolicyContext | None:
        return self._current

    @property
    def pending(self) -> PolicyContext | None:
        return self._pending

    @property
    def history(self) -> tuple[PolicyRevision, ...]:
        return tuple(self._history)

    def load_file(self, path: str | Path) -> PolicyContext:
        try:
            policy = self._parse_path(Path(path))
        except PolicyLoadError as exc:
            self._record_revision(
                source="file",
                status="rejected",
                summary=f"failed to load policy file: {exc}",
            )
            raise
        self._current = policy
        self._pending = None
        self._record_revision(
            source="file",
            status="applied",
            summary="loaded policy file",
        )
        return policy

    def apply_patch(self, patch: dict[str, Any], source: str = "update_policy") -> PolicyContext:
        if self._current is None:
            raise PolicyLoadError("cannot apply patch without an existing policy")
        try:
            merged = _deep_merge(_policy_to_raw(self._current), patch)
            policy = self._normalize(merged)
        except PolicyLoadError as exc:
            self._record_revision(
                source=source,
                status="rejected",
                summary=f"failed to stage policy patch: {exc}",
                patch=patch,
            )
            raise
        self._pending = policy
        self._record_revision(
            source=source,
            status="staged",
            summary="staged policy patch for next cycle",
            patch=patch,
        )
        return policy

    def activate_pending(self) -> PolicyContext | None:
        if self._pending is None:
            return None
        self._current = self._pending
        self._pending = None
        self._record_revision(
            source="activation",
            status="applied",
            summary="activated staged policy for current cycle",
        )
        return self._current

    def _parse_path(self, path: Path) -> PolicyContext:
        suffix = path.suffix.lower()
        content = path.read_text(encoding="utf-8")

        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(content)
        elif suffix == ".toml":
            data = tomllib.loads(content)
        elif suffix in {".md", ".markdown"}:
            data = self._parse_markdown(content)
        else:
            raise PolicyLoadError(f"unsupported policy format: {suffix}")

        if not isinstance(data, dict):
            raise PolicyLoadError("policy file must contain an object")
        return self._normalize(data)

    def _record_revision(
        self,
        source: str,
        status: str,
        summary: str,
        patch: dict[str, Any] | None = None,
    ) -> None:
        self._history.append(
            PolicyRevision(
                revision_id=self._next_revision_id,
                source=source,
                status=status,
                summary=summary,
                patch=patch,
            )
        )
        self._next_revision_id += 1

    def _parse_markdown(self, content: str) -> dict[str, Any]:
        frontmatter = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)
        if frontmatter:
            data = yaml.safe_load(frontmatter.group(1))
            if isinstance(data, dict):
                return data

        fenced = re.search(r"```(yaml|yml|toml)\n(.*?)\n```", content, re.DOTALL)
        if not fenced:
            raise PolicyLoadError("markdown policy must contain YAML/TOML frontmatter or fenced block")
        kind = fenced.group(1)
        body = fenced.group(2)
        if kind in {"yaml", "yml"}:
            data = yaml.safe_load(body)
        else:
            data = tomllib.loads(body)
        if not isinstance(data, dict):
            raise PolicyLoadError("markdown policy must decode to an object")
        return data

    def _normalize(self, raw: dict[str, Any]) -> PolicyContext:
        try:
            goals = tuple(_ensure_string_list(raw.get("goals"), "goals", required=True))
            constraints = tuple(_ensure_string_list(raw.get("constraints", []), "constraints"))
            forbidden_operations = tuple(
                _ensure_string_list(raw.get("forbidden_operations", []), "forbidden_operations")
            )
            strategy = raw.get("exploration_strategy", "expand")
            mode_switch = raw.get("mode_switch_criteria", {}) or {}
            rules = tuple(self._normalize_mode_rules(mode_switch.get("rules", [])))
            notes = tuple(_ensure_string_list(mode_switch.get("notes", []), "mode_switch_criteria.notes"))
            retry = self._normalize_retry(raw.get("retry", {}))
            triggers = self._normalize_triggers(raw.get("triggers", {}))

            return PolicyContext(
                goals=goals,
                constraints=constraints,
                forbidden_operations=forbidden_operations,
                exploration_strategy=strategy,
                mode_switch_criteria=rules,
                mode_switch_notes=notes,
                max_candidates=_positive_int(raw.get("max_candidates", 100), "max_candidates"),
                max_evaluations=_positive_int(raw.get("max_evaluations", 500), "max_evaluations"),
                max_memory_entries=_positive_int(raw.get("max_memory_entries", 1000), "max_memory_entries"),
                max_parallel_actions=_positive_int(raw.get("max_parallel_actions", 8), "max_parallel_actions"),
                llm_context_steps=_positive_int(raw.get("llm_context_steps", 20), "llm_context_steps"),
                triggers=triggers,
                retry=retry,
            )
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(str(exc)) from exc

    def _normalize_retry(self, raw: dict[str, Any] | None) -> RetryPolicy:
        raw = raw or {}
        if not isinstance(raw, dict):
            raise PolicyLoadError("retry must be an object")
        excluded = raw.get("excluded_types", ("ask_user", "switch_mode", "terminate"))
        return RetryPolicy(
            max_retries=_non_negative_int(raw.get("max_retries", 3), "retry.max_retries"),
            retry_interval_sec=_non_negative_int(
                raw.get("retry_interval_sec", 5),
                "retry.retry_interval_sec",
            ),
            excluded_types=tuple(_ensure_string_list(excluded, "retry.excluded_types", required=True)),
        )

    def _normalize_triggers(self, raw: dict[str, Any] | None) -> TriggerThresholds:
        raw = raw or {}
        if not isinstance(raw, dict):
            raise PolicyLoadError("triggers must be an object")
        return TriggerThresholds(
            stagnation_threshold=_non_negative_int(
                raw.get("stagnation_threshold", 1),
                "triggers.stagnation_threshold",
            ),
            diversity_threshold=_non_negative_int(
                raw.get("diversity_threshold", 1),
                "triggers.diversity_threshold",
            ),
        )

    def _normalize_mode_rules(self, raw_rules: Any) -> list[ModeRule]:
        if not isinstance(raw_rules, list):
            raise PolicyLoadError("mode_switch_criteria.rules must be a list")
        rules: list[ModeRule] = []
        for raw_rule in raw_rules:
            if not isinstance(raw_rule, dict):
                raise PolicyLoadError("mode rule must be an object")
            rules.append(
                ModeRule(
                    condition=str(raw_rule["condition"]),
                    target_mode=raw_rule["target_mode"],
                    reason=str(raw_rule["reason"]),
                )
            )
        return rules


def _ensure_string_list(value: Any, field_name: str, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name} must contain non-empty strings")
        normalized.append(item)
    if required and not normalized:
        raise ValueError(f"{field_name} must contain at least one entry")
    return normalized


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _policy_to_raw(policy: PolicyContext) -> dict[str, Any]:
    return {
        "goals": list(policy.goals),
        "constraints": list(policy.constraints),
        "forbidden_operations": list(policy.forbidden_operations),
        "exploration_strategy": policy.exploration_strategy,
        "mode_switch_criteria": {
            "rules": [
                {
                    "condition": rule.condition,
                    "target_mode": rule.target_mode,
                    "reason": rule.reason,
                }
                for rule in policy.mode_switch_criteria
            ],
            "notes": list(policy.mode_switch_notes),
        },
        "max_candidates": policy.max_candidates,
        "max_evaluations": policy.max_evaluations,
        "max_memory_entries": policy.max_memory_entries,
        "max_parallel_actions": policy.max_parallel_actions,
        "llm_context_steps": policy.llm_context_steps,
        "triggers": {
            "stagnation_threshold": policy.triggers.stagnation_threshold,
            "diversity_threshold": policy.triggers.diversity_threshold,
        },
        "retry": {
            "max_retries": policy.retry.max_retries,
            "retry_interval_sec": policy.retry.retry_interval_sec,
            "excluded_types": list(policy.retry.excluded_types),
        },
    }


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
