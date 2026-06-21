import logging
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
import httpx
from slowapi import Limiter
from slowapi.util import get_remote_address
from cachetools import TTLCache
from app.dependencies import get_current_user
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 5.0
DEFAULT_LAT = 23.2599
DEFAULT_LON = 77.4126
DEFAULT_CITY = "Bhopal"
DEFAULT_STATE = "Madhya Pradesh"

dashboard_cache = TTLCache(maxsize=1000, ttl=3600)
advisory_cache = TTLCache(maxsize=1000, ttl=3600)

def _wmo_to_condition(code: int) -> tuple[str, str]:
    if code == 0: return "sunny", "Clear Sky"
    if code in [1, 2, 3]: return "partly_cloudy", "Partly Cloudy"
    if code in [45, 48]: return "fog", "Fog"
    if code in [51, 53, 55, 56, 57]: return "drizzle", "Light Drizzle"
    if code in [61, 63, 65, 66, 67]: return "rain", "Rain"
    if code in [71, 73, 75, 77]: return "snow", "Snow"
    if code in [80, 81, 82]: return "rain", "Rain Showers"
    if code in [95, 96, 99]: return "thunderstorm", "Thunderstorm"
    return "sunny", "Clear Sky"

def _generate_advisory(cond: str, t_max: float, rain: float) -> str:
    """Generate a contextual advisory based on real weather data without Gemini."""
    parts = []

    # Heat advisory
    if t_max >= 42:
        parts.append("आज अत्यधिक गर्मी है — फसलों को सुबह या शाम सिंचाई दें, दोपहर में काम से बचें।")
    elif t_max >= 37:
        parts.append("तापमान अधिक है — फसलों में पर्याप्त नमी बनाए रखें और छाया का प्रबंध करें।")
    elif t_max <= 15:
        parts.append("ठंड अधिक है — पाले से फसलों को बचाने के लिए हल्की सिंचाई करें।")

    # Rain advisory
    if rain >= 70:
        parts.append("भारी बारिश की संभावना है — खेत में जलनिकासी की व्यवस्था करें और कटाई टालें।")
    elif rain >= 40:
        parts.append("बारिश हो सकती है — कटाई व छिड़काव कार्य स्थगित रखें।")
    elif rain < 15:
        parts.append("सूखा मौसम — नियमित सिंचाई करें और मिट्टी की नमी जांचते रहें।")

    # Condition-specific
    if cond in ('thunderstorm',):
        parts.append("आंधी-तूफान की चेतावनी — खुले खेत में काम न करें।")
    elif cond in ('fog',):
        parts.append("कोहरे के कारण फसल में फफूंद रोग का खतरा बढ़ सकता है — निगरानी रखें।")

    # Fallback if nothing specific
    if not parts:
        parts.append("नियमित रूप से मिट्टी की जांच करवाएं और उचित खाद का प्रयोग करें।")

    return " ".join(parts)

def _generate_ai_weather_summary(
    city: str,
    state: str,
    daily_data: dict,
    target_language: str = "English",
    crop_name: str = None,
    days_since_planting: int = None,
    current_stage: str = None,
) -> dict:
    """Call Gemini for a personalised agronomist advisory based on weather + crop stage."""
    dates = daily_data.get("time", [])
    temp_maxes = daily_data.get("temperature_2m_max", [])
    temp_mins = daily_data.get("temperature_2m_min", [])
    precip_probs = daily_data.get("precipitation_probability_mean", [])
    codes = daily_data.get("weather_code", [])

    summary_parts = []
    for i in range(min(7, len(dates))):
        cond = _wmo_to_condition(codes[i] if i < len(codes) else 0)[1]
        t_max = temp_maxes[i] if i < len(temp_maxes) else 35
        t_min = temp_mins[i] if i < len(temp_mins) else 25
        rain = precip_probs[i] if i < len(precip_probs) else 0
        summary_parts.append(f"{dates[i]}: {cond}, {t_min:.0f}-{t_max:.0f}°C, rain {rain}%")

    weather_summary = "; ".join(summary_parts)

    # Build crop context string for the Gemini prompt
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
        code = codes[0] if codes else 0
        t_max = temp_maxes[0] if temp_maxes else 35
        rain = precip_probs[0] if precip_probs else 0
        cond = _wmo_to_condition(code)[0]
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
        return json.loads(response.text.strip())
    except Exception as e:
        logger.error(f"Gemini weather summary failed: {e}")
        code = codes[0] if codes else 0
        t_max = temp_maxes[0] if temp_maxes else 35
        rain = precip_probs[0] if precip_probs else 0
        cond = _wmo_to_condition(code)[0]
        return {
            "advisory": _generate_advisory(cond, t_max, rain),
            "daily_tip": "रोजाना खेत का निरीक्षण करें और जरूरत पड़ने पर ही सिंचाई करें।",
            "moisture_status": "सामान्य",
            "moisture_description": "मिट्टी में नमी की मात्रा अच्छी है। नियमित सिंचाई अनुसूची पर्याप्त है।",
            "is_fallback": True
        }



@router.get("/dashboard")
@limiter.limit("10/minute")
async def get_weather_dashboard(
    request: Request,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    city: str = DEFAULT_CITY,
    state: str = DEFAULT_STATE,
):
    """
    Advanced Agriculture Weather Dashboard.
    """
    cache_key = f"v2_{lat:.2f},{lon:.2f}"
    if cache_key in dashboard_cache:
        return dashboard_cache[cache_key]

    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,surface_pressure",
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_mean,precipitation_sum,"
                "weather_code,wind_speed_10m_max,"
                "relative_humidity_2m_mean"
            ),
            "timezone": "Asia/Kolkata",
            "forecast_days": 7,
        }

        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            raw = response.json()

        current_raw = raw.get("current", {})
        daily_raw = raw.get("daily", {})

        temp = current_raw.get("temperature_2m", 35)
        humidity = current_raw.get("relative_humidity_2m", 50)
        wind_speed = current_raw.get("wind_speed_10m", 10)
        weather_code = current_raw.get("weather_code", 0)
        condition, condition_text = _wmo_to_condition(weather_code)

        current = {
            "temperature_c": round(temp, 1),
            "humidity_pct": round(humidity, 1),
            "wind_speed_kmh": round(wind_speed, 1),
            "condition": condition,
            "condition_text": condition_text,
        }

        soil_insights = {
            "moisture_status": "सामान्य",
            "moisture_description": "मिट्टी में नमी की मात्रा अच्छी है। नियमित सिंचाई अनुसूची पर्याप्त है।"
        }

        dates = daily_raw.get("time", [])
        temp_maxes = daily_raw.get("temperature_2m_max", [])
        temp_mins = daily_raw.get("temperature_2m_min", [])
        precip_probs = daily_raw.get("precipitation_probability_mean", [])
        weather_codes = daily_raw.get("weather_code", [])
        wind_speeds = daily_raw.get("wind_speed_10m_max", [])
        humidities = daily_raw.get("relative_humidity_2m_mean", [])

        forecast_7day = []
        for i in range(min(7, len(dates))):
            d = datetime.strptime(dates[i], "%Y-%m-%d")
            day_code = weather_codes[i] if i < len(weather_codes) else 0
            precip_prob = precip_probs[i] if i < len(precip_probs) else 0
            
            # Downgrade rain/drizzle to partly cloudy if probability is too low to be realistic
            if precip_prob <= 20 and day_code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99]:
                day_code = 3
                
            day_cond, day_cond_text = _wmo_to_condition(day_code)
            forecast_7day.append({
                "date": dates[i],
                "day_name": d.strftime("%A"),
                "temp_max": round(temp_maxes[i], 1) if i < len(temp_maxes) else 35,
                "temp_min": round(temp_mins[i], 1) if i < len(temp_mins) else 25,
                "condition": day_cond,
                "condition_text": day_cond_text,
                "precip_probability_pct": precip_probs[i] if i < len(precip_probs) else 0,
                "wind_speed_kmh": round(wind_speeds[i], 1) if i < len(wind_speeds) else 10,
                "humidity_pct": round(humidities[i], 1) if i < len(humidities) else 50,
            })

        result = {
            "location": {"city": city, "state": state, "latitude": lat, "longitude": lon},
            "current": current,
            "ai_summary": None,
            "soil_insights": soil_insights,
            "forecast_7day": forecast_7day,
        }
        dashboard_cache[cache_key] = result
        return result

    except Exception as e:
        logger.error(f"Weather dashboard failed: {e} - returning safe defaults")
        now = datetime.now()
        fallback_forecast = []
        for i in range(7):
            d = now + timedelta(days=i)
            fallback_forecast.append({
                "date": d.strftime("%Y-%m-%d"),
                "day_name": d.strftime("%A"),
                "temp_max": 35,
                "temp_min": 25,
                "condition": "sunny",
                "condition_text": "Clear Sky",
                "precip_probability_pct": 10,
                "wind_speed_kmh": 10,
                "humidity_pct": 50,
            })

        return {
            "location": {"city": city, "state": state, "latitude": lat, "longitude": lon},
            "current": {
                "temperature_c": 35,
                "humidity_pct": 50,
                "wind_speed_kmh": 10,
                "condition": "sunny",
                "condition_text": "Clear Sky",
            },
            "ai_summary": None,
            "soil_insights": {
                "moisture_status": "सामान्य",
                "moisture_description": "मौसम डेटा उपलब्ध नहीं है - कृपया स्वयं मिट्टी की नमी की जांच करें।",
            },
            "forecast_7day": fallback_forecast,
        }

@router.get("/ai-advisory")
@limiter.limit("10/minute")
async def get_ai_advisory(
    request: Request,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    city: str = DEFAULT_CITY,
    state: str = DEFAULT_STATE,
    crop_name: str = None,
    days_since_planting: int = None,
    current_stage: str = None,
):
    # Include crop context in cache key so different crops get their own advisory
    cache_key = f"{lat:.2f},{lon:.2f}|{crop_name or ''}|{current_stage or ''}"
    if cache_key in advisory_cache:
        return advisory_cache[cache_key]

    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_mean,weather_code"
            ),
            "timezone": "Asia/Kolkata",
            "forecast_days": 7,
        }

        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            raw = response.json()

        daily_raw = raw.get("daily", {})
        target_language = "Hindi (using natural, conversational Devanagari script)"

        summary = _generate_ai_weather_summary(
            city, state, daily_raw, target_language,
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

    except Exception as e:
        logger.error(f"AI advisory failed: {e}")
        return {
            "ai_summary": "आज मौसम सामान्य रहने की उम्मीद है। फसल की नियमित निगरानी करते रहें और जरूरत पड़ने पर ही सिंचाई करें।",
            "daily_tip": "स्वस्थ फसल के लिए अच्छे बीजों का चयन करें और समय पर सिंचाई करें।",
            "moisture_status": "सामान्य",
            "moisture_description": "मिट्टी में नमी की मात्रा अच्छी है। नियमित सिंचाई अनुसूची पर्याप्त है।",
            "is_fallback": True
        }
