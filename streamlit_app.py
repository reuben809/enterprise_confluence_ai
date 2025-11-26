import streamlit as st
import requests
import json
import os

# API_URL uses the service name from docker-compose, or localhost for local dev
API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Confluence AI", layout="wide")
st.title("Enterprise Confluence Assistant")


def send_feedback(feedback_data, feedback_type):
    """Send feedback to the backend."""
    feedback_data["feedback"] = feedback_type
    try:
        requests.post(f"{API_URL}/feedback", json=feedback_data)
    except Exception as e:
        st.error(f"Failed to send feedback: {e}")


# --- Initialize Session State ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_response" not in st.session_state:
    st.session_state.last_response = None

# --- Clear Chat Button in Sidebar ---
if st.sidebar.button("Clear Chat History", use_container_width=True):
    st.session_state.messages = []
    st.session_state.last_response = None
    st.success("Chat history cleared!")
    st.rerun()


# --- Display Chat History ---
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# --- Chat Input ---
if prompt := st.chat_input("Ask a question about your Confluence space..."):
    # Add user message to state and display
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    # Prepare payload for API
    payload = {
        "question": prompt,
        "history": st.session_state.messages[:-1]  # Send history *before* this message
    }

    # Reset last response and sources
    st.session_state.last_response = None
    sources = []

    # Call API and stream response with loading indicator
    with st.spinner("Thinking..."):
        with st.chat_message("assistant").empty() as placeholder:
            full_response = ""
            try:
                # Call post, assign response, THEN check for errors
                resp = requests.post(f"{API_URL}/chat", json=payload, stream=True, timeout=120)
                resp.raise_for_status()

                for line in resp.iter_lines():
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith("data: "):
                            try:
                                data_str = line_str[6:]
                                data = json.loads(data_str)

                                if data["type"] == "token":
                                    full_response += data["data"]
                                    if placeholder:
                                        placeholder.markdown(full_response + "|")
                                    else:
                                        st.markdown(full_response + "|")  # Fallback
                                elif data["type"] == "sources":
                                    sources = data["data"]
                                elif data["type"] == "end":
                                    break
                            except json.JSONDecodeError:
                                continue

                # Final response without cursor
                if placeholder:
                    placeholder.markdown(full_response)
                else:
                    st.markdown(full_response)

                # Save the full response
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                st.session_state.last_response = {
                    "question": prompt,
                    "answer": full_response,
                    "sources": sources
                }

            except requests.exceptions.HTTPError as http_err:
                # This error means `resp` exists, so we can access `resp.text`
                error_msg = f"HTTP Error: {http_err} - {resp.text}"
                if placeholder:
                    placeholder.error(error_msg)
                else:
                    st.error(error_msg)  # Fallback
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

            except requests.exceptions.RequestException as req_err:
                # This catches ConnectionError, Timeout, etc. `resp` may not exist.
                error_msg = f"Connection Error: Make sure the API service is running and accessible. ({req_err})"
                if placeholder:
                    placeholder.error(error_msg)
                else:
                    st.error(error_msg)  # Fallback
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

            except Exception as e:
                # Catchall for other unexpected errors
                error_msg = f"An unexpected error occurred: {e}"
                if placeholder:
                    placeholder.error(error_msg)
                else:
                    st.error(error_msg)  # Fallback
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

# --- Sidebar for Sources and Feedback ---
if st.session_state.last_response:
    st.sidebar.divider()

    # Display Sources as clean hyperlinks
    st.sidebar.subheader("Sources")
    if st.session_state.last_response["sources"]:
        for idx, src in enumerate(st.session_state.last_response["sources"], 1):
            # Show title as a clean numbered clickable link
            st.sidebar.markdown(f"{idx}. [{src['title']}]({src['url']})")
    else:
        st.sidebar.markdown("*No sources found for this response.*")

    # Display Feedback buttons
    st.sidebar.subheader("Was this helpful?")
    cols = st.sidebar.columns(2)
    if cols[0].button("Yes", use_container_width=True):
        send_feedback(st.session_state.last_response, "positive")
        st.sidebar.success("Thank you for your feedback!")

    if cols[1].button("No", use_container_width=True):
        send_feedback(st.session_state.last_response, "negative")
        st.sidebar.error("Thank you for your feedback!")