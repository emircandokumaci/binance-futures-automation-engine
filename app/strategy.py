from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import Signal


@dataclass
class MarketSnapshot:
    symbol: str
    mark_price: float
    volatility_pct: float


class Strategy(ABC):
    """Strategies may propose trades, but can never execute them."""

    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        raise NotImplementedError
