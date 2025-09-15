from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from decimal import Decimal

# Modelos Pydantic
class SportType(str, Enum):
    FOOTBALL = "football"
    BASKETBALL = "basketball"
    TENNIS = "tennis"
    SWIMMING = "swimming"
    ATHLETICS = "athletics"
    VOLLEYBALL = "volleyball"
    PARALYMPIC = "paralympic"

class AthleteLevel(str, Enum):
    AMATEUR = "amateur"
    SEMI_PROFESSIONAL = "semi_professional"
    PROFESSIONAL = "professional"
    ELITE = "elite"

class TokenStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"

class AthleteData(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    age: int = Field(..., ge=14, le=50)
    sport: SportType
    level: AthleteLevel
    height: Optional[float] = Field(None, ge=1.0, le=3.0)
    weight: Optional[float] = Field(None, ge=30.0, le=200.0)
    country: str = Field(..., min_length=2, max_length=3)
    bio: Optional[str] = Field(None, max_length=1000)
    achievements: Optional[List[str]] = []
    social_media: Optional[Dict[str, str]] = {}

class PerformanceMetrics(BaseModel):
    wins: int = Field(default=0, ge=0)
    losses: int = Field(default=0, ge=0)
    ranking_position: Optional[int] = Field(None, ge=1)
    recent_performance_score: float = Field(..., ge=0.0, le=100.0)
    potential_score: float = Field(..., ge=0.0, le=100.0)
    media_exposure_score: float = Field(default=0.0, ge=0.0, le=100.0)

class TokenomicsConfig(BaseModel):
    total_supply: int = Field(..., ge=1000, le=10000000)
    price_per_token: Decimal = Field(..., ge=Decimal("0.01"), le=Decimal("1000.00"))
    minimum_investment: Optional[Decimal] = Field(default=Decimal("10.00"), ge=Decimal("1.00"))
    revenue_share_percentage: float = Field(..., ge=5.0, le=50.0)
    token_symbol: str = Field(..., min_length=3, max_length=12, pattern=r'^[A-Z][A-Z0-9]*$')

class CreateAthleteTokenRequest(BaseModel):
    athlete_data: AthleteData
    performance_metrics: PerformanceMetrics
    tokenomics: TokenomicsConfig
    funding_goal: Decimal = Field(..., ge=Decimal("1000.00"))
    campaign_duration_days: int = Field(..., ge=30, le=365)

class InvestmentRequest(BaseModel):
    token_id: str
    amount_xlm: Decimal = Field(..., ge=Decimal("1.00"))
    investor_stellar_address: str

class RevenueDistribution(BaseModel):
    token_id: str
    revenue_amount: Decimal
    source: str  # "prize", "marketing", "events", "other"
    description: Optional[str] = None