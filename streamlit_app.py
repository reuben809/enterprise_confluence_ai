import streamlit as st
import requests
import json
import os
from datetime import datetime

# API_URL uses the service name from docker-compose, or localhost for local dev
API_URL = os.getenv("API_URL", "http://localhost:8000")

# --- Page Config ---
st.set_page_config(
    page_title="Confluence AI Assistant", 
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for dark/light theme compatibility ---
st.markdown("""
<style>
    /* Main header styling - gradient works in both themes */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        margin-bottom: 1.5rem;
        color: white;
        text-align: center;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
    }
    
    .main-header h1 {
        margin: 0;
        font-size: 2.2rem;
    }
    
    /* Source card styling - dark theme compatible */
    .source-card {
        background: rgba(102, 126, 234, 0.1);
        border-left: 3px solid #667eea;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
        transition: all 0.2s ease;
    }
    
    .source-card:hover {
        background: rgba(102, 126, 234, 0.2);
        transform: translateX(5px);
    }
    
    .source-card a {
        color: #667eea !important;
        text-decoration: none;
    }
    
    .source-card a:hover {
        color: #764ba2 !important;
        text-decoration: underline;
    }
    
    /* Stat cards */
    .stat-card {
        background: rgba(102, 126, 234, 0.1);
        padding: 1rem;
        border-radius: 10px;
        text-align: center;
    }
    
    /* Welcome section */
    .welcome-section {
        text-align: center;
        padding: 3rem;
        background: rgba(102, 126, 234, 0.05);
        border-radius: 15px;
        margin: 2rem 0;
    }
    
    .welcome-section h3 {
        color: #667eea;
    }
    
    /* Chat styling improvements */
    .stChatMessage {
        border-radius: 15px !important;
        padding: 1rem !important;
    }
    
    /* Button styling */
    .stButton > button {
        border-radius: 20px;
        transition: all 0.2s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    /* Divider styling */
    hr {
        border-color: rgba(102, 126, 234, 0.2) !important;
    }
    
    /* Input styling */
    .stChatInput > div {
        border-radius: 25px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown("""
<div class="main-header">
    <h1>🔍 Confluence AI Assistant</h1>
    <p style="margin:0; opacity:0.9;">Ask questions about your enterprise documentation</p>
</div>
""", unsafe_allow_html=True)


def send_feedback(feedback_data, feedback_type):
    """Send feedback to the backend."""
    feedback_data["feedback"] = feedback_type
    feedback_data["timestamp"] = datetime.utcnow().isoformat()
    try:
        requests.post(f"{API_URL}/feedback", json=feedback_data, timeout=5)
    except Exception as e:
        st.error(f"Failed to send feedback: {e}")


def check_api_health():
    """Check if API is running."""
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        return resp.status_code == 200
    except:
        return False


# --- Initialize Session State ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_response" not in st.session_state:
    st.session_state.last_response = None
if "query_count" not in st.session_state:
    st.session_state.query_count = 0
if "feedback_given" not in st.session_state:
    st.session_state.feedback_given = False

# --- Sidebar ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/8/82/Confluence_Logo.svg", width=150)
    
    # API Status
    api_status = check_api_health()
    if api_status:
        st.success("🟢 API Connected")
    else:
        st.error("🔴 API Disconnected")
    
    st.divider()
    
    # Quick Stats
    st.subheader("📊 Session Stats")
    col1, col2 = st.columns(2)
    col1.metric("Queries", st.session_state.query_count)
    col2.metric("Messages", len(st.session_state.messages))
    
    st.divider()
    
    # Clear Chat
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_response = None
        st.session_state.query_count = 0
        st.session_state.feedback_given = False
        st.success("Chat cleared!")
        st.rerun()
    
    # Sources Section
    if st.session_state.last_response and st.session_state.last_response.get("sources"):
        st.divider()
        st.subheader("📄 Sources")
        for idx, src in enumerate(st.session_state.last_response["sources"], 1):
            with st.container():
                st.markdown(f"""
                <div class="source-card">
                    <strong>{idx}.</strong> <a href="{src['url']}" target="_blank">{src['title']}</a>
                </div>
                """, unsafe_allow_html=True)
    
    # Feedback Section
    if st.session_state.last_response and not st.session_state.feedback_given:
        st.divider()
        st.subheader("💬 Rate This Response")
        
        col1, col2 = st.columns(2)
        
        if col1.button("👍 Helpful", use_container_width=True):
            send_feedback(st.session_state.last_response, "positive")
            st.session_state.feedback_given = True
            st.success("Thanks for your feedback! 🎉")
            st.rerun()
        
        if col2.button("👎 Not Helpful", use_container_width=True):
            send_feedback(st.session_state.last_response, "negative")
            st.session_state.feedback_given = True
            st.warning("Thanks! We'll try to improve. 💪")
            st.rerun()
    
    elif st.session_state.feedback_given:
        st.divider()
        st.info("✅ Feedback recorded for this response")

# --- Main Chat Area ---

# Display Chat History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
        st.markdown(msg["content"])

# Chat Input
if prompt := st.chat_input("💬 Ask about your Confluence docs...", key="chat_input"):
    # Reset feedback state for new query
    st.session_state.feedback_given = False
    st.session_state.query_count += 1
    
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(prompt)
    
    # Prepare payload
    payload = {
        "question": prompt,
        "history": st.session_state.messages[:-1]
    }
    
    # Reset last response
    st.session_state.last_response = None
    sources = []
    
    # Stream response
    with st.chat_message("assistant", avatar="🤖"):
        message_placeholder = st.empty()
        full_response = ""
        
        # Show typing indicator
        with st.spinner("🔍 Searching Confluence & generating answer..."):
            try:
                resp = requests.post(
                    f"{API_URL}/chat", 
                    json=payload, 
                    stream=True, 
                    timeout=180
                )
                resp.raise_for_status()
                
                for line in resp.iter_lines():
                    if line:
                        line_str = line.decode('utf-8').strip()
                        if line_str:
                            try:
                                data = json.loads(line_str)
                                
                                if data["type"] == "token":
                                    full_response += data["data"]
                                    message_placeholder.markdown(full_response + "▌")
                                elif data["type"] == "sources":
                                    sources = data["data"]
                                elif data["type"] == "end":
                                    break
                            except json.JSONDecodeError:
                                continue
                
                # Final response
                message_placeholder.markdown(full_response)
                
                # Save response
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": full_response
                })
                st.session_state.last_response = {
                    "question": prompt,
                    "answer": full_response,
                    "sources": sources
                }
                
                # Show sources inline
                if sources:
                    st.divider()
                    st.caption("📚 **Sources used:**")
                    source_text = " • ".join([f"[{s['title']}]({s['url']})" for s in sources[:3]])
                    st.markdown(source_text)
                
            except requests.exceptions.HTTPError as http_err:
                error_msg = f"❌ HTTP Error: {http_err}"
                message_placeholder.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
                
            except requests.exceptions.ConnectionError:
                error_msg = "❌ Cannot connect to API. Make sure the backend is running on port 8000."
                message_placeholder.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
                
            except requests.exceptions.Timeout:
                error_msg = "⏱️ Request timed out. The query may be too complex or the LLM is slow."
                message_placeholder.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
                
            except Exception as e:
                error_msg = f"❌ Unexpected error: {e}"
                message_placeholder.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
    
    # Rerun to update sidebar
    st.rerun()

# --- Empty State ---
if not st.session_state.messages:
    st.markdown("""
    <div style="text-align: center; padding: 3rem; color: #666;">
        <h3>👋 Welcome!</h3>
        <p>Ask any question about your Confluence documentation.</p>
        <p style="opacity: 0.7;">Examples:</p>
        <ul style="list-style: none; padding: 0;">
            <li>📋 "What is our vacation policy?"</li>
            <li>🔧 "How do I set up the VPN?"</li>
            <li>📊 "Show me the Q4 roadmap"</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)