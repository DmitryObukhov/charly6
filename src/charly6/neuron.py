"""Neuron model and serialization helpers."""

from __future__ import annotations

from typing import Any, Mapping, TypeAlias

DEFAULT_NUMBER_OF_LAYERS = 1
DEFAULT_HISTORY_DEPTH = 32
DEFAULT_CHARGE_MAX = 100.0

HistoryEntry: TypeAlias = dict[str, Any]
LegacyHistoryEntry: TypeAlias = tuple[int, float, bool]


def _as_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _layer_values(values: Any, layers: int, default: float = 0.0) -> list[float]:
    if values is None:
        return [default] * layers
    if isinstance(values, (int, float, str)):
        first = _as_float(values, default)
        return [first, *([default] * max(0, layers - 1))][:layers]
    parsed = [_as_float(value, default) for value in values]
    if len(parsed) < layers:
        parsed.extend([default] * (layers - len(parsed)))
    return parsed[:layers]


def _status_values(values: Any, layers: int) -> list[bool]:
    if values is None:
        return [False] * layers
    if isinstance(values, bool):
        return [values, *([False] * max(0, layers - 1))][:layers]
    parsed = [bool(value) for value in values]
    if len(parsed) < layers:
        parsed.extend([False] * (layers - len(parsed)))
    return parsed[:layers]


class Neuron:
    """Serializable neuron state.

    ``active`` is exposed as a compatibility synonym for ``status[0]``. Brain
    processing also folds multi-layer activity into ``status[0]`` so the legacy
    GUI can keep using ``active`` as the visible firing flag.
    """

    __slots__ = (
        "name",
        "number_of_layers",
        "history_depth",
        "charge_max",
        "status",
        "eq",
        "signal",
        "trigger",
        "trigger_flex",
        "charge",
        "charge_min",
        "recharge",
        "recharge_flex",
        "discharge_random",
        "history",
        "cumulative_signal",
        "tiredness",
        "cyclic_discharge",
    )

    def __init__(
        self,
        *,
        name: str = "",
        number_of_layers: int = DEFAULT_NUMBER_OF_LAYERS,
        history_depth: int = DEFAULT_HISTORY_DEPTH,
        charge_max: float = DEFAULT_CHARGE_MAX,
        status: list[bool] | None = None,
        eq: float = 0.0,
        signal: list[float] | None = None,
        trigger: list[float] | None = None,
        trigger_flex: float = 0.0,
        charge: float = 0.0,
        charge_min: float = 0.0,
        recharge: float = 0.0,
        recharge_flex: float = 0.0,
        discharge_random: float = 0.0,
        history: list[HistoryEntry] | None = None,
        active: bool | None = None,
        cumulative_signal: float = 0.0,
        elastic_trigger_delta: float | None = None,
        elastic_recharge: float | None = None,
        cyclic_discharge: float = 0.0,
        tiredness: float = 0.0,
        history_table: list[LegacyHistoryEntry] | None = None,
    ) -> None:
        self.number_of_layers = _as_positive_int(number_of_layers, DEFAULT_NUMBER_OF_LAYERS)
        self.history_depth = _as_positive_int(history_depth, DEFAULT_HISTORY_DEPTH)
        self.charge_max = max(0.0, _as_float(charge_max, DEFAULT_CHARGE_MAX))
        self.name = str(name)
        self.status = _status_values(status, self.number_of_layers)
        if active is not None:
            self.status[0] = bool(active)
        self.eq = self._clamp_eq(eq)
        self.signal = _layer_values(signal, self.number_of_layers)
        self.trigger = _layer_values(trigger, self.number_of_layers)
        self.trigger_flex = _as_float(
            trigger_flex if elastic_trigger_delta is None else elastic_trigger_delta
        )
        self.charge_min = self._clamp_charge(charge_min)
        self.charge = max(self.charge_min, self._clamp_charge(charge))
        self.recharge = min(self.charge_max, max(0.0, _as_float(recharge)))
        self.recharge_flex = min(
            self.charge_max,
            max(0.0, _as_float(recharge_flex if elastic_recharge is None else elastic_recharge)),
        )
        self.discharge_random = min(1.0, max(0.0, _as_float(discharge_random)))
        self.history = list(history or [])
        if history_table:
            self.history = [
                {
                    "iteration": iteration_idx,
                    "active": bool(active_value),
                    "signal": float(signal_value),
                    "trigger": self.trigger[0],
                    "charge": self.charge,
                }
                for iteration_idx, signal_value, active_value in history_table
            ]
        self.history = self.history[-self.history_depth:]
        self.cumulative_signal = _as_float(cumulative_signal)
        self.tiredness = _as_float(tiredness)
        self.cyclic_discharge = max(0.0, _as_float(cyclic_discharge))

    @property
    def active(self) -> bool:
        return bool(self.status[0]) if self.status else False

    @active.setter
    def active(self, value: bool) -> None:
        self._ensure_layers()
        self.status[0] = bool(value)
        if value and not self.signal[0]:
            self.signal[0] = self.charge

    @property
    def elastic_trigger_delta(self) -> float:
        return self.trigger_flex

    @elastic_trigger_delta.setter
    def elastic_trigger_delta(self, value: float) -> None:
        self.trigger_flex = _as_float(value)

    @property
    def elastic_recharge(self) -> float:
        return self.recharge_flex

    @elastic_recharge.setter
    def elastic_recharge(self, value: float) -> None:
        self.recharge_flex = min(self.charge_max, max(0.0, _as_float(value)))

    @property
    def history_table(self) -> list[LegacyHistoryEntry]:
        return [
            (
                int(entry.get("iteration", idx)),
                float(entry.get("signal", 0.0)),
                bool(entry.get("active", False)),
            )
            for idx, entry in enumerate(self.history)
        ]

    @history_table.setter
    def history_table(self, entries: list[LegacyHistoryEntry]) -> None:
        self.history = [
            {
                "iteration": iteration_idx,
                "active": bool(active),
                "signal": float(signal),
                "trigger": self.trigger[0] if self.trigger else 0.0,
                "charge": self.charge,
            }
            for iteration_idx, signal, active in entries
        ][-self.history_depth:]

    def resize_layers(self, number_of_layers: int) -> None:
        self.number_of_layers = _as_positive_int(number_of_layers, DEFAULT_NUMBER_OF_LAYERS)
        self.status = _status_values(self.status, self.number_of_layers)
        self.signal = _layer_values(self.signal, self.number_of_layers)
        self.trigger = _layer_values(self.trigger, self.number_of_layers)

    def record_history(self, iteration_idx: int) -> None:
        self.history.append({
            "iteration": iteration_idx,
            "active": self.active,
            "signal": self.signal[0] if self.signal else 0.0,
            "trigger": self.trigger[0] if self.trigger else 0.0,
            "charge": self.charge,
        })
        if len(self.history) > self.history_depth:
            self.history = self.history[-self.history_depth:]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of this neuron."""
        return {
            "name": self.name,
            "number_of_layers": self.number_of_layers,
            "history_depth": self.history_depth,
            "charge_max": self.charge_max,
            "status": list(self.status),
            "active": self.active,
            "eq": self.eq,
            "signal": list(self.signal),
            "trigger": list(self.trigger),
            "trigger_flex": self.trigger_flex,
            "charge": self.charge,
            "charge_min": self.charge_min,
            "recharge": self.recharge,
            "recharge_flex": self.recharge_flex,
            "discharge_random": self.discharge_random,
            "history": list(self.history),
            "cumulative_signal": self.cumulative_signal,
            "tiredness": self.tiredness,
            "cyclic_discharge": self.cyclic_discharge,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Neuron:
        """Create a neuron from a mapping produced by :meth:`to_dict`."""
        return cls(
            name=str(data.get("name", "")),
            number_of_layers=int(data.get("number_of_layers", data.get("NUMBER_OF_LAYERS", DEFAULT_NUMBER_OF_LAYERS))),
            history_depth=int(data.get("history_depth", data.get("HISTORY_DEPTH", DEFAULT_HISTORY_DEPTH))),
            charge_max=float(data.get("charge_max", data.get("CHARGE_MAX", DEFAULT_CHARGE_MAX))),
            status=data.get("status"),
            active=data.get("active"),
            eq=float(data.get("eq", 0.0)),
            signal=data.get("signal", data.get("signals")),
            trigger=data.get("trigger", data.get("triggers")),
            trigger_flex=float(data.get("trigger_flex", data.get("elastic_trigger_delta", 0.0))),
            charge=float(data.get("charge", 0.0)),
            charge_min=float(data.get("charge_min", 0.0)),
            recharge=float(data.get("recharge", 0.0)),
            recharge_flex=float(data.get("recharge_flex", data.get("elastic_recharge", 0.0))),
            discharge_random=float(data.get("discharge_random", 0.0)),
            history=list(data.get("history", [])),
            cumulative_signal=float(data.get("cumulative_signal", 0.0)),
            cyclic_discharge=float(data.get("cyclic_discharge", 0.0)),
            tiredness=float(data.get("tiredness", 0.0)),
            history_table=data.get("history_table"),
        )

    def _ensure_layers(self) -> None:
        if not self.status:
            self.status = [False] * self.number_of_layers
        if not self.signal:
            self.signal = [0.0] * self.number_of_layers
        if not self.trigger:
            self.trigger = [0.0] * self.number_of_layers

    def _clamp_charge(self, value: Any) -> float:
        return min(self.charge_max, max(0.0, _as_float(value)))

    def _clamp_eq(self, value: Any) -> float:
        limit = self.charge_max
        return min(limit, max(-limit, _as_float(value)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Neuron):
            return NotImplemented
        return self.to_dict() == other.to_dict()
