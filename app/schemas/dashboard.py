"""
Pydantic schemas for Dashboard — Weather & Mandi data validation.
"""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
#  WEATHER SCHEMAS
# ═══════════════════════════════════════════════════════════════

class WeatherLocation(BaseModel):
    """Geographic location for weather data."""
    latitude: float
    longitude: float
    city: str
    state: str


class CurrentWeather(BaseModel):
    """Current weather conditions."""
    temperature_c: float
    feels_like_c: float
    humidity_pct: float = Field(..., ge=0, le=100)
    wind_speed_kmh: float = Field(..., ge=0)
    wind_direction: str
    condition: str
    condition_text: str
    uv_index: int = Field(..., ge=0, le=15)
    visibility_km: float = Field(..., ge=0)
    pressure_hpa: float


class DailyForecast(BaseModel):
    """Single day weather forecast."""
    date: str
    day_name: str
    temp_max: float
    temp_min: float
    condition: str
    condition_text: str
    precipitation_mm: float = Field(..., ge=0)
    humidity_pct: float = Field(..., ge=0, le=100)
    wind_speed_kmh: float = Field(..., ge=0)
    uv_index: int = Field(..., ge=0, le=15)
    advisory: str


class WeatherResponse(BaseModel):
    """Full weather response — current conditions + 7-day forecast."""
    location: WeatherLocation
    current: CurrentWeather
    daily: List[DailyForecast]


# ═══════════════════════════════════════════════════════════════
#  MANDI PRICE SCHEMAS
# ═══════════════════════════════════════════════════════════════

class MandiPrice(BaseModel):
    """Single commodity price entry from a mandi."""
    commodity: str
    variety: str
    mandi: str
    state: str
    min_price: float = Field(..., ge=0, description="Minimum price in INR per quintal")
    max_price: float = Field(..., ge=0, description="Maximum price in INR per quintal")
    modal_price: float = Field(..., ge=0, description="Most common trading price")
    previous_price: float = Field(..., ge=0, description="Previous day's modal price")
    change_pct: float = Field(..., description="Percentage change from previous price")
    unit: str = "quintal"
    arrival_date: str
    arrival_tonnes: float = Field(..., ge=0)


class MandiPricesResponse(BaseModel):
    """Response wrapper for mandi prices."""
    last_updated: str
    prices: List[MandiPrice]
