from typing import ClassVar
from collections.abc import Mapping
from types import MappingProxyType

class InstrumentRegistry:
    """Maps instrument names to instrument ID numbers."""

    _INSTRUMENTS: ClassVar[Mapping[str, int]] = MappingProxyType({
        "Yamaha Grand Piano": 0,
        "Honky Tonk Piano": 3,
        "Marimba": 12,
    })

    @classmethod
    def get_instrument_names(cls) -> list[str]:
        """Return all registered instrument names."""
        return list(cls._INSTRUMENTS)

    @classmethod
    def get_instrument_id(cls, name: str) -> int:
        """Return the ID associated with an instrument name."""
        return cls._INSTRUMENTS[name]