from openai import OpenAI
import openai
import shelve
from dotenv import load_dotenv
import os
import time
import logging
import glob

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI(api_key=OPENAI_API_KEY)

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
DATA_FILE_PATH = os.path.join(DATA_DIR, "airbnb-faq.pdf")
SUPPORTED_FAQ_GLOBS = ["*.pdf", "*.docx", "*.doc"]


def find_faq_file():
    # Search DATA_DIR for supported FAQ files and return the first match
    for pattern in SUPPORTED_FAQ_GLOBS:
        matches = glob.glob(os.path.join(DATA_DIR, pattern))
        if matches:
            # prefer the first match
            return os.path.abspath(matches[0])
    return None
VECTOR_STORE_DB = "vector_store_db"
VECTOR_STORE_NAME = "CUZ Query Assistant FAQ Vector Store"
VECTOR_STORE_DESCRIPTION = (
    "Vector store for Catholic University of Zimbabwe Harare Campus FAQ content used by the WhatsApp assistant."
)

ASSISTANT_INSTRUCTIONS = (
    "You are a WhatsApp help assistant for Catholic University of Zimbabwe, Harare Campus. "
    "Use the campus FAQ knowledge base to answer student questions as accurately as possible. Otherwise use the information found on the official Catholic Universiity of Zimbabwe website website https://cuz.ac.zw/ to answer questions. "
    "If the answer is not present in the knowledge base, say you don't know and direct the student to the university help desk. "
    "Be professional, funny, concise, and friendly."
)


def upload_file(path):
    # Upload a file with an "assistants" purpose
    if not os.path.isfile(path):
        raise FileNotFoundError(f"FAQ file not found at {path}")

    file = client.files.create(
        file=open(path, "rb"), purpose="assistants"
    )

    return file


def create_assistant(file):
    """
    You currently cannot set the temperature for Assistant via the API.
    """
    assistant = client.beta.assistants.create(
        name="CUZ Query Assistant",
        instructions="You're a helpful WhatsApp assistant that can assist students learning at Catholic University in Zimbabwe Harare Campus. Use your knowledge base to best respond to customer queries. If you don't know the answer, say simply that you cannot help with question and advice to contact the host directly. Be friendly, funny and professional.",
        tools=[{"type": "retrieval"}],
        model="gpt-5.4",
        file_ids=[file.id],
    )
    return assistant


# Use context manager to ensure the shelf file is closed properly
def check_if_thread_exists(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id, None)


def store_thread(wa_id, thread_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[wa_id] = thread_id


def get_response_conversation_id(wa_id):
    with shelve.open("responses_db") as responses_shelf:
        return responses_shelf.get(wa_id, None)


def store_response_conversation_id(wa_id, conversation_id):
    with shelve.open("responses_db", writeback=True) as responses_shelf:
        responses_shelf[wa_id] = conversation_id


def get_cached_vector_store():
    with shelve.open(VECTOR_STORE_DB, writeback=True) as db:
        return db.get("vector_store_id"), db.get("file_id")


def store_cached_vector_store(vector_store_id, file_id):
    with shelve.open(VECTOR_STORE_DB, writeback=True) as db:
        db["vector_store_id"] = vector_store_id
        db["file_id"] = file_id


def ensure_vector_store():
    vector_store_id, file_id = get_cached_vector_store()
    if vector_store_id:
        return vector_store_id
    try:
        if not file_id:
            faq_path = find_faq_file()
            if not faq_path:
                raise FileNotFoundError(f"No supported FAQ file found in {DATA_DIR}")
            file = upload_file(faq_path)
            file_id = file.id

        vector_store = client.vector_stores.create(
            file_ids=[file_id],
            name=VECTOR_STORE_NAME,
            description=VECTOR_STORE_DESCRIPTION,
        )
        store_cached_vector_store(vector_store.id, file_id)
        return vector_store.id
    except FileNotFoundError as e:
        logging.warning(str(e) + "; skipping vector store setup.")
        return None
    except Exception as e:
        logging.exception("Failed to create or retrieve vector store; proceeding without retrieval tools: %s", e)
        return None


def get_retrieval_tools():
    vector_store_id = ensure_vector_store()
    if not vector_store_id:
        return []
    return [{"type": "file_search", "vector_store_ids": [vector_store_id]}]


def is_valid_assistant_id(assistant_id):
    return isinstance(assistant_id, str) and assistant_id.startswith("asst")


def run_assistant(thread, name, message_body):
    # Retrieve the Assistant if the ID is valid, otherwise fall back to Responses API.
    if is_valid_assistant_id(OPENAI_ASSISTANT_ID):
        assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id,
            # instructions=f"You are having a conversation with {name}",
        )

        # Wait for completion
        while run.status != "completed":
            time.sleep(0.5)
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        new_message = messages.data[0].content[0].text.value
        logging.info(f"Generated message from Assistant API: {new_message}")
        return new_message

    logging.info("Invalid or missing assistant ID; falling back to Responses API.")
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=message_body,
        instructions=ASSISTANT_INSTRUCTIONS,
        tools=get_retrieval_tools(),
        max_output_tokens=512,
        temperature=0,
    )

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

    logging.info(f"Generated message from Responses API: {new_message}")
    return new_message


def generate_response(message_body, wa_id, name):
    # Check if there is already a thread_id for the wa_id
    thread_id = check_if_thread_exists(wa_id)

    # If a thread doesn't exist, create one and store it
    if thread_id is None:
        logging.info(f"Creating new thread for {name} with wa_id {wa_id}")
        thread = client.beta.threads.create()
        store_thread(wa_id, thread.id)
        thread_id = thread.id

    # Otherwise, retrieve the existing thread
    else:
        logging.info(f"Retrieving existing thread for {name} with wa_id {wa_id}")
        thread = client.beta.threads.retrieve(thread_id)

    # Add message to thread
    message = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message_body,
    )

    # Run the assistant and get the new message
    new_message = run_assistant(thread, name, message_body)

    return new_message
