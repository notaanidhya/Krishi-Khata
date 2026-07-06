"""
gdd_calculator.py — Growing Degree Day calculations.

Hybrid Architecture:
  - Uses Open-Meteo Archive API for historical GDD (unlimited free history).
  - Uses Open-Meteo Forecast API for today's GDD.

NOTE: This intentionally does NOT use WeatherAPI here.
WeatherAPI's free tier caps historical data at 7 days, which is insufficient
for tracking crops planted weeks or months ago. Open-Meteo provides a
completely free archive going back decades with no rate limits.

The coordinates passed here are always the high-precision lat/lon resolved
by WeatherAPI's location engine (4 decimal places ≈ ±11m precision).
"""

import httpx
from datetime import date
import json

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"


async def fetch_historical_gdd(
    lat: float, lon: float,
    start_date: date, end_date: date,
    base_temp: float = 10.0
) -> float:
    """
    Fetch historical max/min temperatures via Open-Meteo and calculate
    cumulative Growing Degree Days (GDD).

    Formula: GDD_per_day = max(0, (T_max + T_min) / 2 - base_temp)

    Args:
        lat: Latitude (high-precision, resolved by WeatherAPI)
        lon: Longitude (high-precision, resolved by WeatherAPI)
        start_date: First day of the period (planting date)
        end_date: Last day of the period (usually yesterday)
        base_temp: Crop base temperature in °C (default 10°C = wheat/maize)

    Returns:
        Cumulative GDD as a float. Falls back to 15 GDD/day on API failure.
    """
    if start_date > end_date:
        return 0.0

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "Asia/Kolkata",
    }

    cumulative_gdd = 0.0
    try:
        async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": "Agroo/1.0"}) as client:
            response = await client.get(ARCHIVE_API_URL, params=params)
            response.raise_for_status()
            data = response.json()

            daily = data.get("daily", {})
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])

            for t_max, t_min in zip(max_temps, min_temps):
                if t_max is not None and t_min is not None:
                    gdd = ((t_max + t_min) / 2.0) - base_temp
                    if gdd > 0:
                        cumulative_gdd += gdd

    except json.JSONDecodeError:
        print(f"[GDD] Open-Meteo returned invalid JSON — using fallback (15 GDD/day)")
        days = (end_date - start_date).days + 1
        cumulative_gdd = days * 15.0
    except Exception as e:
        print(f"[GDD] Error fetching historical GDD from Open-Meteo: {e}")
        days = (end_date - start_date).days + 1
        cumulative_gdd = days * 15.0

    return cumulative_gdd


async def get_todays_gdd(lat: float, lon: float, base_temp: float = 10.0) -> float:
    """
    Fetch today's max/min temperatures from Open-Meteo forecast
    and return the GDD contribution for today.

    Args:
        lat: Latitude (high-precision, resolved by WeatherAPI)
        lon: Longitude (high-precision, resolved by WeatherAPI)
        base_temp: Crop base temperature in °C

    Returns:
        Today's GDD as a float. Falls back to 15.0 on API failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "Asia/Kolkata",
        "forecast_days": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0, headers={"User-Agent": "Agroo/1.0"}) as client:
            response = await client.get(FORECAST_API_URL, params=params)
            response.raise_for_status()
            data = response.json()

            daily = data.get("daily", {})
            t_max = daily.get("temperature_2m_max", [None])[0]
            t_min = daily.get("temperature_2m_min", [None])[0]

            if t_max is not None and t_min is not None:
                gdd = ((t_max + t_min) / 2.0) - base_temp
                return max(0.0, gdd)

    except json.JSONDecodeError:
        print(f"[GDD] Open-Meteo forecast returned invalid JSON — using fallback")
    except Exception as e:
        print(f"[GDD] Error fetching today's GDD from Open-Meteo: {e}")

    return 15.0  # Safe fallback
