# Krishi Khata Backend API (Agroo)

A robust, high-performance FastAPI backend designed to serve the Krishi Khata PWA, empowering Indian farmers with smart agriculture tools. This API handles everything from farm management and localized weather forecasting to digital ledger keeping and real-time mandi price caching.

## 🚀 Features

- **Ghost Authentication:** Frictionless onboarding flow mapping device footprints or quick PINs to authenticated sessions.
- **Smart Data Caching:** Includes a background scheduling system that fetches and caches daily Mandi prices from Data.gov.in (automatically refreshing at 6:00 AM IST to minimize API calls).
- **Farm-Aware Architecture:** All core endpoints (Khata entries, crop tracking) are scoped contextually to specific farms.
- **Kisan Khata (Ledger):** Full CRUD for transactional ledger entries, allowing farmers to track expenses and income seamlessly.
- **Chaupal (Community Chat):** Endpoints to power real-time community interactions and media sharing.
- **Modular Routing:** Clean, decoupled routers for Auth, Mandi, Khata, Weather, Crops, and Chat.

## 🛠️ Technology Stack

- **Framework:** FastAPI
- **Database:** SQLAlchemy 2.0 with PostgreSQL/SQLite compatibility
- **Migrations:** Alembic
- **Security:** bcrypt, passlib, PyJWT
- **External Integrations:** Firebase Admin, python-multipart (for uploads)
- **Server:** Uvicorn

## 📋 Prerequisites

- Python 3.9+
- pip (Python package installer)

## ⚙️ Installation & Setup

1. **Clone the repository and navigate to the backend directory:**
   ```bash
   cd agroo/server
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file in the root of the `server` directory and configure the necessary variables (e.g., Database URL, Secret Keys, Data.gov.in API keys).

   ```env
   # Example .env
   API_V1_STR=/api/v1
   DATAGOV_API_KEY=your_datagov_key_here
   ```

5. **Database Initialization:**
   The application automatically generates the required SQL tables on startup in development mode. For production, ensure you use Alembic migrations:
   ```bash
   alembic upgrade head
   ```

## 🚀 Running the Server

Start the development server with live reloading:

```bash
uvicorn app.main:app --reload --port 8001
```

The API will be available at `http://localhost:8001`.
You can access the auto-generated Swagger documentation at `http://localhost:8001/docs`.

## 📁 Directory Structure

```text
server/
├── app/
│   ├── config.py         # App settings and environment variables
│   ├── database.py       # SQLAlchemy engine and session setup
│   ├── main.py           # FastAPI application factory and lifespan events
│   ├── models/           # SQLAlchemy ORM models (Base, User, Farm, etc.)
│   ├── routers/          # API Route handlers (auth, mandi, khata, etc.)
│   ├── schemas/          # Pydantic models for request/response validation
│   └── services/         # Business logic and external API integrations
├── instance/             # Local database storage (if using SQLite)
├── uploads/              # Static directory for user-uploaded media
├── requirements.txt      # Python dependencies
└── alembic.ini           # Alembic migration configuration
```

## 🤝 Contributing

1. Create a feature branch (`git checkout -b feature/amazing-feature`)
2. Commit your changes (`git commit -m 'Add amazing feature'`)
3. Push to the branch (`git push origin feature/amazing-feature`)
4. Open a Pull Request

## 📄 License

This project is proprietary and confidential.
