"""Mode rule evaluation with a constrained expression language."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from eqorch.domain.policy import ModeRule


@dataclass(slots=True, frozen=True)
class ModeEvaluationResult:
    target_mode: str | None
    reason: str | None
    matched_rule: ModeRule | None
    notes: tuple[str, ...]


class ModeRuleEvaluator:
    """Evaluates mode-switch conditions against a small safe expression subset."""

    def evaluate(self, rules: tuple[ModeRule, ...], context: dict[str, Any], notes: tuple[str, ...] = ()) -> ModeEvaluationResult:
        for rule in rules:
            if self._evaluate_condition(rule.condition, context):
                return ModeEvaluationResult(
                    target_mode=rule.target_mode,
                    reason=rule.reason,
                    matched_rule=rule,
                    notes=notes,
                )
        return ModeEvaluationResult(target_mode=None, reason=None, matched_rule=None, notes=notes)

    def _evaluate_condition(self, condition: str, context: dict[str, Any]) -> bool:
        try:
            expression = ast.parse(condition, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"invalid mode rule condition: {condition}") from exc
        return bool(self._eval_node(expression.body, context))

    def _eval_node(self, node: ast.AST, context: dict[str, Any]) -> Any:
        if isinstance(node, ast.BoolOp):
            values = [self._eval_node(value, context) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._eval_node(node.operand, context)
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)
                if isinstance(op, ast.Eq):
                    ok = left == right
                elif isinstance(op, ast.NotEq):
                    ok = left != right
                elif isinstance(op, ast.Gt):
                    ok = left > right
                elif isinstance(op, ast.GtE):
                    ok = left >= right
                elif isinstance(op, ast.Lt):
                    ok = left < right
                elif isinstance(op, ast.LtE):
                    ok = left <= right
                elif isinstance(op, ast.In):
                    ok = left in right
                elif isinstance(op, ast.NotIn):
                    ok = left not in right
                else:
                    raise ValueError("unsupported comparison in mode rule")
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Name):
            if node.id not in context:
                raise ValueError(f"unknown mode rule variable: {node.id}")
            return context[node.id]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [self._eval_node(element, context) for element in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(element, context) for element in node.elts)
        raise ValueError("unsupported expression in mode rule")
