"""
Weather routes — live data from Open-Meteo API with mock fallback.

Fetches current conditions and 7-day forecast from the Open-Meteo
free API, then transforms the response into the Pydantic schema
expected by the frontend Dashboard.

Falls back to local mock JSON if the external API is unreachable.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter
from app.schemas.dashboard import WeatherResponse

import httpx

logger = logging.getLogger(__name__)

router = APIRouter()

MOCK_DIR = Path(__file__).resolve().parent.parent.parent / "mockdata"

# ── Open-Meteo Configuration ───────────────────────────────────
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_LAT = 22.7196   # Indore
DEFAULT_LON = 75.8577
DEFAULT_CITY = "Indore"
DEFAULT_STATE = "Madhya Pradesh"
TIMEOUT_SECONDS = 8.0

# ── WMO Weather Code → Readable Condition Mapping ──────────────
# https://open-meteo.com/en/docs#weathervariables
WMO_CODE_MAP = {
    0:  ("sunny",          "Clear Sky"),
    1:  ("sunny",          "Mainly Clear"),
    2:  ("partly_cloudy",  "Partly Cloudy"),
    3:  ("cloudy",         "Overcast"),
    45: ("fog",            "Fog"),
    48: ("fog",            "Depositing Rime Fog"),
    51: ("drizzle",        "Light Drizzle"),
    53: ("drizzle",        "Moderate Drizzle"),
    55: ("drizzle",        "Dense Drizzle"),
    56: ("drizzle",        "Freezing Light Drizzle"),
    57: ("drizzle",        "Freezing Dense Drizzle"),
    61: ("rain",           "Slight Rain"),
    63: ("rain",           "Moderate Rain"),
    65: ("rain",           "Heavy Rain"),
    66: ("rain",           "Freezing Light Rain"),
    67: ("rain",           "Freezing Heavy Rain"),
    71: ("snow",           "Slight Snowfall"),
    73: ("snow",           "Moderate Snowfall"),
    75: ("snow",           "Heavy Snowfall"),
    77: ("snow",           "Snow Grains"),
    80: ("rain",           "Slight Rain Showers"),
    81: ("rain",           "Moderate Rain Showers"),
    82: ("rain",           "Violent Rain Showers"),
    85: ("snow",           "Slight Snow Showers"),
    86: ("snow",           "Heavy Snow Showers"),
    95: ("thunderstorm",   "Thunderstorm"),
    96: ("thunderstorm",   "Thunderstorm with Slight Hail"),
    99: ("thunderstorm",   "Thunderstorm with Heavy Hail"),
}


def _wmo_to_condition(code: int) -> tuple[str, str]:
    """Convert a WMO weather code to (condition_key, condition_text)."""
    return WMO_CODE_MAP.get(code, ("unknown", "Unknown"))


def _generate_advisory(condition: str, temp_max: float, precip_prob: int) -> str:
    """Generate a simple farming advisory based on weather conditions."""
    if condition == "thunderstorm":
        return "Storm warning — avoid open fields. Secure tarpaulins and stored grain."
    if condition == "rain" and precip_prob > 60:
        return "Heavy rain expected — ensure proper field drainage. Good for sowing."
    if condition in ("rain", "drizzle"):
        return "Light rain possible — postpone spraying operations."
    if condition == "fog":
        return "Low visibility — delay early morning fieldwork."
    if condition == "snow":
        return "Cold conditions — protect crops from frost damage."
    if temp_max >= 40:
        return "Extreme heat — ensure adequate irrigation and avoid fieldwork 12–3 PM."
    if temp_max >= 35:
        return "Hot weather — irrigate in the early morning or evening."
    if condition in ("sunny", "partly_cloudy") and precip_prob < 20:
        return "Good day for spraying pesticides — no wind or rain expected."
    if condition == "cloudy":
        return "Good conditions for fertilizer application."
    return "Normal conditions — continue routine farm activities."


def _estimate_feels_like(temp: float, humidity: float, wind_speed: float) -> float:
    """Simple heat index approximation for feels-like temperature."""
    if temp >= 27 and humidity >= 40:
        # Simplified Steadman heat index
        hi = temp + 0.33 * (humidity / 100 * 6.105 * (17.27 * temp / (237.7 + temp))) - 0.7 * wind_speed - 4.0
        return round(max(hi, temp), 1)
    return round(temp, 1)


def _estimate_uv_index(weather_code: int, month: int, lat: float) -> int:
    """Rough UV index estimate based on cloud cover and location."""
    # Base UV by month for tropical/subtropical India
    base_uv = {1: 6, 2: 7, 3: 9, 4: 10, 5: 11, 6: 10, 7: 8, 8: 8, 9: 9, 10: 8, 11: 7, 12: 6}
    uv = base_uv.get(month, 8)

    # Reduce for cloud/rain
    if weather_code >= 95:
        uv = max(1, uv - 8)
    elif weather_code >= 61:
        uv = max(2, uv - 6)
    elif weather_code >= 51:
        uv = max(3, uv - 4)
    elif weather_code >= 3:
        uv = max(4, uv - 3)
    elif weather_code >= 2:
        uv = max(5, uv - 1)

    return min(uv, 15)


def _load_mock_weather() -> dict:
    """Load weather data from the local JSON mock file as fallback."""
    filepath = MOCK_DIR / "weather.json"
    if not filepath.exists():
        # Return safe defaults if mock file is also missing
        return _build_safe_defaults()
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_safe_defaults() -> dict:
    """Build a minimal valid WeatherResponse when everything fails."""
    today = datetime.now()
    daily = []
    for i in range(7):
        d = today + timedelta(days=i)
        daily.append({
            "date": d.strftime("%Y-%m-%d"),
            "day_name": d.strftime("%A"),
            "temp_max": 35,
            "temp_min": 25,
            "condition": "sunny",
            "condition_text": "Clear Sky",
            "precipitation_mm": 0,
            "humidity_pct": 50,
            "wind_speed_kmh": 10,
            "uv_index": 8,
            "advisory": "Weather data temporarily unavailable — continue normal activities.",
        })

    return {
        "location": {
            "latitude": DEFAULT_LAT,
            "longitude": DEFAULT_LON,
            "city": DEFAULT_CITY,
            "state": DEFAULT_STATE,
        },
        "current": {
            "temperature_c": 35,
            "feels_like_c": 38,
            "humidity_pct": 50,
            "wind_speed_kmh": 10,
            "wind_direction": "N",
            "condition": "sunny",
            "condition_text": "Clear Sky",
            "uv_index": 8,
            "visibility_km": 10,
            "pressure_hpa": 1010,
        },
        "daily": daily,
    }


def _wind_degree_to_direction(degrees: float) -> str:
    """Convert wind direction in degrees to a compass abbreviation."""
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(degrees / 22.5) % 16
    return directions[idx]


def _transform_open_meteo(data: dict, lat: float, lon: float, city: str, state: str) -> dict:
    """Transform raw Open-Meteo JSON into our frontend WeatherResponse schema."""
    current = data.get("current", {})
    daily = data.get("daily", {})

    # ── Current conditions ───────────────────────────────────
    temp = current.get("temperature_2m", 35)
    humidity = current.get("relative_humidity_2m", 50)
    wind_speed = current.get("wind_speed_10m", 10)
    wind_direction = current.get("wind_direction_10m", 0)
    weather_code = current.get("weather_code", 0)
    pressure = current.get("surface_pressure", 1010)

    now = datetime.now()
    condition, condition_text = _wmo_to_condition(weather_code)

    current_weather = {
        "temperature_c": round(temp, 1),
        "feels_like_c": _estimate_feels_like(temp, humidity, wind_speed),
        "humidity_pct": round(humidity, 1),
        "wind_speed_kmh": round(wind_speed, 1),
        "wind_direction": _wind_degree_to_direction(wind_direction),
        "condition": condition,
        "condition_text": condition_text,
        "uv_index": _estimate_uv_index(weather_code, now.month, lat),
        "visibility_km": 10,  # Open-Meteo free tier doesn't provide visibility
        "pressure_hpa": round(pressure, 1),
    }

    # ── Daily forecast ───────────────────────────────────────
    dates = daily.get("time", [])
    temp_maxes = daily.get("temperature_2m_max", [])
    temp_mins = daily.get("temperature_2m_min", [])
    precip_probs = daily.get("precipitation_probability_max", [])
    precip_sums = daily.get("precipitation_sum", [])
    weather_codes = daily.get("weather_code", [])
    wind_speeds = daily.get("wind_speed_10m_max", [])
    humidities = daily.get("relative_humidity_2m_mean", [])

    daily_forecasts = []
    for i in range(len(dates)):
        d = datetime.strptime(dates[i], "%Y-%m-%d")
        day_code = weather_codes[i] if i < len(weather_codes) else 0
        day_cond, day_cond_text = _wmo_to_condition(day_code)
        t_max = temp_maxes[i] if i < len(temp_maxes) else 35
        precip_prob = precip_probs[i] if i < len(precip_probs) else 0
        precip_mm = precip_sums[i] if i < len(precip_sums) else 0
        day_wind = wind_speeds[i] if i < len(wind_speeds) else 10
        day_humidity = humidities[i] if i < len(humidities) else 50

        daily_forecasts.append({
            "date": dates[i],
            "day_name": d.strftime("%A"),
            "temp_max": round(t_max, 1),
            "temp_min": round(temp_mins[i], 1) if i < len(temp_mins) else 25,
            "condition": day_cond,
            "condition_text": day_cond_text,
            "precipitation_mm": round(precip_mm, 1),
            "humidity_pct": round(day_humidity, 1),
            "wind_speed_kmh": round(day_wind, 1),
            "uv_index": _estimate_uv_index(day_code, d.month, lat),
            "advisory": _generate_advisory(day_cond, t_max, precip_prob),
        })

    return {
        "location": {
            "latitude": lat,
            "longitude": lon,
            "city": city,
            "state": state,
        },
        "current": current_weather,
        "daily": daily_forecasts,
    }


# ── Routes ──────────────────────────────────────────────────────

@router.get("/current", response_model=WeatherResponse)
async def get_current_weather(
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    city: str = DEFAULT_CITY,
    state: str = DEFAULT_STATE,
):
    """
    Current weather + 7-day forecast from Open-Meteo.

    Falls back to local mock data if the external API is unreachable.
    Query params: ?lat=22.71&lon=75.85&city=Indore&state=Madhya Pradesh
    """
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,surface_pressure",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,weather_code,wind_speed_10m_max,relative_humidity_2m_mean",
            "timezone": "Asia/Kolkata",
            "forecast_days": 7,
        }

        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            raw = response.json()
            
            # If dynamic coords were provided but no specific city name, try to reverse geocode
            if (lat != DEFAULT_LAT or lon != DEFAULT_LON) and city == DEFAULT_CITY:
                try:
                    # Decoupled call with a strict short timeout and compliant User-Agent
                    geo_res = await client.get(
                        f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}",
                        headers={"User-Agent": "AgrooWeatherApp/1.0 (contact@agroo.app)"},
                        timeout=2.0
                    )
                    if geo_res.status_code == 200:
                        geo_data = geo_res.json()
                        address = geo_data.get("address", {})
                        city = address.get("city") or address.get("town") or address.get("village") or "Local Farm"
                        state = address.get("state") or "GPS Data"
                    else:
                        city = "Local Farm"
                        state = "GPS Data"
                except Exception as geo_err:
                    logger.warning(f"Reverse geocoding failed (degrading gracefully): {geo_err}")
                    city = "Local Farm"
                    state = "GPS Data"

        return _transform_open_meteo(raw, lat, lon, city, state)

    except httpx.TimeoutException:
        logger.warning("Open-Meteo request timed out — falling back to mock data")
    except httpx.HTTPStatusError as e:
        logger.warning(f"Open-Meteo returned HTTP {e.response.status_code} — falling back to mock data")
    except httpx.RequestError as e:
        logger.warning(f"Open-Meteo request failed ({e}) — falling back to mock data")
    except Exception as e:
        logger.error(f"Unexpected error fetching weather: {e} — falling back to mock data")

    # Fallback to mock data
    return _load_mock_weather()


@router.get("/forecast")
async def get_forecast(
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    city: str = DEFAULT_CITY,
    state: str = DEFAULT_STATE,
):
    """
    7-day forecast. Query: ?lat=&lon=&city=&state=

    Reuses the /current endpoint logic and returns only location + daily.
    """
    full_data = await get_current_weather(lat=lat, lon=lon, city=city, state=state)

    # full_data can be a dict or a Pydantic model depending on path taken
    if isinstance(full_data, dict):
        return {"location": full_data["location"], "daily": full_data["daily"]}
    return {"location": full_data.location, "daily": full_data.daily}
