"""Body interface between physical world outputs and brain input neurons."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(slots=True)
class BodyMapping:
    target: str
    source: str
    min_value: float = 0.0
    max_value: float = 1.0
    formula: str = "linear"
    clamp: bool = True
    rounding: str = "round"
    threshold: float = 0.5


@dataclass(slots=True)
class BodyTranslation:
    target: str
    source: str
    value: float
    normalized: float
    count: int
    indices: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "source": self.source,
            "value": self.value,
            "normalized": self.normalized,
            "count": self.count,
            "indices": list(self.indices),
        }


class Body:
    """Translate physical observables into active brain input neuron groups."""

    def __init__(self, mappings: Sequence[BodyMapping]) -> None:
        self.mappings = list(mappings)
        self._by_target = {mapping.target: mapping for mapping in self.mappings}

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any] | None) -> Body:
        ok, problems = cls.Validate(cfg)
        if not ok:
            raise ValueError("; ".join(problems))
        raw_mappings = _raw_mappings(cfg)
        mappings: list[BodyMapping] = []
        for raw in raw_mappings:
            target = str(raw.get("target", raw.get("input", ""))).strip()
            source = str(raw.get("source", target)).strip()
            formula = str(raw.get("formula", "linear")).strip().lower()
            min_value = float(raw.get("min", raw.get("min_value", 0.0)))
            max_value = float(raw.get("max", raw.get("max_value", 1.0)))
            mappings.append(BodyMapping(
                target=target,
                source=source,
                min_value=min_value,
                max_value=max_value,
                formula=formula,
                clamp=bool(raw.get("clamp", True)),
                rounding=str(raw.get("rounding", "round")).strip().lower(),
                threshold=float(raw.get("threshold", 0.5)),
            ))
        return cls(mappings)

    @staticmethod
    def Validate(
        cfg: Mapping[str, Any] | None,
        *,
        brain_inputs: set[str] | None = None,
        world_outputs: set[str] | None = None,
    ) -> tuple[bool, list[str]]:
        problems: list[str] = []
        if cfg is None:
            return False, ["body section is required"]
        if not isinstance(cfg, Mapping):
            return False, ["body must be a mapping"]
        raw_mappings = _raw_mappings(cfg)
        if not raw_mappings:
            problems.append("body.mappings must contain at least one mapping")

        seen_targets: set[str] = set()
        formulas = {"linear", "inverse_linear", "threshold"}
        roundings = {"round", "floor", "ceil"}
        for idx, raw in enumerate(raw_mappings):
            prefix = f"body.mappings[{idx}]"
            if not isinstance(raw, Mapping):
                problems.append(f"{prefix} must be a mapping")
                continue
            target = str(raw.get("target", raw.get("input", ""))).strip()
            source = str(raw.get("source", target)).strip()
            if not target:
                problems.append(f"{prefix}.target is required")
            elif target in seen_targets:
                problems.append(f"{prefix}.target {target!r} is duplicated")
            seen_targets.add(target)
            if not source:
                problems.append(f"{prefix}.source is required")
            formula = str(raw.get("formula", "linear")).strip().lower()
            if formula not in formulas:
                problems.append(f"{prefix}.formula must be one of: {', '.join(sorted(formulas))}")
            rounding = str(raw.get("rounding", "round")).strip().lower()
            if rounding not in roundings:
                problems.append(f"{prefix}.rounding must be one of: {', '.join(sorted(roundings))}")
            try:
                min_value = float(raw.get("min", raw.get("min_value", 0.0)))
                max_value = float(raw.get("max", raw.get("max_value", 1.0)))
            except (TypeError, ValueError):
                problems.append(f"{prefix}.min and {prefix}.max must be numeric")
            else:
                if formula != "threshold" and min_value == max_value:
                    problems.append(f"{prefix}.min and {prefix}.max must be different")

        if brain_inputs is not None:
            missing = sorted(seen_targets - brain_inputs)
            if missing:
                problems.append(f"body targets missing from brain inputs: {', '.join(missing)}")
        if world_outputs is not None:
            sources = {
                str(raw.get("source", raw.get("target", raw.get("input", "")))).strip()
                for raw in raw_mappings
                if isinstance(raw, Mapping)
            }
            missing = sorted(source for source in sources if source and source not in world_outputs)
            if missing:
                problems.append(f"body sources missing from world outputs: {', '.join(missing)}")
        return not problems, problems

    def mapping_for_target(self, target: str) -> BodyMapping | None:
        return self._by_target.get(target)

    def translate(
        self,
        physical_outputs: Mapping[str, Any],
        input_specs: Sequence[Mapping[str, Any]],
    ) -> dict[str, BodyTranslation]:
        input_by_name = {str(spec.get("name", "")): spec for spec in input_specs}
        translations: dict[str, BodyTranslation] = {}
        for mapping in self.mappings:
            spec = input_by_name.get(mapping.target)
            if spec is None or mapping.source not in physical_outputs:
                continue
            value = float(physical_outputs[mapping.source])
            translations[mapping.target] = self.translate_value(mapping, value, spec)
        return translations

    def translate_value(
        self,
        mapping: BodyMapping,
        value: float,
        input_spec: Mapping[str, Any],
    ) -> BodyTranslation:
        indices = [int(idx) for idx in input_spec.get("indices", [])]
        normalized = self._normalized(mapping, float(value))
        count = self._count(normalized, len(indices), mapping.rounding)
        return BodyTranslation(
            target=mapping.target,
            source=mapping.source,
            value=float(value),
            normalized=normalized,
            count=count,
            indices=indices[:count],
        )

    def _normalized(self, mapping: BodyMapping, value: float) -> float:
        if mapping.formula == "threshold":
            normalized = 1.0 if value >= mapping.threshold else 0.0
        elif mapping.formula == "inverse_linear":
            normalized = (mapping.max_value - value) / (mapping.max_value - mapping.min_value)
        else:
            normalized = (value - mapping.min_value) / (mapping.max_value - mapping.min_value)
        if mapping.clamp:
            normalized = min(1.0, max(0.0, normalized))
        return normalized

    def _count(self, normalized: float, total: int, rounding: str) -> int:
        raw = normalized * max(0, total)
        if rounding == "floor":
            count = math.floor(raw)
        elif rounding == "ceil":
            count = math.ceil(raw)
        else:
            count = math.floor(raw + 0.5)
        return min(total, max(0, int(count)))


def _raw_mappings(cfg: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(cfg, Mapping):
        return []
    raw = cfg.get("mappings", cfg.get("inputs", []))
    if isinstance(raw, Mapping):
        return [
            {"target": name, **(spec if isinstance(spec, Mapping) else {"source": spec})}
            for name, spec in raw.items()
        ]
    if isinstance(raw, list):
        return raw
    return []
