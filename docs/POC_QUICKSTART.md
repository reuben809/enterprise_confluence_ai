# 🚀 POC Quick Start Guide

**Goal:** Get your Confluence AI Assistant POC running in **2-3 hours**

---

## **Prerequisites**

✅ Docker & Docker Compose installed  
✅ Python 3.11+ installed  
✅ LM Studio downloaded ([lmstudio.ai](https://lmstudio.ai))  
✅ Confluence access (URL, Space Key, Personal Access Token)  
✅ 16GB+ RAM, 20GB+ disk space  

---

## **Step 1: Clone & Setup (10 minutes)**

```bash
# Clone repository
git clone https://github.com/reuben809/enterprise_confluence_ai.git
cd enterprise_confluence_ai

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## **Step 2: Configure Environment (5 minutes)**

Create `.env.local` file:

```bash
# Confluence Settings
BASE_URL=https://your-company.atlassian.net
SPACE_KEY=YOUR_SPACE
PAT=your_personal_access_token

# LLM Settings (LM Studio)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=local-model

# Infrastructure (defaults work for Docker)
QDRANT_URL=http://localhost:6333
MONGO_URI=mongodb://localhost:27017/
```

**Get Confluence PAT:**
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Copy token to `.env.local`

---

## **Step 3: Start Infrastructure (5 minutes)**

```bash
# Start MongoDB and Qdrant
docker-compose up -d mongo qdrant

# Verify services are running
docker-compose ps

# Should show:
# mongo    running   0.0.0.0:27017
# qdrant   running   0.0.0.0:6333
```

---

## **Step 4: Setup LM Studio (10 minutes)**

1. **Download LM Studio** from https://lmstudio.ai
2. **Install and open** LM Studio
3. **Download a model** (recommended):
   - **Mistral 7B Instruct** (fast, good quality)
   - **Llama 3 8B Instruct** (better quality, slower)
   - **Phi-3 Mini** (fastest, lower quality)

4. **Start local server:**
   - Click "Local Server" tab
   - Select your downloaded model
   - Click "Start Server"
   - Verify it shows: `Server running on http://localhost:1234`

5. **Test the server:**
   ```bash
   curl http://localhost:1234/v1/models
   # Should return JSON with model info
   ```

---

## **Step 5: Ingest Confluence Data (30-60 minutes)**

```bash
# Crawl Confluence pages
python -m ingestion.confluence_crawler

# This will:
# - Connect to your Confluence space
# - Download all pages
# - Store in MongoDB
# - Takes 5-10 minutes for 100 pages

# Verify data in MongoDB
python check_db.py
# Should show: "Found X pages in MongoDB"

# Generate embeddings
python -m ingestion.embedder

# This will:
# - Read pages from MongoDB
# - Create chunks
# - Generate dense + sparse embeddings
# - Store in Qdrant
# - Takes 20-40 minutes for 100 pages
```

**Note:** First run downloads embedding models (~500MB). Subsequent runs are faster.

---

## **Step 6: Start Application (5 minutes)**

```bash
# Terminal 1: Start API server
uvicorn chat.chat_api:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start Streamlit UI
streamlit run streamlit_app.py --server.port 8501
```

**Verify:**
- API: http://localhost:8000/health should return `{"status": "ok"}`
- UI: http://localhost:8501 should show chat interface

---

## **Step 7: Test the System (10 minutes)**

### Manual Test
1. Open http://localhost:8501
2. Check sidebar shows "🟢 API Connected"
3. Ask a question: "What is [something in your Confluence]?"
4. Verify:
   - Answer appears within 5 seconds
   - Sources are shown in sidebar
   - Citations are clickable

### Automated Test
```bash
# Customize test questions
nano tests/poc_test_questions.json

# Run test suite
python tests/run_poc_tests.py

# Review results
cat tests/poc_results.json
```

---

## **Step 8: Prepare Demo (30 minutes)**

1. **Select demo questions** (5-7 questions that showcase different capabilities)
2. **Test each question** and verify answers are good
3. **Review demo script:** `docs/POC_DEMO_SCRIPT.md`
4. **Prepare comparison** with Confluence search
5. **Set up screen sharing** (two browser windows side-by-side)

---

## **Quick Troubleshooting**

### ❌ "Cannot connect to API"
```bash
# Check if API is running
curl http://localhost:8000/health

# If not, restart:
uvicorn chat.chat_api:app --port 8000
```

### ❌ "No results found"
```bash
# Check if embeddings exist
docker exec -it qdrant curl http://localhost:6333/collections

# If empty, re-run embedder:
python -m ingestion.embedder
```

### ❌ "LLM timeout"
```bash
# Check LM Studio is running
curl http://localhost:1234/v1/models

# If not, restart LM Studio server
```

### ❌ "Slow responses"
- Use smaller model (7B instead of 13B)
- Enable GPU in LM Studio settings
- Reduce `top_k` in config.yaml (5 → 3)

---

## **What's Included in POC**

✅ **Core Features:**
- Hybrid search (semantic + keyword)
- Fast reranking (FlashRank)
- Streaming responses
- Source citations
- Multi-turn conversations
- Query preprocessing
- Feedback mechanism

✅ **Testing:**
- 10 test questions
- Automated test runner
- Results reporting

✅ **Documentation:**
- Demo script
- POC checklist
- Architecture docs

❌ **Not Included (Production Features):**
- Permission-aware search
- Multi-source connectors
- Analytics dashboard
- Incremental sync
- Agentic capabilities

---

## **Success Metrics**

Your POC is successful if:
- ✅ 80%+ accuracy on test questions
- ✅ < 5 second average response time
- ✅ Users prefer it over Confluence search
- ✅ Sources are accurate and relevant
- ✅ System is stable (no crashes)

---

## **Next Steps**

### After Successful POC:
1. **Gather feedback** from stakeholders
2. **Measure impact** (time saved, satisfaction)
3. **Plan production** deployment
4. **Prioritize enhancements** (permissions, multi-source, etc.)

### If POC Needs Improvement:
1. **Analyze failures** (which questions failed?)
2. **Improve prompts** (see `chat/prompt_template.py`)
3. **Add more data** (crawl more Confluence spaces)
4. **Upgrade model** (try larger/better model)

---

## **Resources**

- **Full Documentation:** `docs/SYSTEM_DOCUMENTATION.md`
- **Demo Script:** `docs/POC_DEMO_SCRIPT.md`
- **Checklist:** `docs/POC_CHECKLIST.md`
- **Architecture:** `docs/architecture.png`
- **Troubleshooting:** `docs/TROUBLESHOOTING.md`

---

## **Support**

- **GitHub Issues:** https://github.com/reuben809/enterprise_confluence_ai/issues
- **Documentation:** `docs/` folder
- **Logs:** `docker-compose logs` or check terminal output

---

**Estimated Time:** 2-3 hours total

**Good luck! 🎉**
