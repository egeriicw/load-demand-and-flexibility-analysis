"""Structural validation for the analysis configuration.

Runs before any data is loaded. Produces a list of findings with severity
``INFO`` / ``WARNING`` / ``ERROR``; any ``ERROR`` finding means the config is
invalid and should abort the run with a readable multi-line message.

This module intentionally does no expression evaluation or dynamic code
execution — it only inspects the plain dict produced by ``tomllib.load``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITIES = ("INFO", "WARNING", "ERROR")


@dataclass
class ConfigIssue:
    severity: str  # "INFO" | "WARNING" | "ERROR"
    path: str       # dotted key path, e.g. "data_quality.negative_demand_severity"
    message: str


@dataclass
class ConfigValidationReport:
    issues: list[ConfigIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.issues)

    @property
    def is_valid(self) -> bool:
        return not self.has_errors

    def __str__(self) -> str:
        if not self.issues:
            return "Configuration valid — no issues found."
        lines = [f"[{i.severity}] {i.path}: {i.message}" for i in self.issues]
        return "\n".join(lines)


class ConfigValidationError(ValueError):
    """Raised when a ConfigValidationReport contains one or more ERROR issues."""

    def __init__(self, report: ConfigValidationReport):
        self.report = report
        super().__init__(f"Configuration validation failed:\n{report}")


def _add(
    report: ConfigValidationReport, severity: str, path: str, message: str
) -> None:
    report.issues.append(ConfigIssue(severity=severity, path=path, message=message))


def _detect_meter_group_cycles(group_children: dict[str, list[str]]) -> list[str]:
    """
    DFS cycle detection over a group -> child-group-names adjacency map.

    Parameters
    ----------
    group_children : dict[str, list[str]]
        Maps each group name to the names of the *other groups* it
        references as children (member meter_ids are irrelevant here).

    Returns
    -------
    list[str]
        Names of the groups forming the first cycle found, in traversal
        order (empty list if the graph is acyclic).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {name: WHITE for name in group_children}
    path: list[str] = []

    def visit(name: str) -> list[str] | None:
        color[name] = GRAY
        path.append(name)
        for child in group_children.get(name, []):
            if child not in color:
                continue  # unknown reference — reported separately, not a cycle
            if color[child] == GRAY:
                cycle_start = path.index(child)
                return path[cycle_start:] + [child]
            if color[child] == WHITE:
                found = visit(child)
                if found is not None:
                    return found
        path.pop()
        color[name] = BLACK
        return None

    for name in group_children:
        if color[name] == WHITE:
            found = visit(name)
            if found is not None:
                return found
    return []


def _validate_input_section(cfg: dict[str, Any], report: ConfigValidationReport) -> None:
    unit = cfg.get("input", {}).get("unit", "kW")
    if unit not in ("kW", "kWh"):
        _add(report, "ERROR", "input.unit", f"must be 'kW' or 'kWh', got {unit!r}")


def _validate_data_quality_section(
    cfg: dict[str, Any], report: ConfigValidationReport
) -> None:
    dq = cfg.get("data_quality", {})

    gap = dq.get("max_interpolation_gap_minutes", 60)
    if not isinstance(gap, (int, float)) or gap < 0:
        _add(
            report, "ERROR", "data_quality.max_interpolation_gap_minutes",
            f"must be a non-negative number, got {gap!r}",
        )

    frac = dq.get("min_completeness_fraction", 0.75)
    if not isinstance(frac, (int, float)) or not (0.0 <= frac <= 1.0):
        _add(
            report, "ERROR", "data_quality.min_completeness_fraction",
            f"must be between 0 and 1, got {frac!r}",
        )

    severity = dq.get("negative_demand_severity", "ERROR")
    if severity not in SEVERITIES:
        _add(
            report, "ERROR", "data_quality.negative_demand_severity",
            f"must be one of {SEVERITIES}, got {severity!r}",
        )


def _validate_weight_sums(cfg: dict[str, Any], report: ConfigValidationReport) -> None:
    for section in ("start_detection", "end_detection"):
        weights = {
            k: v for k, v in cfg.get(section, {}).items() if k.startswith("weight_")
        }
        if not weights:
            continue
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            _add(
                report, "WARNING", f"{section}.weight_*",
                f"scoring weights sum to {total:.4f}, expected 1.0",
            )


def _validate_meters_section(cfg: dict[str, Any], report: ConfigValidationReport) -> None:
    meters = cfg.get("meters", [])
    if not meters:
        _add(report, "WARNING", "meters", "no [[meters]] configured — DER multi-meter pipeline is inert")
        return

    seen: set[str] = set()
    for i, m in enumerate(meters):
        meter_id = m.get("meter_id")
        if not meter_id:
            _add(report, "ERROR", f"meters[{i}]", "missing required 'meter_id'")
            continue
        if meter_id in seen:
            _add(report, "ERROR", f"meters[{i}].meter_id", f"duplicate meter_id '{meter_id}'")
        seen.add(meter_id)


def _validate_meter_groups_section(cfg: dict[str, Any], report: ConfigValidationReport) -> None:
    known_meters = {m.get("meter_id") for m in cfg.get("meters", [])}
    groups = cfg.get("meter_groups", [])
    known_groups: set[str] = set()

    for i, g in enumerate(groups):
        name = g.get("name")
        if not name:
            _add(report, "ERROR", f"meter_groups[{i}]", "missing required 'name'")
            continue
        if name in known_groups:
            _add(report, "ERROR", f"meter_groups[{i}].name", f"duplicate group name '{name}'")
        known_groups.add(name)

    for i, g in enumerate(groups):
        name = g.get("name", f"<unnamed[{i}]>")
        for meter_id in g.get("meters", []):
            if meter_id not in known_meters:
                _add(
                    report, "ERROR", f"meter_groups[{i}].meters",
                    f"group '{name}' references unknown meter_id '{meter_id}'",
                )
        for child in g.get("child_groups", []):
            if child == name:
                _add(
                    report, "ERROR", f"meter_groups[{i}].child_groups",
                    f"group '{name}' cannot list itself as a child_group",
                )
            elif child not in known_groups:
                _add(
                    report, "ERROR", f"meter_groups[{i}].child_groups",
                    f"group '{name}' references unknown child_group '{child}'",
                )

    child_map = {g.get("name"): g.get("child_groups", []) for g in groups if g.get("name")}
    cycle = _detect_meter_group_cycles(child_map)
    if cycle:
        _add(
            report, "ERROR", "meter_groups",
            f"cyclic child_groups reference: {' -> '.join(cycle)}",
        )


def _validate_portfolio_section(cfg: dict[str, Any], report: ConfigValidationReport) -> None:
    known_meters = {m.get("meter_id") for m in cfg.get("meters", [])}
    excluded = cfg.get("portfolio", {}).get("excluded_meters", [])
    for meter_id in excluded:
        if meter_id not in known_meters:
            _add(
                report, "ERROR", "portfolio.excluded_meters",
                f"references unknown meter_id '{meter_id}'",
            )


def validate_config(cfg: dict[str, Any]) -> ConfigValidationReport:
    """
    Run structural validation over the full configuration dict.

    Purely structural — never touches the actual data file. Data-content
    validation (``data_ingestion.validate_input``) is a separate, later step.
    """
    report = ConfigValidationReport()
    if not isinstance(cfg, dict):
        _add(report, "ERROR", "<root>", f"config must be a dict, got {type(cfg)!r}")
        return report

    _validate_input_section(cfg, report)
    _validate_data_quality_section(cfg, report)
    _validate_weight_sums(cfg, report)
    _validate_meters_section(cfg, report)
    _validate_meter_groups_section(cfg, report)
    _validate_portfolio_section(cfg, report)

    return report
