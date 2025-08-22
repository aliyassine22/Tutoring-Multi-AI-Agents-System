import json, time, uuid
import streamlit as st
import httpx

API = "http://localhost:8000"
session_id = st.session_state.get("session_id") or str(uuid.uuid4())
user_id = st.session_state.get("user_id") or "user_12345"
st.session_state["session_id"] = session_id
st.session_state["user_id"] = user_id

st.set_page_config(page_title="Signals & Systems Tutoring")
st.title("Signals & Systems Tutoring Assistant")

if "messages" not in st.session_state:
    st.session_state["messages"] = []

for role, text in st.session_state["messages"]:
    with st.chat_message(role):
        st.markdown(text)

def poll_for_response():
    """Poll the /answer endpoint until we get a response."""
    with httpx.Client(timeout=None) as client:
        # Poll until we get a response
        max_attempts = 100
        for attempt in range(max_attempts):
            response = client.get(f"{API}/answer?user_id={user_id}&session_id={session_id}")
            data = response.json()
            
            if data.get("status") == "done":
                return data.get("answer", "")
            elif data.get("status") == "error":
                return f"Error: {data.get('error_msg', 'Unknown error')}"
            elif data.get("status") == "pending":
                time.sleep(0.5)  # Wait before polling again
            else:
                time.sleep(0.5)  # Unknown status, wait before retrying
                
        return "Response timed out. Please try again."

prompt = st.chat_input("Ask me anything about Signals & Systems...")
if prompt:
    # Immediately render the user's message
    st.session_state["messages"].append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    # Kick off response generation for assistant
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            # Send the user message to the backend
            response = httpx.post(
                f"{API}/send", 
                json={
                    "query": prompt,
                    "user_id": user_id,
                    "session_id": session_id
                }
            )
            if response.status_code != 200:
                st.error(f"Error sending message: {response.text}")
                st.session_state["messages"].append(
                    ("assistant", f"Error: Unable to process your request (HTTP {response.status_code})")
                )
            else:
                # Poll for the response
                assistant_response = poll_for_response()
                st.markdown(assistant_response)
                st.session_state["messages"].append(("assistant", assistant_response))

# Optional: Add a sidebar with session information
with st.sidebar:
    st.subheader("Session Information")
    st.write(f"Session ID: {session_id}")
    
    if st.button("Start New Session"):
        new_session_id = str(uuid.uuid4())
        st.session_state["session_id"] = new_session_id
        st.session_state["messages"] = []
        st.rerun()





# this is compatible with the second code 

# import json, time, uuid
# import streamlit as st
# import httpx
# import asyncio
# from sseclient import SSEClient

# API = "http://localhost:8000"
# # Generate a numeric user_id (the backend expects an int)
# if "user_id" not in st.session_state:
#     st.session_state["user_id"] = int(uuid.uuid4().int % 10000)
# user_id = st.session_state["user_id"]

# st.set_page_config(page_title="Signals & Systems Tutoring")
# st.title("Signals & Systems Tutoring Assistant")

# # Initialize chat history
# if "messages" not in st.session_state:
#     st.session_state["messages"] = []

# # Display chat messages
# for role, text in st.session_state["messages"]:
#     with st.chat_message(role):
#         st.markdown(text)

# def stream_response():
#     """Stream the response from the SSE endpoint"""
#     message_placeholder = st.empty()
#     full_response = ""
    
#     try:
#         # Connect to the SSE endpoint
#         client = SSEClient(f"{API}/events/{user_id}")
        
#         for event in client:
#             if not event.data:
#                 continue
                
#             data = json.loads(event.data)
            
#             # Check if turn is complete
#             if data.get("turn_complete") or data.get("interrupted"):
#                 break
                
#             # Process text message
#             if data.get("mime_type") == "text/plain":
#                 text = data.get("data", "")
#                 full_response += text
#                 message_placeholder.markdown(full_response)
        
#         return full_response
#     except Exception as e:
#         return f"Error: {str(e)}"

# # Handle user input
# prompt = st.chat_input("Ask me anything about Signals & Systems...")
# if prompt:
#     # Immediately render the user's message
#     st.session_state["messages"].append(("user", prompt))
#     with st.chat_message("user"):
#         st.markdown(prompt)

#     # Send the message to the backend and display the response
#     with st.chat_message("assistant"):
#         try:
#             # Format the message for the new endpoint
#             message = {
#                 "mime_type": "text/plain",
#                 "data": prompt
#             }
            
#             # Send message to backend
#             response = httpx.post(
#                 f"{API}/send/{user_id}", 
#                 json=message
#             )
            
#             if response.status_code != 200:
#                 st.error(f"Error sending message: {response.text}")
#                 st.session_state["messages"].append(
#                     ("assistant", f"Error: Unable to process your request (HTTP {response.status_code})")
#                 )
#             else:
#                 # Stream and display the response
#                 assistant_response = stream_response()
#                 if not assistant_response.startswith("Error:"):
#                     st.session_state["messages"].append(("assistant", assistant_response))
                    
#         except Exception as e:
#             st.error(f"Error: {str(e)}")
#             st.session_state["messages"].append(("assistant", f"Error: {str(e)}"))

# # Add a sidebar with session information
# with st.sidebar:
#     st.subheader("Session Information")
#     st.write(f"User ID: {user_id}")
    
#     if st.button("Start New Session"):
#         # Generate a new user ID
#         st.session_state["user_id"] = int(uuid.uuid4().int % 10000)
#         st.session_state["messages"] = []
#         st.rerun()