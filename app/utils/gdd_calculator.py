import httpx
from datetime import date
from typing import Optional
import json

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

async def fetch_historical_gdd(lat: float, lon: float, start_date: date, end_date: date, base_temp: float = 10.0) -> float:
    """
    Fetch historical max/min temperatures and calculate cumulative GDD.
    GDD = (Max + Min) / 2 - Base.
    If GDD < 0, it contributes 0.
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
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "Agroo/1.0"}) as client:
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
                        
    except Exception as e:
        if isinstance(e, json.JSONDecodeError):
            print(f"Warning: Open-Meteo returned invalid JSON. Using fallback historical GDD. (url: {ARCHIVE_API_URL})")
        else:
            print(f"Error fetching historical GDD: {e}")
        # Fallback approximation: 15 GDD per day
        days = (end_date - start_date).days + 1
        cumulative_gdd = days * 15.0

    return cumulative_gdd


async def get_todays_gdd(lat: float, lon: float, base_temp: float = 10.0) -> float:
    """Fetch today's max/min and return GDD."""
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
    except Exception as e:
        if isinstance(e, json.JSONDecodeError):
            print(f"Warning: Open-Meteo returned invalid JSON. Using fallback today's GDD. (url: {FORECAST_API_URL})")
        else:
            print(f"Error fetching today's GDD: {e}")
        
    return 15.0 # fallback
