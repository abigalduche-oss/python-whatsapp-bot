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


# Use context manager to ensure the shelf file is closed properly
# These legacy storage helpers are preserved for compatibility but are not used by the current Responses API flow.


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


def run_responses_api(message_body):
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
    logging.info("Using Responses API only for message generation.")
    return run_responses_api(message_body)
