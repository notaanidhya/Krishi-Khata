import logging
import json
import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
import httpx
from slowapi import Limiter
from slowapi.util import get_remote_address
from cachetools import TTLCache
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

WEATHERAPI_BASE = "https://api.weatherapi.com/v1/forecast.json"
OPENMETEO_BASE  = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 8.0

# In-memory server-side caches (TTL = 1 hour)
dashboard_cache = TTLCache(maxsize=1000, ttl=3600)
advisory_cache  = TTLCache(maxsize=1000, ttl=3600)


def _weatherapi_to_condition(code: int, is_day: int = 1) -> tuple[str, str]:
    """
    Map WeatherAPI.com condition codes to our internal (condition, condition_text) tuple.
    Full code list: https://www.weatherapi.com/docs/weather_conditions.json
    """
    # Sunny / Clear
    if code == 1000:
        return ("sunny", "Clear Sky") if is_day else ("sunny", "Clear")
    # Partly Cloudy
    if code in (1003,):
        return "partly_cloudy", "Partly Cloudy"
    # Cloudy / Overcast
    if code in (1006, 1009):
        return "cloudy", "Partly Cloudy"
    # Mist / Fog
    if code in (1030, 1135, 1147):
        return "fog", "Fog"
    # Drizzle / Light rain
    if code in (1063, 1150, 1153, 1168, 1171, 1180, 1183):
        return "drizzle", "Light Drizzle"
    # Moderate / Heavy rain
    if code in (1186, 1189, 1192, 1195, 1198, 1201, 1240, 1243, 1246):
        return "rain", "Rain"
    # Snow
    if code in (1066, 1069, 1072, 1114, 1117, 1204, 1207, 1210, 1213,
                1216, 1219, 1222, 1225, 1237, 1249, 1252, 1255, 1258,
                1261, 1264):
        return "snow", "Snow"
    # Thunderstorm
    if code in (1087, 1273, 1276, 1279, 1282):
        return "thunderstorm", "Thunderstorm"
    # Rain showers (patchy)
    if code in (1021, 1024, 1027):
        return "rain", "Rain Showers"
    return "partly_cloudy", "Partly Cloudy"


def _cache_key(lat: float, lon: float) -> str:
    """4 decimal places ≈ ±11m precision — prevents serving the wrong area's cache."""
    return f"v3_{lat:.4f},{lon:.4f}"


def _generate_advisory(cond: str, t_max: float, rain: float) -> str:
    """Static fallback advisory when Gemini is unavailable."""
    parts = []
    if t_max >= 42:
        parts.append("आज अत्यधिक गर्मी है — फसलों को सुबह या शाम सिंचाई दें, दोपहर में काम से बचें।")
    elif t_max >= 37:
        parts.append("तापमान अधिक है — फसलों में पर्याप्त नमी बनाए रखें और छाया का प्रबंध करें।")
    elif t_max <= 15:
        parts.append("ठंड अधिक है — पाले से फसलों को बचाने के लिए हल्की सिंचाई करें।")

    if rain >= 70:
        parts.append("भारी बारिश की संभावना है — खेत में जलनिकासी की व्यवस्था करें और कटाई टालें।")
    elif rain >= 40:
        parts.append("बारिश हो सकती है — कटाई व छिड़काव कार्य स्थगित रखें।")
    elif rain < 15:
        parts.append("सूखा मौसम — नियमित सिंचाई करें और मिट्टी की नमी जांचते रहें।")

    if cond == "thunderstorm":
        parts.append("आंधी-तूफान की चेतावनी — खुले खेत में काम न करें।")
    elif cond == "fog":
        parts.append("कोहरे के कारण फसल में फफूंद रोग का खतरा बढ़ सकता है — निगरानी रखें।")

    if not parts:
        parts.append("नियमित रूप से मिट्टी की जांच करवाएं और उचित खाद का प्रयोग करें।")
    return " ".join(parts)


def _generate_ai_weather_summary(
    city: str,
    state: str,
    forecast_days: list,
    target_language: str = "Hindi",
    crop_name: str = None,
    days_since_planting: int = None,
    current_stage: str = None,
) -> dict:
    """Call Gemini for a personalised agronomist advisory based on weather + crop stage."""
    summary_parts = []
    for day in forecast_days[:7]:
        cond = day.get("condition_text", "Clear")
        t_max = day.get("temp_max", 35)
        t_min = day.get("temp_min", 25)
        rain = day.get("precip_probability_pct", 0)
        summary_parts.append(
            f"{day.get('date', '')}: {cond}, {t_min:.0f}-{t_max:.0f}°C, rain {rain}%"
        )

    weather_summary = "; ".join(summary_parts)

    if crop_name and days_since_planting is not None and current_stage:
        crop_context = (
            f"The farmer is currently growing {crop_name}, planted {days_since_planting} days ago "
            f"(current growth stage: {current_stage}). "
            f"Tailor ALL advice specifically to this crop at this exact growth stage."
        )
    elif crop_name:
        crop_context = f"The farmer is growing {crop_name}. Tailor all advice specifically to this crop."
    else:
        crop_context = "No specific crop information is available — give general farming advice."

    if not settings.GEMINI_API_KEY:
        t_max = forecast_days[0].get("temp_max", 35) if forecast_days else 35
        rain = forecast_days[0].get("precip_probability_pct", 0) if forecast_days else 0
        cond = forecast_days[0].get("condition", "sunny") if forecast_days else "sunny"
        return {
            "advisory": _generate_advisory(cond, t_max, rain),
            "daily_tip": "रोजाना खेत का निरीक्षण करें और जरूरत पड़ने पर ही सिंचाई करें।",
            "moisture_status": "सामान्य",
            "moisture_description": "मिट्टी में नमी की मात्रा अच्छी है। नियमित सिंचाई अनुसूची पर्याप्त है।",
            "is_fallback": True
        }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Give me today's agricultural weather advisory.",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction=(
                    f"You are an expert Indian agronomist weather advisor speaking directly to a farmer. "
                    f"{crop_context} "
                    f"The upcoming 7-day forecast for {city}, {state} is: {weather_summary}. "
                    f"You must return a JSON object with exactly four keys: "
                    f"1. 'advisory': 2-3 sentences of highly specific advice for this farmer right now — "
                    f"mention the crop name and growth stage explicitly, warn of real risks like fungal infection, "
                    f"heat stress on the crop at this stage, irrigation needs, or upcoming harvest timing. "
                    f"2. 'daily_tip': One practical everyday farming tip relevant to this crop at its current stage, "
                    f"written in simple conversational Hindi that any farmer would understand. "
                    f"3. 'moisture_status': One word/phrase for current soil moisture (e.g., 'सूखा', 'सामान्य', 'अधिक नमी'). "
                    f"4. 'moisture_description': 1 sentence describing soil moisture and specific watering advice for this crop stage. "
                    f"IMPORTANT: Respond entirely in Hindi (Devanagari script). Use simple, conversational language "
                    f"that a village farmer can easily understand. Be specific — not generic."
                ),
            )
        )
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"Gemini weather summary failed: {e}")
        t_max = forecast_days[0].get("temp_max", 35) if forecast_days else 35
        rain = forecast_days[0].get("precip_probability_pct", 0) if forecast_days else 0
        cond = forecast_days[0].get("condition", "sunny") if forecast_days else "sunny"
        return {
            "advisory": _generate_advisory(cond, t_max, rain),
            "daily_tip": "रोजाना खेत का निरीक्षण करें और जरूरत पड़ने पर ही सिंचाई करें।",
            "moisture_status": "सामान्य",
            "moisture_description": "मिट्टी में नमी की मात्रा अच्छी है। नियमित सिंचाई अनुसूची पर्याप्त है।",
            "is_fallback": True
        }


async def _fetch_weatherapi(lat: float, lon: float) -> dict:
    """
    Fetches 7-day forecast + current conditions from WeatherAPI.com.
    Returns the parsed JSON or raises httpx.HTTPStatusError on failure.
    """
    if not settings.WEATHERAPI_KEY:
        raise ValueError("WEATHERAPI_KEY is not configured in settings.")

    params = {
        "key": settings.WEATHERAPI_KEY,
        "q": f"{lat},{lon}",
        "days": 7,
        "aqi": "no",
        "alerts": "no",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.get(WEATHERAPI_BASE, params=params)
        response.raise_for_status()
        return response.json()


async def _fetch_openmeteo_soil(lat: float, lon: float) -> dict | None:
    """
    Fetches today's soil moisture and evapotranspiration from Open-Meteo.
    This supplements WeatherAPI which does not provide native soil data.

    Returns a dict with moisture_pct and evapotranspiration_mm, or None on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "soil_moisture_0_to_1cm",
        "daily": "et0_fao_evapotranspiration",
        "timezone": "Asia/Kolkata",
        "forecast_days": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": "Agroo/1.0"}) as client:
            response = await client.get(OPENMETEO_BASE, params=params)
            response.raise_for_status()
            data = response.json()

        # Average the hourly soil moisture values for today (m³/m³) → convert to %
        hourly_moisture = data.get("hourly", {}).get("soil_moisture_0_to_1cm", [])
        valid = [v for v in hourly_moisture if v is not None]
        avg_moisture_raw = sum(valid) / len(valid) if valid else None

        # Open-Meteo returns volumetric water content (m³/m³).
        # Typical field range: 0.05 (very dry) – 0.45 (saturated)
        # We map this to a 0–100% scale for display.
        moisture_pct = round((avg_moisture_raw / 0.45) * 100, 1) if avg_moisture_raw is not None else None

        # Daily evapotranspiration (mm/day)
        et_vals = data.get("daily", {}).get("et0_fao_evapotranspiration", [])
        et_mm = round(et_vals[0], 2) if et_vals and et_vals[0] is not None else None

        return {"moisture_pct": moisture_pct, "evapotranspiration_mm": et_mm}

    except Exception as e:
        logger.warning(f"Open-Meteo soil fetch failed (non-critical): {e}")
        return None


def _soil_status_label(moisture_pct: float | None) -> tuple[str, str]:
    """
    Converts a soil moisture percentage to a human-readable Hindi label
    and a descriptive sentence for the farmer.
    """
    if moisture_pct is None:
        return "सामान्य", "मिट्टी में नमी की मात्रा अच्छी है। नियमित सिंचाई अनुसूची पर्याप्त है।"
    if moisture_pct < 20:
        return (
            "बहुत सूखा",
            f"मिट्टी में नमी बहुत कम है ({moisture_pct:.0f}%)। आज ही सिंचाई करें — पौधों पर सूखे का तनाव पड़ सकता है।"
        )
    if moisture_pct < 40:
        return (
            "सूखा",
            f"मिट्टी में नमी कम है ({moisture_pct:.0f}%)। अगले 1-2 दिनों में सिंचाई की जरूरत है।"
        )
    if moisture_pct < 65:
        return (
            "सामान्य",
            f"मिट्टी में नमी की मात्रा अच्छी है ({moisture_pct:.0f}%)। नियमित सिंचाई अनुसूची पर्याप्त है।"
        )
    if moisture_pct < 80:
        return (
            "अधिक नमी",
            f"मिट्टी में नमी अधिक है ({moisture_pct:.0f}%)। अगले 2-3 दिन सिंचाई न करें और जलनिकासी की जांच करें।"
        )
    return (
        "जलभराव",
        f"खेत में जलभराव की स्थिति है ({moisture_pct:.0f}%)। तुरंत जल निकासी का प्रबंध करें — फसल की जड़ें प्रभावित हो सकती हैं।"
    )


def _parse_dashboard(
    raw: dict,
    city: str,
    state: str,
    lat: float,
    lon: float,
    soil_data: dict | None = None,
) -> dict:
    """
    Translate WeatherAPI.com JSON → our internal dashboard schema.

    Args:
        raw: Raw WeatherAPI JSON response.
        soil_data: Optional dict from Open-Meteo with moisture_pct + evapotranspiration_mm.
    """
    current_raw = raw.get("current", {})
    forecast_raw = raw.get("forecast", {}).get("forecastday", [])
    loc_raw = raw.get("location", {})

    # Use WeatherAPI's own resolved location name if no city was passed
    resolved_city = city or loc_raw.get("name", "")
    resolved_state = state or loc_raw.get("region", "")

    # Current conditions
    cond_obj = current_raw.get("condition", {})
    condition, condition_text = _weatherapi_to_condition(
        cond_obj.get("code", 1000), current_raw.get("is_day", 1)
    )
    current = {
        "temperature_c": round(current_raw.get("temp_c", 35), 1),
        "humidity_pct": round(current_raw.get("humidity", 50), 1),
        "wind_speed_kmh": round(current_raw.get("wind_kph", 10), 1),
        "condition": condition,
        "condition_text": condition_text,
    }

    # 7-day forecast
    forecast_7day = []
    for day_raw in forecast_raw:
        day_info = day_raw.get("day", {})
        day_cond_obj = day_info.get("condition", {})
        day_cond, day_cond_text = _weatherapi_to_condition(day_cond_obj.get("code", 1000))
        date_str = day_raw.get("date", "")
        d = datetime.strptime(date_str, "%Y-%m-%d")
        forecast_7day.append({
            "date": date_str,
            "day_name": d.strftime("%A"),
            "temp_max": round(day_info.get("maxtemp_c", 35), 1),
            "temp_min": round(day_info.get("mintemp_c", 25), 1),
            "condition": day_cond,
            "condition_text": day_cond_text,
            "precip_probability_pct": int(day_info.get("daily_chance_of_rain", 0)),
            "wind_speed_kmh": round(day_info.get("maxwind_kph", 10), 1),
            "humidity_pct": round(day_info.get("avghumidity", 50), 1),
        })

    # Soil insights — use Open-Meteo native data when available, else a safe default
    moisture_pct = soil_data.get("moisture_pct") if soil_data else None
    et_mm = soil_data.get("evapotranspiration_mm") if soil_data else None
    moisture_status, moisture_description = _soil_status_label(moisture_pct)

    return {
        "location": {
            "city": resolved_city,
            "state": resolved_state,
            "latitude": lat,
            "longitude": lon,
        },
        "current": current,
        "ai_summary": None,
        "soil_insights": {
            "moisture_status": moisture_status,
            "moisture_description": moisture_description,
            "moisture_pct": moisture_pct,
            "evapotranspiration_mm": et_mm,
            "source": "open-meteo" if moisture_pct is not None else "fallback",
        },
        "forecast_7day": forecast_7day,
    }


def _build_fallback_dashboard(city: str, state: str, lat: float, lon: float) -> dict:
    now = datetime.now()
    fallback_forecast = []
    for i in range(7):
        d = now + timedelta(days=i)
        fallback_forecast.append({
            "date": d.strftime("%Y-%m-%d"),
            "day_name": d.strftime("%A"),
            "temp_max": 35, "temp_min": 25,
            "condition": "sunny", "condition_text": "Clear Sky",
            "precip_probability_pct": 10,
            "wind_speed_kmh": 10, "humidity_pct": 50,
        })
    return {
        "location": {"city": city, "state": state, "latitude": lat, "longitude": lon},
        "current": {
            "temperature_c": 35, "humidity_pct": 50, "wind_speed_kmh": 10,
            "condition": "sunny", "condition_text": "Clear Sky",
        },
        "ai_summary": None,
        "soil_insights": {
            "moisture_status": "सामान्य",
            "moisture_description": "मौसम डेटा उपलब्ध नहीं है - कृपया स्वयं मिट्टी की नमी की जांच करें।",
        },
        "forecast_7day": fallback_forecast,
    }


# ─────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
@limiter.limit("20/minute")
async def get_weather_dashboard(
    request: Request,
    lat: float,
    lon: float,
    city: str = "",
    state: str = "",
):
    """
    Advanced Agriculture Weather Dashboard via WeatherAPI.com.
    lat and lon are required — no hardcoded defaults.
    """
    cache_key = _cache_key(lat, lon)
    if cache_key in dashboard_cache:
        return dashboard_cache[cache_key]

    try:
        # ── Hybrid Fetch: WeatherAPI + Open-Meteo in parallel ──────────
        # Both requests fire simultaneously — no extra latency.
        # If Open-Meteo fails, we gracefully fall back to the AI-generated
        # soil moisture estimate in the advisory endpoint.
        weatherapi_task = _fetch_weatherapi(lat, lon)
        soil_task = _fetch_openmeteo_soil(lat, lon)
        raw, soil_data = await asyncio.gather(weatherapi_task, soil_task, return_exceptions=False)

        result = _parse_dashboard(raw, city, state, lat, lon, soil_data=soil_data)
        dashboard_cache[cache_key] = result
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Weather dashboard failed: {e} — returning safe defaults")
        return _build_fallback_dashboard(city, state, lat, lon)


@router.get("/ai-advisory")
@limiter.limit("10/minute")
async def get_ai_advisory(
    request: Request,
    lat: float,
    lon: float,
    city: str = "",
    state: str = "",
    crop_name: str = None,
    days_since_planting: int = None,
    current_stage: str = None,
):
    """AI agricultural advisory, backed by Gemini + WeatherAPI.com forecast data."""
    cache_key = f"{_cache_key(lat, lon)}|{crop_name or ''}|{current_stage or ''}"
    if cache_key in advisory_cache:
        return advisory_cache[cache_key]

    try:
        raw = await _fetch_weatherapi(lat, lon)
        dashboard = _parse_dashboard(raw, city, state, lat, lon)
        forecast_days = dashboard["forecast_7day"]
        loc_raw = raw.get("location", {})
        resolved_city = city or loc_raw.get("name", "")
        resolved_state = state or loc_raw.get("region", "")

        summary = _generate_ai_weather_summary(
            resolved_city, resolved_state, forecast_days,
            crop_name=crop_name,
            days_since_planting=days_since_planting,
            current_stage=current_stage,
        )

        result = {
            "ai_summary": summary.get("advisory", ""),
            "daily_tip": summary.get("daily_tip", ""),
            "moisture_status": summary.get("moisture_status", "सामान्य"),
            "moisture_description": summary.get("moisture_description", "मिट्टी में नमी की मात्रा अच्छी है।"),
            "is_fallback": summary.get("is_fallback", False),
            "crop_name": crop_name,
            "current_stage": current_stage,
        }
        if not result["is_fallback"]:
            advisory_cache[cache_key] = result
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI advisory failed: {e}")
        return {
            "ai_summary": "आज मौसम सामान्य रहने की उम्मीद है। फसल की नियमित निगरानी करते रहें और जरूरत पड़ने पर ही सिंचाई करें।",
            "daily_tip": "स्वस्थ फसल के लिए अच्छे बीजों का चयन करें और समय पर सिंचाई करें।",
            "moisture_status": "सामान्य",
            "moisture_description": "मिट्टी में नमी की मात्रा अच्छी है। नियमित सिंचाई अनुसूची पर्याप्त है।",
            "is_fallback": True,
        }


@router.get("/current")
@limiter.limit("20/minute")
async def get_current_weather(
    request: Request,
    lat: float = None,
    lon: float = None,
):
    """Minimal current conditions endpoint (used by the dashboard home widget)."""
    if lat is None or lon is None:
        raise HTTPException(status_code=400, detail="lat and lon are required.")

    cache_key = f"current_{_cache_key(lat, lon)}"
    if cache_key in dashboard_cache:
        return dashboard_cache[cache_key]

    try:
        raw = await _fetch_weatherapi(lat, lon)
        dashboard = _parse_dashboard(raw, "", "", lat, lon)
        result = {
            "location": dashboard["location"],
            "current": dashboard["current"],
            "daily": dashboard["forecast_7day"],
        }
        dashboard_cache[cache_key] = result
        return result
    except Exception as e:
        logger.error(f"Current weather fetch failed: {e}")
        raise HTTPException(status_code=503, detail="Weather service temporarily unavailable.")


@router.get("/forecast")
@limiter.limit("20/minute")
async def get_forecast(
    request: Request,
    lat: float,
    lon: float,
):
    """7-day forecast endpoint."""
    cache_key = f"forecast_{_cache_key(lat, lon)}"
    if cache_key in dashboard_cache:
        return dashboard_cache[cache_key]

    try:
        raw = await _fetch_weatherapi(lat, lon)
        dashboard = _parse_dashboard(raw, "", "", lat, lon)
        result = {
            "location": dashboard["location"],
            "daily": dashboard["forecast_7day"],
        }
        dashboard_cache[cache_key] = result
        return result
    except Exception as e:
        logger.error(f"Forecast fetch failed: {e}")
        raise HTTPException(status_code=503, detail="Weather service temporarily unavailable.")
