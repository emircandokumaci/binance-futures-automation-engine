from enum import Enum
from pydantic import BaseModel, Field


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Signal(BaseModel):
    symbol: str
    side: Side
    confidence: float = Field(ge=0.0, le=1.0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)
    volatility_pct: float = Field(ge=0.0)
    reason: str = ""


class AccountState(BaseModel):
    equity: float = Field(gt=0)
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = Field(default=0.0, ge=0.0)
    current_gross_exposure: float = Field(default=0.0, ge=0.0)
    current_margin_used: float = Field(default=0.0, ge=0.0)
    current_open_positions: int = Field(default=0, ge=0)


class RiskAssessment(BaseModel):
    approved: bool
    reason: str
    risk_pct: float = 0.0
    risk_usdt: float = 0.0
    stop_distance_pct: float = 0.0
    reward_risk: float = 0.0
    notional: float = 0.0
    leverage: int = 0
    margin_required: float = 0.0
    projected_gross_leverage: float = 0.0
