# 🚀 RAG System Run Steps

## Prerequisites

Before running, ensure you have:

- [ ] **Docker Desktop** installed and running
- [ ] **LM Studio** installed with a model loaded
- [ ] **Python 3.11+** with virtual environment set up
- [ ] **Dependencies** installed (`pip install -r requirements.txt`)

---

## Quick Start (4 Steps)

```powershell
# 1. Start Docker services
docker-compose up -d mongo qdrant

# 2. Start LM Studio with model loaded on port 1234

# 3. Start API
.venv\Scripts\python.exe -m uvicorn chat.chat_api:app --host 0.0.0.0 --port 8000 --reload

# 4. Start UI (new terminal)
.venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8501
```

**Access:** http://localhost:8501

---

## Full Setup (First Time)

### Step 1: Start Infrastructure

```powershell
cd C:\Users\reuben.joseph\PycharmProjects\enterprise_confluence_ai

# Start MongoDB and Qdrant
docker-compose up -d mongo qdrant

# Verify services are running
docker ps
```

**Expected output:**
| Container | Port | Purpose |
|-----------|------|---------|
| mongo | 27017 | Document cache |
| qdrant | 6333 | Vector database |

---

### Step 2: Configure LM Studio

1. Open LM Studio
2. Load a model (e.g., `openai/gpt-oss-20b` or smaller for speed)
3. Go to **Local Server** tab
4. Toggle ON:
   - ✅ Serve on Local Network
   - ✅ Enable CORS
5. Click **Start Server**
6. Verify: http://localhost:1234/v1/models

---

### Step 3: Activate Virtual Environment

```powershell
cd C:\Users\reuben.joseph\PycharmProjects\enterprise_confluence_ai
.\.venv\Scripts\Activate
```

---

### Step 4: Crawl Confluence (One-Time)

```powershell
# Configure .env.local with your Confluence details first:
# BASE_URL=https://your-confluence.company.com
# SPACE_KEY=YOUR_SPACE
# PAT=your-personal-access-token

python -m ingestion.confluence_crawler
```

---

### Step 5: Run Ingestion (One-Time)

```powershell
python -m ingestion.embedder
```

**Note:** This takes 30-60 minutes for ~30K chunks with hybrid embeddings.

---

### Step 6: Start API Server

```powershell
.venv\Scripts\python.exe -m uvicorn chat.chat_api:app --host 0.0.0.0 --port 8000 --reload
```

**Verify:** http://localhost:8000/health

---

### Step 7: Start Streamlit UI

```powershell
# Open a NEW terminal
cd C:\Users\reuben.joseph\PycharmProjects\enterprise_confluence_ai
.\.venv\Scripts\Activate
.venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8501
```

**Access:** http://localhost:8501

---

## Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| **Streamlit UI** | http://localhost:8501 | Chat interface |
| **FastAPI** | http://localhost:8000 | REST API |
| **API Docs** | http://localhost:8000/docs | Swagger UI |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | Vector DB UI |
| **LM Studio** | http://localhost:1234 | LLM server |
| **MongoDB** | localhost:27017 | Document DB |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Connection refused` on LM Studio | Check LM Studio server is running |
| `SSL certificate error` | Models need to be downloaded manually |
| No results returned | Check ingestion completed successfully |
| Slow responses | Use a smaller LLM model (7B) |
| UI shows no sources | Check API is running on port 8000 |

---

## Stop All Services

```powershell
# Stop Docker
docker-compose down

# Stop Python processes
# Press Ctrl+C in each terminal
```

---

## Daily Workflow

```powershell
# Morning startup:
docker-compose up -d mongo qdrant
# Start LM Studio
.venv\Scripts\python.exe -m uvicorn chat.chat_api:app --port 8000 --reload
.venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8501

# Access: http://localhost:8501
```
