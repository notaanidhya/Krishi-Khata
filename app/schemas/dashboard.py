from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


#  WEATHER SCHEMAS
class WeatherLocation(BaseModel):
    latitude: float
    longitude: float
    city: str
    state: str


class CurrentWeather(BaseModel):
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
    location: WeatherLocation
    current: CurrentWeather
    daily: List[DailyForecast]


#  MANDI PRICE SCHEMAS
class MandiPrice(BaseModel):
    commodity: str
    variety: str
    min_price: float
    max_price: float
    modal_price: float
    arrival_date: str


class DashboardMandiResponse(BaseModel):
    district: str
    date: str
    prices: List[MandiPrice]

class MandiPricesResponse(BaseModel):
    last_updated: str
    prices: List[MandiPrice]


#  COMBINED DASHBOARD SCHEMA
class FarmerDashboardResponse(BaseModel):
    farm_id: int
    farm_name: str
    area_acres: float
    weather: Optional[WeatherResponse] = None
    mandi_prices: Optional[DashboardMandiResponse] = None
