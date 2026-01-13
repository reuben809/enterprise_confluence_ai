# 🎯 POC Demo Script

## **Objective**
Demonstrate that the Confluence AI Assistant can answer employee questions **faster and more accurately** than manual Confluence search.

**Duration:** 10-15 minutes

---

## **Setup (Before Demo)**

### 1. Start Services
```bash
# Terminal 1: Start infrastructure
docker-compose up -d mongo qdrant

# Terminal 2: Start LM Studio
# Load a model (e.g., Mistral 7B, Llama 3 8B)
# Ensure it's running on http://localhost:1234

# Terminal 3: Start API
uvicorn chat.chat_api:app --host 0.0.0.0 --port 8000

# Terminal 4: Start UI
streamlit run streamlit_app.py --server.port 8501
```

### 2. Verify Health
- Open http://localhost:8501
- Check that API status shows "🟢 API Connected"
- Test with a simple question: "What is Confluence?"

### 3. Prepare Comparison
- Open Confluence in another browser tab
- Have 2-3 test questions ready

---

## **Demo Flow**

### **Part 1: The Problem (2 minutes)**

**Narrative:**
> "Every day, our employees spend hours searching for information in Confluence. 
> Let me show you the typical experience..."

**Demo:**
1. Open Confluence search
2. Search for: "How do I deploy to production?"
3. Show results:
   - 50+ pages returned
   - Irrelevant results mixed in
   - No direct answer
   - User has to click through multiple pages
   - Takes 5-10 minutes to find the right info

**Key Point:** 
> "This wastes time and frustrates employees. What if we could get instant, accurate answers?"

---

### **Part 2: The Solution (5 minutes)**

**Narrative:**
> "Our AI Assistant changes this. Watch..."

**Demo Question 1: Simple Factual Query**
```
Question: "What is our vacation policy?"

Expected Result:
- Instant answer (< 5 seconds)
- Clear, structured response
- Direct citations to HR handbook
- No need to read full documents
```

**Highlight:**
- ✅ Speed: 5 seconds vs 5 minutes
- ✅ Accuracy: Direct answer with sources
- ✅ Convenience: No clicking through pages

---

**Demo Question 2: Procedural Query**
```
Question: "How do I set up VPN access?"

Expected Result:
- Step-by-step instructions
- Prerequisites listed
- Links to relevant guides
- Troubleshooting tips
```

**Highlight:**
- ✅ Completeness: All steps in one place
- ✅ Context: Includes prerequisites and troubleshooting
- ✅ Citations: Links to official docs for details

---

**Demo Question 3: Technical Query**
```
Question: "What are the API authentication methods?"

Expected Result:
- List of methods (OAuth, API keys, JWT)
- Brief explanation of each
- Links to detailed documentation
- Code examples if available
```

**Highlight:**
- ✅ Technical Accuracy: Correct information
- ✅ Structured: Easy to scan and understand
- ✅ Actionable: Links to implementation guides

---

### **Part 3: Advanced Features (3 minutes)**

**Demo: Multi-Turn Conversation**
```
Question 1: "How do I deploy to production?"
[Get answer]

Question 2: "What if the deployment fails?"
[System understands context, provides troubleshooting]

Question 3: "Who should I contact for help?"
[System provides on-call information]
```

**Highlight:**
- ✅ Context Awareness: Remembers conversation
- ✅ Natural: Feels like talking to a colleague
- ✅ Comprehensive: Covers follow-up questions

---

**Demo: Source Verification**
```
Show sidebar with sources
Click on a source link
Verify information matches
```

**Highlight:**
- ✅ Trustworthy: All answers are grounded in docs
- ✅ Verifiable: Easy to check sources
- ✅ Up-to-date: Uses latest Confluence content

---

### **Part 4: Comparison (2 minutes)**

**Side-by-Side:**

| Metric | Confluence Search | AI Assistant |
|--------|-------------------|--------------|
| Time to Answer | 5-10 minutes | < 5 seconds |
| Accuracy | Hit or miss | High (grounded in docs) |
| User Experience | Frustrating | Delightful |
| Learning Curve | None | None |
| Citations | Manual | Automatic |

---

### **Part 5: Technical Highlights (2 minutes)**

**For Technical Stakeholders:**

**Architecture:**
- ✅ **Privacy-First**: All data stays on-premises
- ✅ **No Vendor Lock-in**: Uses local LLMs (LM Studio)
- ✅ **Scalable**: Handles 1000s of documents
- ✅ **Fast**: Hybrid search + reranking < 100ms

**Technology Stack:**
- Vector Database: Qdrant (hybrid search)
- Embeddings: FastEmbed (local, no API calls)
- LLM: LM Studio (any model, fully local)
- Reranking: FlashRank (sub-100ms)
- UI: Streamlit (modern, responsive)

**Key Differentiators:**
1. **Hybrid Search**: Combines semantic + keyword search
2. **Local-First**: No data sent to OpenAI/Anthropic
3. **Production-Ready**: Docker deployment, monitoring
4. **Extensible**: Easy to add more data sources

---

## **Handling Questions**

### **Q: How accurate is it?**
**A:** "We've tested it on 10 common questions with 80%+ accuracy. The system only uses information from your Confluence docs, so answers are grounded in your actual documentation."

### **Q: What if it gives wrong answers?**
**A:** "Every answer includes source citations. Users can verify information by clicking the source links. We also have a feedback mechanism to improve over time."

### **Q: How much does it cost?**
**A:** "Since we use local LLMs, there are no per-query API costs. Main costs are infrastructure (servers) and one-time setup. Much cheaper than enterprise solutions like Glean ($15-30/user/month)."

### **Q: How long to deploy?**
**A:** "POC is ready now. Production deployment takes 2-4 weeks including:
- Data ingestion from your Confluence
- Fine-tuning for your domain
- Security review
- User training"

### **Q: Can it handle other data sources?**
**A:** "Yes! The architecture supports multiple sources. We can add Jira, Slack, Google Drive, GitHub, etc. Each source takes 1-2 weeks to integrate."

### **Q: What about permissions?**
**A:** "Good question. Current POC doesn't enforce Confluence permissions. For production, we'll add permission-aware search so users only see docs they have access to."

---

## **Closing (1 minute)**

**Summary:**
> "In summary, our AI Assistant:
> - Saves employees 5-10 minutes per search
> - Provides accurate, cited answers
> - Works with your existing Confluence data
> - Runs entirely on-premises for privacy
> - Costs a fraction of enterprise solutions"

**Call to Action:**
> "Next steps:
> 1. Try it yourself with your questions
> 2. Share feedback on accuracy and usefulness
> 3. If satisfied, we can move to production deployment
> 
> Questions?"

---

## **Backup Demos (If Time Permits)**

### **Demo: Failed Query Handling**
```
Question: "What is the meaning of life?"

Expected Result:
"I don't have information about that in the Confluence documentation. 
I can only answer questions about [your company's] processes, policies, and technical documentation."
```

**Highlight:** System knows its limits

---

### **Demo: Ambiguous Query**
```
Question: "How do I deploy?"

Expected Result:
"I found deployment guides for multiple environments:
- AWS Production
- Azure Staging  
- On-Prem Legacy

Which environment are you deploying to?"
```

**Highlight:** System asks clarifying questions

---

## **Success Metrics to Track**

After demo, measure:
1. **Time Saved**: Compare search time (before/after)
2. **User Satisfaction**: Survey participants (1-5 scale)
3. **Accuracy**: % of questions answered correctly
4. **Adoption**: % of employees who would use it daily

**Target Metrics:**
- 80%+ accuracy
- 4+ satisfaction score
- 70%+ would use daily
- 5x faster than manual search

---

## **Troubleshooting**

### **Issue: Slow responses**
- Check LM Studio is using GPU
- Reduce `top_k` from 5 to 3
- Use smaller model (7B instead of 13B)

### **Issue: Poor answers**
- Check if relevant docs are in Confluence
- Verify embeddings were generated correctly
- Try different query phrasing

### **Issue: API not connecting**
- Verify all services are running: `docker-compose ps`
- Check LM Studio is on port 1234
- Restart API: `uvicorn chat.chat_api:app --reload`

---

## **Post-Demo Follow-Up**

Send participants:
1. Link to try the system themselves
2. Feedback form (Google Form)
3. Test questions to try
4. Timeline for production deployment

**Feedback Form Questions:**
1. How accurate were the answers? (1-5)
2. How useful is this compared to Confluence search? (1-5)
3. Would you use this daily? (Yes/No)
4. What improvements would you suggest?
5. What other data sources should we add?
