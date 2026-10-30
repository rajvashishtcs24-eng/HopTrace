# HopTrace

**ISP Network Fault Localisation and Subscriber Operations**  
*hackFront India · Theme T3: Telecom & Connectivity (Running a Village Internet Business)*

HopTrace is an intelligent network diagnostic and operations system designed for rural village Internet Service Providers (ISPs). It combines graph-based network topology modeling, explainable fault localisation, and subscriber impact analysis to help village operators detect outages, identify root causes, and notify affected community members in local languages.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.13 (`brew install python@3.13` on macOS)
- Node.js & npm (for frontend)

### 1. Backend Setup
```bash
# Setup virtual environment
python3.13 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt

# Configure environment
cp .env.example .env

# Run FastAPI development server
backend/.venv/bin/uvicorn app.main:app --reload --port 8000 --app-dir backend
```
- **API Swagger Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
- **Web UI:** [http://localhost:5173](http://localhost:5173)

### 3. Run Backend Tests
From repository root:
```bash
backend/.venv/bin/python -m pytest -v
```

---

## 🏛️ System Architecture

```
                      +-----------------------------+
                      | React Frontend (Vite) :5173 |
                      +--------------+--------------+
                                     | HTTP REST
                                     v
                 +---------------------------------------+
                 |       FastAPI Application (:8000)     |
                 |      lifespan: init_db, seed_topology |
                 +-------------------+-------------------+
                                     |
         +---------------------------+---------------------------+
         |                           |                           |
         v                           v                           v
+------------------+       +-------------------+       +-------------------+
| Operational DB   |       | Provider Registry |       | Engine Facade     |
| SQLite           |       | (Topology,        |       | HopTraceEngine    |
| (Subscribers,    |       |  Dependencies,    |       | (Singleton)       |
|  Reminders,      |       |  Explanations)    |       +---------+---------+
|  Incidents)      |       +---------+---------+                 |
+------------------+                 |                 +---------+---------+
                                     v                 v                   v
                           +-------------------+ +-------------+ +-----------------+
                           | Sarvam AI /       | | In-Memory   | | Neo4j Aura /    |
                           | Unavailable       | | Graph Store | | Live Database   |
                           +-------------------+ +-------------+ +-----------------+
```

---

## 📚 Documentation Index

Detailed specifications and developer guides are located in `docs/`:

- 📋 [**API Contract (`docs/api-contract.md`)**](docs/api-contract.md): Strict HTTP REST API contract for all endpoints, request bodies, and JSON responses.
- 📘 [**Backend Handover Guide (`docs/backend-handover.md`)**](docs/backend-handover.md): Comprehensive developer handover document covering architecture, setup, endpoints, engine integration, limitations, and troubleshooting.
- 🕸️ [**Graph Model & Engine (`docs/graph-model.md`)**](docs/graph-model.md): Detailed specification of the Neo4j schema, Cypher queries, simulated telemetry model, and explainable fault localization algorithms.
- 🧪 [**Test Plan & Verification Matrix (`docs/test-plan.md`)**](docs/test-plan.md): Complete backend test suite breakdown, verification matrix (144 passed / 2 skipped), and external service prerequisites.

---

## 👥 Team Ownership & Modules

- **Member 1 (Graph Engine):**  
  Owns `backend/app/engine/` (Neo4j driver, Cypher queries, in-memory graph store, diagnostic engine, simulated telemetry generator).
- **Member 2 (Backend & Operations):**  
  Owns `backend/app/api/`, `backend/app/providers/`, `backend/app/schemas/`, `backend/app/db/`, `backend/app/config.py`, `backend/app/main.py`, `tests/api/`, and backend documentation.
- **Member 3 (Frontend):**  
  Owns `frontend/` (React, TypeScript, Vite dev server, operator dashboard UI).
