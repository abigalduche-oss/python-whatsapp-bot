from openai import OpenAI
import openai
import shelve
from dotenv import load_dotenv
import os
import time

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


# --------------------------------------------------------------
# Upload file and create vector store
# --------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_FILE_PATH = os.path.join(SCRIPT_DIR, "..", "data", "airbnb-faq.pdf")


def upload_file(path):
    with open(path, "rb") as file_obj:
        return client.files.create(file=file_obj, purpose="assistants")


def create_vector_store(file_id):
    return client.vector_stores.create(
        file_ids=[file_id],
        name="CUZ Query Assistant FAQ Vector Store",
        description="Vector store for Catholic University of Zimbabwe Harare Campus FAQ content used by the WhatsApp assistant.",
    )


file = upload_file(DATA_FILE_PATH)
vector_store = create_vector_store(file.id)
TOOLS = [
    {
        "type": "file_search",
        "vector_store_ids": [vector_store.id],
    }
]


# --------------------------------------------------------------
# Conversation management
# --------------------------------------------------------------

def get_conversation_id(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id)


def store_conversation_id(wa_id, conversation_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[wa_id] = conversation_id


# --------------------------------------------------------------
# Generate response
# --------------------------------------------------------------

def generate_response(message_body, wa_id, name):
    conversation_id = get_conversation_id(wa_id)
    if conversation_id is None:
        print(f"Starting new conversation for {name} with wa_id {wa_id}")
    else:
        print(f"Continuing conversation for {name} with wa_id {wa_id}")

    # Handle RateLimit / Insufficient quota errors with retries and backoff
    max_retries = 3
    response = None
    for attempt in range(max_retries):
        try:
            response = client.responses.create(
                model="gpt-4.1-mini",
                input=message_body,
                instructions=(
                    "You're a helpful WhatsApp assistant that can assist students learning Catholic University of Zimbabwe Harare Campus. "
                    "Use your knowledge base to answer customer questions. If you don't know the answer, say that you cannot help and advise them to contact the host directly. Be friendly, funny and proffessional."
                ),
                tools=TOOLS,
                conversation=conversation_id,
                max_output_tokens=512,
                temperature=0.7,
            )
            break
        except openai.RateLimitError as e:
            # If it's the last attempt, don't retry
            if attempt == max_retries - 1:
                print("Quota or rate limit exceeded and retries exhausted:", str(e))
            else:
                wait_seconds = 2 ** attempt
                print(f"Rate limit / quota error: {e}. Retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
        except Exception as e:
            # For other errors, show and stop retrying
            print("Unexpected error calling OpenAI responses.create:", str(e))
            break

    if response is None:
        # Provide a clear message to the caller and stop
        print("Assistant unavailable: API quota/rate limit issue. Check your OpenAI billing and quota.")
        return "Sorry, the assistant is temporarily unavailable due to API quota/rate limits. Please check your OpenAI billing and try again later."

    if conversation_id is None and getattr(response, "conversation", None) is not None:
        store_conversation_id(wa_id, response.conversation.id)

    if getattr(response, "output_text", None) is not None:
        new_message = response.output_text
    else:
        output_items = getattr(response, "output", []) or []
        new_message = "\n".join(
            item.text
            for item in output_items
            if getattr(item, "type", None) == "message"
            for content in getattr(item, "content", [])
            if getattr(content, "type", None) == "output_text"
        )

    print(f"To {name}: {new_message}")
    return new_message


# --------------------------------------------------------------
# Test response flow
# --------------------------------------------------------------

new_message = generate_response("When is the fees due date for the current semester", "123", "John")
new_message = generate_response("How do l get a fees statement ?", "456", "Sarah")
new_message = generate_response("What was my previous question?", "123", "John")
new_message = generate_response("What was my previous question?", "456", "Sarah")
