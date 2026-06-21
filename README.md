# Krishi Khata — Backend API

A FastAPI backend that powers the Krishi Khata PWA. It handles farm and ledger management, crop tracking, real-time community chat, mandi (market) price data, AI-driven weather advisories, and labor management.

Deployed on **Render**. Database hosted on **Neon (PostgreSQL)**.

---

## What It Does

### API Modules

| Prefix | Router | Responsibility |
|---|---|---|
| `/api/v1/auth` | `auth.py` | Device-ID + PIN registration and JWT login |
| `/api/v1/khata` | `khata.py` | Farm ledger — income and expense entries |
| `/api/v1` | `crop.py` | Farms, crop seasons, AI diary, photo uploads |
| `/api/v1/mandi` | `mandi.py` | Market price history and metadata |
| `/api/v1/weather` | `weather.py` | Weather data with Gemini AI advisory |
| `/api/v1/chat` | `chat.py` | WebSocket community chat (Kisan Chaupal) |
| `/api/v1` | `laborers.py` | Farm labor attendance and wage tracking |
| `/api/health` | `main.py` | Health check endpoint |

### Authentication

The app uses a **device-ID + PIN** system — no email or phone number needed. On registration, the device ID and a hashed PIN are stored. Login returns a JWT that expires after 90 days (long-lived to accommodate users in low-connectivity areas).

A `ENABLE_DEV_BYPASS=true` flag in `.env` can skip JWT checks entirely during local development.

### Mandi Price Data (data.gov.in)

Prices are fetched on-demand rather than on a schedule. When the frontend requests prices for a commodity and district, the server checks if recent data exists (within the last 7 days). If not, it pulls up to 30 days of history from the `data.gov.in` API, stores it in the database, and returns it. This keeps memory usage low and avoids pulling data for regions nobody is looking at.

A seeder in `main.py` populates a few commodity/district combinations with mock price data when the app runs in development mode (`FLASK_ENV=development`), so the frontend works without needing live API keys.

### AI Features (Gemini)

The backend uses Google's `google-genai` SDK to power two features:

- **Smart Crop Diary** — analyzes the farmer's crop history and diary entries and returns insights
- **Weather Advisory** — generates farm-specific advice based on the current forecast

The language of the AI response (Hindi or English) is controlled by the `Accept-Language` header sent by the frontend, so no separate translation step is needed.

### Community Chat (WebSocket)

The `/api/v1/chat/ws/chat` endpoint upgrades HTTP connections to persistent WebSockets. The JWT is passed as a `?token=` query parameter. Unauthenticated or expired connections are rejected before the upgrade completes.

### Rate Limiting

`slowapi` is applied to write-heavy routes and AI generation endpoints to prevent abuse. A custom middleware also sets `no-store` cache headers on all `GET /api/*` responses to stop CDNs or browsers from serving stale data.

### CORS

Allowed origins are defined explicitly:
- `http://localhost:5173` and `localhost:5174` (Vite dev server)
- `https://krishi-khata.vercel.app`
- Any Vercel preview URL matching `^https://krishi-khata(-[a-z0-9]+)?\.vercel\.app$`

---

## Tech Stack

| Category | Library / Version |
|---|---|
| Framework | FastAPI 0.136 |
| Server | Uvicorn 0.46 |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic 1.18 |
| Database | PostgreSQL (Neon) / SQLite (dev) |
| Validation | Pydantic 2.13, pydantic-settings |
| Auth | PyJWT 2.12, passlib + bcrypt |
| AI | google-genai |
| Translation | deep-translator |
| Rate limiting | slowapi 0.1.9 |
| HTTP client | httpx |
| WebSocket | websockets 16 |
| Caching | cachetools |

---

## Getting Started

### Prerequisites

- Python 3.10–3.13
- PostgreSQL instance (or use the default SQLite for local dev)

### 1. Set up a virtual environment

```bash
cd agroo/server

# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the `server/` folder:

```env
# App environment
FLASK_ENV=development

# Secret key (used for general signing — separate from JWT)
SECRET_KEY=change-me-in-production

# JWT — REQUIRED. Generate with:
# python -c "import secrets; print(secrets.token_urlsafe(64))"
JWT_SECRET_KEY=your-64-char-secret-here

# Database
# SQLite is used by default if this is not set:
DATABASE_URL=postgresql://user:password@localhost:5432/agroo

# Google Gemini (AI features)
GEMINI_API_KEY=your-gemini-api-key

# data.gov.in (Mandi prices)
DATAGOV_API_KEY=your-datagov-api-key

# Dev-only: skip JWT validation (never set true in production)
ENABLE_DEV_BYPASS=false
```

> **Note:** The server will refuse to start if `JWT_SECRET_KEY` is not set.

### 4. Run database migrations

```bash
alembic upgrade head
```

If you are running locally with SQLite (the default), the tables are also created automatically on startup via `Base.metadata.create_all()`, so Alembic is optional for quick local testing.

### 5. Start the server

```bash
uvicorn app.main:app --reload --port 8001
```

- API base: `http://localhost:8001`
- Interactive docs (Swagger UI): `http://localhost:8001/docs`
- Health check: `http://localhost:8001/api/health`

---

## Folder Structure

```
server/
├── app/
│   ├── config.py           # Pydantic settings — reads .env, validates required vars
│   ├── database.py         # SQLAlchemy engine setup and session factory
│   ├── dependencies.py     # Shared FastAPI dependencies (auth, rate limiter)
│   ├── main.py             # App factory, middleware, router registration, dev seeder
│   ├── models/
│   │   ├── user.py         # User (device ID, hashed PIN, name)
│   │   ├── farm.py         # Farm (name, area, soil type, district)
│   │   ├── crop.py         # CropSeason + CropDiaryEntry + CropStage
│   │   ├── crop_data_cache.py  # Cached external crop reference data
│   │   ├── khata.py        # LedgerEntry (income/expense)
│   │   ├── laborer.py      # Laborer and attendance records
│   │   ├── mandi.py        # MandiPriceHistory (commodity, district, date, price)
│   │   ├── chat.py         # ChatMessage
│   │   └── translation.py  # Translation cache
│   ├── routers/
│   │   ├── auth.py         # POST /register, POST /login
│   │   ├── crop.py         # Farm and crop season CRUD, diary, AI analysis
│   │   ├── khata.py        # Ledger entry CRUD
│   │   ├── laborers.py     # Laborer management
│   │   ├── mandi.py        # Price history + metadata endpoint
│   │   ├── weather.py      # Weather + Gemini AI advisory
│   │   └── chat.py         # WebSocket chat
│   ├── schemas/            # Pydantic request/response models for each router
│   ├── services/           # Business logic (currently minimal — logic lives in routers)
│   └── utils/              # Shared utility functions
├── instance/               # SQLite database file (local dev only, gitignored)
├── uploads/                # User-uploaded crop photos (served as static files)
├── scripts/                # One-off maintenance scripts
├── requirements.txt        # Pinned production dependencies
└── alembic.ini             # Alembic migration configuration
```

---

## Development Notes

- **Mock data seeder**: When `FLASK_ENV=development`, `main.py` seeds two demo farms and 30 days of price history for common commodities (Wheat, Rice, Onion, etc.) so the frontend works without any external API calls.
- **SQLite default**: If `DATABASE_URL` is not set, the app uses `instance/agroo.db`. This is fine for local dev but not for production.
- **Uploads**: Profile and crop photos are stored in `uploads/` and served at `/uploads/<filename>`. This directory is created automatically if it doesn't exist.
- **Migration scripts**: `add_laborer_column.py` and `migrate_auth.py` in the root are one-off migration helpers from earlier in the project. They are safe to ignore unless you are upgrading an older database.

---

## License

Proprietary. Do not distribute without permission.
