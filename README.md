# Enterprise Confluence AI

**Intelligent Question-Answering for Confluence Documentation**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)

A production-ready **Retrieval-Augmented Generation (RAG)** system that enables natural language Q&A over your Confluence documentation. Built with hybrid search, local LLM inference, and enterprise-grade scalability.

![Architecture Overview](docs/architecture.png)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔍 **Hybrid Search** | Combines semantic (dense) + keyword (sparse) retrieval with RRF fusion |
| 🏠 **Offline-First** | All models run locally—no API keys, no data leaving your network |
| ⚡ **Fast Reranking** | FlashRank cross-encoder for sub-100ms reranking |
| 🎯 **Accurate Answers** | Grounded responses with source citations |
| 💬 **Streaming UI** | Real-time token streaming via Streamlit |
| 🔧 **LM Studio Ready** | Works with any OpenAI-compatible local LLM |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         INGESTION                                │
│  Confluence → MongoDB → Chunking → FastEmbed → Qdrant           │
│              (raw pages)  (1400/400 char)  (Dense+Sparse)        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                          QUERY                                   │
│  User → Streamlit → FastAPI → HybridRetriever → LocalReranker   │
│          :8501       :8000        ↓                  ↓          │
│                               Qdrant            LM Studio        │
│                             (RRF Fusion)       :1234             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- [LM Studio](https://lmstudio.ai/) (or any OpenAI-compatible server)

### 1. Clone & Install

```bash
git clone https://github.com/reuben809/enterprise_confluence_ai.git
cd enterprise_confluence_ai

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env.local` file:

```env
# Confluence Settings
BASE_URL=https://your-confluence.atlassian.net
SPACE_KEY=YOUR_SPACE
PAT=your_personal_access_token

# LLM Settings (LM Studio)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=your-model-name

# Infrastructure (defaults work for Docker)
QDRANT_URL=http://localhost:6333
MONGO_URI=mongodb://localhost:27017/
```

### 3. Start Infrastructure

```bash
# Start MongoDB and Qdrant
docker-compose up -d mongo qdrant

# Start LM Studio and load a model on port 1234
```

### 4. Run Ingestion (One-time)

```bash
# Crawl Confluence and generate embeddings
python -m ingestion.confluence_crawler
python -m ingestion.embedder
```

### 5. Start the Application

```bash
# Terminal 1: Start API server
uvicorn chat.chat_api:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start Streamlit UI
streamlit run streamlit_app.py --server.port 8501
```

Open http://localhost:8501 and start asking questions!

---

## 📁 Project Structure

```
enterprise_confluence_ai/
├── chat/
│   ├── chat_api.py           # FastAPI endpoints (/chat, /health, /feedback)
│   └── prompt_template.py    # LLM prompt templates
├── ingestion/
│   ├── confluence_crawler.py # Confluence page scraper
│   ├── embedder.py           # FastEmbed vectorization pipeline
│   └── text_cleaner.py       # Hierarchical text chunking
├── config/
│   └── settings.py           # Pydantic settings (env vars)
├── utils/
│   └── llm_client.py         # Async OpenAI SDK wrapper
├── retrieval.py              # HybridRetriever + LocalReranker
├── streamlit_app.py          # Chat UI application
├── models_cache/             # Local ONNX models (auto-downloaded)
│   ├── bge-small-en-v1.5/    # Dense embeddings (384d)
│   ├── Splade_PP_en_v1/      # Sparse embeddings
│   └── ms-marco-TinyBERT-L-2-v2/  # Reranker
├── docker-compose.yml        # Infrastructure setup
├── requirements.txt          # Python dependencies
└── docs/                     # Documentation
```

---

## ⚙️ Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_BASE_URL` | LM Studio endpoint | `http://localhost:1234/v1` |
| `LLM_MODEL` | Model name | `local-model` |
| `QDRANT_URL` | Vector database URL | `http://localhost:6333` |
| `QDRANT_COLLECTION` | Collection name | `confluence_vectors_fastembed` |
| `FASTEMBED_CACHE_PATH` | Model cache directory | `./models_cache` |
| `TOP_K` | Number of results | `5` |

---

## 🐳 Docker Deployment

```bash
# Full stack deployment
docker-compose up -d

# Services:
# - mongo:27017     - Document store
# - qdrant:6333     - Vector database
# - rag-api:8000    - FastAPI backend
# - streamlit:8501  - Web UI
```

---

## 📊 Performance

| Metric | Value |
|--------|-------|
| Ingestion Speed | ~1000 chunks/min |
| Retrieval Latency | ~50ms |
| Reranking Latency | ~100ms |
| Memory (API) | ~1 GB |

---

## 🛠️ Troubleshooting

| Issue | Solution |
|-------|----------|
| SSL Error on model download | Models are cached in `./models_cache`. Ensure they're pre-downloaded or set `cache_dir` parameter. |
| FlashRank fails to load | Set `cache_dir=./models_cache` in LocalReranker |
| No response from LLM | Verify LM Studio is running on port 1234 with a model loaded |
| Vector "name not found" | Delete Qdrant collection and re-run ingestion |

---

## 📚 Documentation

- [System Documentation](docs/SYSTEM_DOCUMENTATION.md) - Architecture deep-dive
- [Run Steps](docs/RUN_STEPS.md) - Detailed setup guide
- [Beginner's Guide](docs/BEGINNERS_GUIDE.md) - RAG concepts explained

---

## 🗺️ Roadmap

- [x] Hybrid Search (Dense + Sparse)
- [x] FlashRank Reranking
- [x] LM Studio Integration
- [x] Streamlit Chat UI
- [ ] MCP Server Integration
- [ ] Agentic RAG with multi-step reasoning
- [ ] MongoDB decommission (direct Qdrant metadata)

---

## 🙏 Acknowledgments

- [FastEmbed](https://github.com/qdrant/fastembed) - Fast ONNX embeddings
- [Qdrant](https://qdrant.tech/) - Vector database with hybrid search
- [FlashRank](https://github.com/PrithivirajDamodaran/FlashRank) - Ultra-fast reranking
- [LM Studio](https://lmstudio.ai/) - Local LLM inference
