```markdown
# Krishi Khata Backend API

A high-performance, asynchronous FastAPI backend engineered to power the Krishi Khata progressive web application. This service manages context-aware digital accounting ledgers, dynamic agricultural crop timelines, rate-limited real-time communication gateways, and multi-layered localized external data integrations for Indian farmers.

The production engine is deployed on **Render** and backed by a **Neon PostgreSQL** database layer.

---

## 🛠️ System Architecture & Updated Core Features

### 1. Just-In-Time (JIT) Mandi Price Pipeline
*   **The Problem:** Traditional batch scraping of the heavy `data.gov.in` (Agmarknet) database via fixed cron routines causes massive memory overhead and introduces stale data or unnecessary API usage for unsearched regions.
*   **The Solution:** Transitioned to an on-demand JIT caching model. When an endpoint queries history for a specific commodity and district combination, the system checks the local repository. If data is absent or insufficient ($< 7$ days), it fires a targeted synchronous backfill request to the government API, pulling up to 30 days of real history, bulk-upserting records via SQLAlchemy, and caching them instantly. Subsequent regional requests load in sub-200ms execution times.

### 2. Multi-Layer Bilingual AI Engine (Gemini RAG)
*   **Context Injection:** Integrates Google's Generative AI SDK to drive the AI Crop Doctor and localized weather advisories.
*   **Runtime Localization:** Rather than managing translated text states on the database side, the backend intercepts incoming `Accept-Language` headers (e.g., `hi` or `en`). It dynamically alters the underlying Gemini system instructions mid-flight, mandating the model to process, reason, and stream responses natively in clear, conversational agricultural Hindi (Devanagari script) or English based purely on consumer state.

### 3. Hardened WebSocket Gateway
*   **Token Verification:** The real-time "Kisan Chaupal" community chat uses persistent WebSockets (`/api/v1/chat/ws/chat`). 
*   **State Security:** Following a security review, the connection handshake isolates incoming JWT authorization tokens passed securely via query parameters. Unauthenticated or expired socket requests are aggressively dropped with a `403 Forbidden` response before upgrading the protocol, insulating the event loop from unauthorized payload overhead.

### 4. Traffic Control & Security Auditing
*   **API Rate Limiting:** Bound `slowapi` middleware across core transaction writing routes and AI generation paths to prevent burst-abuse or denial-of-service vectors on resource-heavy routes.
*   **Surgical CORS Restrictions:** Implemented strict origin filtering handling dynamic client environments using localized regular expression matchers (`allow_origin_regex`) ensuring security coverage for Vercel deployment strings while preserving localhost pipelines.

### 5. Consolidated Metadata Engine
*   **Optimized Queries:** Added dedicated `GET /api/v1/mandi/metadata` routing to feed searchable frontend Combobox UI selectors. The endpoint combines hardcoded regional baselines with `DISTINCT` transactional parameters recorded across tracking layers to return cleanly structured, deduplicated, alphabetized search indices.

---

## 🏗️ Technology Stack

*   **Framework:** FastAPI (Asynchronous Server Gateway Interface)
*   **Task Management:** Native ASGI `BackgroundTasks` for non-blocking asynchronous I/O writes
*   **Database & ORM:** SQLAlchemy 2.0 (PostgreSQL/SQLite unified pooling model)
*   **Database Migrations:** Alembic
*   **Security & Gateway:** PyJWT, Passlib (Bcrypt hashing binaries)
*   **AI Framework:** Google Generative AI Engine (`google-generativeai`)
*   **Rate Limiter:** Slowapi (Token bucket algorithm wrappers)
*   **Server Engine:** Uvicorn

---

## 📋 Prerequisites & Local Development Setup

### System Dependencies
*   Python 3.10 to Python 3.13
*   PostgreSQL instance or local SQLite environment

### Step 1: Initialize Workspace Environment
Navigate to the root server path and spin up a clean virtual runtime:

```bash
cd agroo/server

# Linux/macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate

```

### Step 2: Install Package Targets

```bash
pip install -r requirements.txt

```

### Step 3: Environment Variables configuration

Generate a `.env` schema file in the server root directory and adjust access parameters:

```env
# API Global Base Path
API_V1_STR=/api/v1

# Security Infrastructure
SECRET_KEY=your_secure_256bit_jwt_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Database Target String
DATABASE_URL=postgresql://user:password@localhost:5432/krishikhata
# For quick local prototyping fallback: sqlite:///./sql_app.db

# Third Party Access Keys
DATAGOV_API_KEY=your_official_data_gov_in_api_key
GEMINI_API_KEY=your_google_ai_studio_api_key

```

### Step 4: Run Migrations & Synchronize Database

Ensure your database schemas are current before launching the ASGI worker loop:

```bash
alembic upgrade head

```

---

## 🚀 Running the API Server

Launch the Uvicorn engine bound to your target execution port:

```bash
uvicorn app.main:app --reload --port 8001

```

* **Live Backend Endpoints:** Accessible locally via `http://localhost:8001`
* **Interactive API Specifications:** Self-documenting OpenAPI specifications can be evaluated at `http://localhost:8001/docs`

---

## 📁 Updated Directory Layout

```text
server/
├── app/
│   ├── config.py         # Global application setting definitions and type-validated envs
│   ├── database.py       # Async engine configuration and context-bound database sessions
│   ├── main.py           # Application instantiation, middleware configurations, and execution lifespans
│   ├── models/           # Declarative database mapping definitions (User, Farm, Ledger, MandiPriceHistory)
│   ├── routers/          # Modularized routing modules (auth, mandi, khata, weather, chat)
│   ├── schemas/          # Strictly typed Pydantic models handling sanitization and request validation
│   └── services/         # Decoupled business rules engine and background API consumers (Gemini, Weather APIs)
├── instance/             # Local database file sandbox (for active development SQLite configs)
├── requirements.txt      # Fixed version tracking schemas for production environments
└── alembic.ini           # System schema control engine instructions

```

---

## 📄 Licensing & Permissions

This system architecture, including database definitions and predictive data processing workflows, remains proprietary and confidential. Unauthorized redistribution or external staging is strictly prohibited.

```

```
