# 🎓 Complete Beginner's Guide to Your RAG System

## Table of Contents
1. [What is RAG?](#1-what-is-rag)
2. [System Overview](#2-system-overview)
3. [Step-by-Step Data Flow](#3-step-by-step-data-flow)
4. [All Terminologies Explained](#4-terminologies)
5. [Tunable Parameters](#5-tunable-parameters)

---

## 1. What is RAG?

**RAG = Retrieval Augmented Generation**

Think of it like a smart assistant with a library:

```
Without RAG:
  User: "What is our vacation policy?"
  LLM: "I don't know your company policies" ❌

With RAG:
  User: "What is our vacation policy?"
  System: [Searches your documents] → Finds HR Policy page
  LLM: "According to your HR policy, you get 21 days..." ✅
```

**Your system:**
```
Confluence Pages → Chunks → Vectors → Qdrant → Search → LLM → Answer
```

---

## 2. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     YOUR RAG SYSTEM                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐            │
│  │Confluence│────▶│ MongoDB  │────▶│  Qdrant  │            │
│  │  Pages   │     │ (Cache)  │     │ (Vectors)│            │
│  └──────────┘     └──────────┘     └──────────┘            │
│       │                                  │                  │
│       │           INGESTION              │                  │
│       │          (One-time)              │                  │
│       ▼                                  │                  │
│  ┌──────────┐                            │                  │
│  │ FastEmbed│ ─ Creates Embeddings ──────┘                  │
│  │  (ONNX)  │                                               │
│  └──────────┘                                               │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  User Question                                              │
│       │                                                     │
│       ▼                                                     │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐            │
│  │ Retriever│────▶│ Reranker │────▶│   LLM    │───▶ Answer │
│  │ (Search) │     │(FlashRank)│    │(LM Studio)│            │
│  └──────────┘     └──────────┘     └──────────┘            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Step-by-Step Data Flow

### Phase 1: INGESTION (One-Time Setup)

**Step 1: Crawl Confluence**
```python
# File: ingestion/confluence_crawler.py
# What it does: Downloads all pages from Confluence

Confluence API → JSON response with page content
```

**Step 2: Store in MongoDB**
```python
# What it does: Saves raw page content for caching
{
  "page_id": "12345",
  "title": "Vacation Policy",
  "content_text": "All employees get 21 days..."
}
```

**Step 3: Chunking**
```python
# File: ingestion/text_cleaner.py
# What it does: Splits large documents into small pieces

BEFORE: One 5000-word document
AFTER:  20 small chunks of ~400 words each
```

**Why chunk?**
- LLMs have token limits
- Smaller chunks = more precise retrieval
- Better matching for specific questions

**Step 4: Embedding**
```python
# What it does: Converts text to numbers (vectors)

"Vacation policy gives 21 days" → [0.12, -0.34, 0.56, ... 384 numbers]
```

**Why?**
- Computers can't understand text directly
- Numbers allow mathematical similarity comparison
- Similar meanings = similar numbers

**Step 5: Store in Qdrant**
```python
# What it does: Stores vectors for fast searching
{
  "id": "chunk-123",
  "vector": {"dense": [0.12, ...], "sparse": {...}},
  "payload": {"title": "Vacation Policy", "chunk": "..."}
}
```

---

### Phase 2: QUERY (Every User Question)

**Step 1: User Asks Question**
```
"How many vacation days do I get?"
```

**Step 2: Convert Question to Vector**
```python
# Same embedding model as ingestion
"How many vacation days..." → [0.11, -0.35, 0.55, ...]
```

**Step 3: Search Qdrant (Hybrid Search)**
```python
# Two types of search happen:
# 1. DENSE search: Finds similar MEANING
# 2. SPARSE search: Finds exact KEYWORDS

Results are FUSED using RRF (Reciprocal Rank Fusion)
```

**Step 4: Rerank Results**
```python
# FlashRank cross-encoder scores each result
# More accurate than initial search

Input: Top 20 chunks from search
Output: Top 5 most relevant chunks
```

**Step 5: Generate Answer**
```python
# LLM receives:
# - Context (the 5 chunks)
# - User question
# - Chat history

Prompt = f"""
Based on these documents:
{chunks}

Answer this question:
{user_question}
"""
```

---

## 4. Terminologies

### A. Embedding Terms

| Term | Meaning | Analogy |
|------|---------|---------|
| **Embedding** | Text converted to numbers | Like GPS coordinates for meaning |
| **Vector** | Array of numbers [0.1, 0.2, ...] | A point in space |
| **Dimension** | How many numbers in vector | 384 for your dense model |
| **Dense Embedding** | Fixed-size vector (384 dims) | Full coordinate system |
| **Sparse Embedding** | Variable-size, mostly zeros | Only important keywords marked |

### B. Search Terms

| Term | Meaning | Analogy |
|------|---------|---------|
| **Semantic Search** | Find by meaning | "car" finds "automobile" |
| **Keyword Search** | Find exact words | "XJ-500" finds "XJ-500" only |
| **Hybrid Search** | Both combined | Best of both worlds |
| **Cosine Similarity** | Measure of vector similarity | Angle between two arrows |

### C. Retrieval Terms

| Term | Meaning | Analogy |
|------|---------|---------|
| **Top-K** | How many results to return | "Give me top 5 matches" |
| **Reranking** | Re-score results for accuracy | Second opinion from expert |
| **Cross-Encoder** | Model that compares query+doc together | More accurate but slower |
| **RRF (Reciprocal Rank Fusion)** | Method to combine two rankings | Averaging two judges' scores |

### D. Model Terms

| Term | Meaning | Your System |
|------|---------|-------------|
| **ONNX** | Model format for fast CPU inference | FastEmbed uses this |
| **LLM** | Large Language Model | LM Studio (20B params) |
| **Tokenizer** | Splits text into pieces | "hello world" → ["hello", "world"] |
| **Inference** | Running model to get output | Asking the model a question |

---

## 5. Tunable Parameters

### 5.1 Chunking Parameters

```python
# File: ingestion/text_cleaner.py

parent_chunk_size = 1400  # Parent chunk size in characters
child_chunk_size = 400    # Child chunk size in characters
parent_overlap = 200      # Overlap between parent chunks
child_overlap = 80        # Overlap between child chunks
```

**Effects:**

| Parameter | If INCREASED | If DECREASED |
|-----------|--------------|--------------|
| `parent_chunk_size` | More context per chunk, fewer chunks total | Less context, more chunks |
| `child_chunk_size` | More text per search result | More precise matching |
| `overlap` | Less chance of cutting important sentences | Fewer duplicate embeddings |

**Recommendations:**
- For **technical docs**: Smaller chunks (300-400)
- For **narrative content**: Larger chunks (600-800)
- For **tables/lists**: Keep overlap low

---

### 5.2 Retrieval Parameters

```python
# File: chat/chat_api.py

limit = 20  # How many results from initial search
top_k = 5   # How many final results after reranking
```

| Parameter | If INCREASED | If DECREASED |
|-----------|--------------|--------------|
| `limit` (search) | More candidates for reranker, slower | Fewer options, might miss relevant |
| `top_k` (final) | More context to LLM, longer prompts | Less context, faster responses |

**Recommendations:**
- `limit`: 15-30 (enough for reranker to work with)
- `top_k`: 3-7 (balance between context and noise)

---

### 5.3 Embedding Parameters

```python
# File: ingestion/embedder.py

BATCH_SIZE = 64  # How many chunks to embed at once
```

| Parameter | If INCREASED | If DECREASED |
|-----------|--------------|--------------|
| `BATCH_SIZE` | Faster overall, more memory used | Slower, less memory |

**Memory Rule:**
- 8GB RAM: Use 32-64
- 16GB RAM: Use 64-128
- 32GB+ RAM: Use 128-256

---

### 5.4 Model Selection

**Dense Embedding Model:**
```
BAAI/bge-small-en-v1.5
- Dimensions: 384
- Size: ~100MB
- Speed: Fast
- Quality: Good for English
```

**Alternatives:**
| Model | Dimensions | Speed | Quality |
|-------|------------|-------|---------|
| bge-small | 384 | ⚡⚡⚡ | ★★★ |
| bge-base | 768 | ⚡⚡ | ★★★★ |
| bge-large | 1024 | ⚡ | ★★★★★ |

**Tradeoff:** Higher dimensions = better quality but slower

---

### 5.5 LLM Parameters

```python
# File: .env.local

LLM_MODEL=openai/gpt-oss-20b
```

| Model Size | Speed | Quality | Memory |
|------------|-------|---------|--------|
| 3B params | ⚡⚡⚡ | ★★ | 4GB |
| 7B params | ⚡⚡ | ★★★ | 8GB |
| 13B params | ⚡ | ★★★★ | 16GB |
| 20B params | 🐌 | ★★★★★ | 24GB+ |

**Your current:** 20B (highest quality, slowest)

---

### 5.6 Environment Variables Summary

```bash
# .env.local - All tunable settings

# Database
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=confluence_vectors_fastembed

# LLM
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=openai/gpt-oss-20b  # 👈 Change for faster responses

# Embeddings
FASTEMBED_CACHE_PATH=./models_cache  # Where models are stored

# Retrieval
TOP_K=5  # 👈 Increase for more context, decrease for speed
```

---

## 6. Performance Tuning Cheatsheet

| Goal | What to Change |
|------|----------------|
| **Faster responses** | Use smaller LLM (7B), reduce `top_k` |
| **More accurate answers** | Increase `limit`, use larger embedding model |
| **Less memory usage** | Reduce `BATCH_SIZE`, disable sparse embeddings |
| **Better table search** | Keep small `child_chunk_size` |
| **Fewer hallucinations** | Reduce `top_k` to only most relevant |

---

## 7. Example: Following a Query

Let's trace what happens when you ask: **"What is our vacation policy?"**

```
╔═══════════════════════════════════════════════════════════════╗
║                    RAG PIPELINE FLOW DIAGRAM                  ║
╚═══════════════════════════════════════════════════════════════╝

┌───────────────────────────────────────────────────────────────┐
│  STEP 1: USER INPUT                                           │
│  "What is our vacation policy?"                               │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│  STEP 2: EMBEDDING (FastEmbed)                                │
│  • Dense Vector: [0.12, -0.34, 0.56, ...] (384 dimensions)    │
│  • Sparse Vector: {vacation: 0.8, policy: 0.7, ...}           │
└─────────────────┬─────────────────────────┬───────────────────┘
                  │                         │
         ┌────────▼────────┐       ┌────────▼────────┐
         │  Dense Search   │       │  Sparse Search  │
         │                 │       │                 │
         │  Semantic       │       │  Keyword        │
         │  Similarity     │       │  Matching       │
         │                 │       │                 │
         │  Finds:         │       │  Finds:         │
         │  • time off     │       │  • "vacation"   │
         │  • leave        │       │    (exact)      │
         │  • PTO          │       │                 │
         └────────┬────────┘       └────────┬────────┘
                  │                         │
                  └────────┬────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  STEP 3: QDRANT SEARCH                                        │
│  RRF (Reciprocal Rank Fusion)                                 │
│  Combines both dense and sparse search rankings               │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│  STEP 4: TOP 20 CANDIDATES                                    │
│  1. "HR Policy - Vacation Days" (score: 0.92)                 │
│  2. "Employee Benefits Overview" (score: 0.87)                │
│  3. "Time-Off Request Process" (score: 0.85)                  │
│  4. ...                                                        │
│  20. ...                                                       │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│  STEP 5: FLASHRANK RERANKING                                  │
│  Cross-encoder model re-scores each candidate                 │
│  Selects Top 5 most relevant chunks                           │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│  STEP 6: PROMPT CONSTRUCTION                                  │
│  """                                                           │
│  Context:                                                      │
│  [1] HR Policy - Vacation Days: All employees get 21 days...  │
│  [2] Employee Benefits: In addition to vacation...            │
│  [3] ...                                                       │
│                                                                │
│  Question: What is our vacation policy?                       │
│  """                                                           │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│  STEP 7: LLM RESPONSE (LM Studio)                             │
│  "According to the HR Policy, all employees receive           │
│   21 vacation days per year..."                               │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│  STEP 8: STREAMED TO UI                                       │
│  → Tokens sent one-by-one to user interface                   │
│  → Source documents shown in sidebar                          │
└───────────────────────────────────────────────────────────────┘
```

---

## 8. Common Issues & Fixes

| Problem | Cause | Fix |
|---------|-------|-----|
| Wrong answers | Not enough relevant chunks | Increase `limit` |
| Slow responses | LLM too large | Use 7B model |
| Missing keywords | Sparse disabled | Enable sparse embeddings |
| Out of memory | Batch size too high | Reduce `BATCH_SIZE` |
| Tables not found | Chunked incorrectly | Use smaller `child_chunk_size` |
