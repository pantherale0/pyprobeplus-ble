from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=False)
class ProbeState:
    battery_level: int = 0
    temperature: float = 0
    rssi: float = 0

@dataclass(frozen=False)
class RelayState:
    battery_level: int = 0
    volage: float = 0
    status: int = 0
