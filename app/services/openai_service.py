from openai import OpenAI
import openai
import shelve
from dotenv import load_dotenv
import os
import time
import logging

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI(api_key=OPENAI_API_KEY)

ASSISTANT_INSTRUCTIONS = (
    "You're a helpful WhatsApp assistant that can assist students learning Catholic University in Zimbabwe Harare Campus. "
    "Use your knowledge base to answer customer questions. If you don't know the answer, say that you cannot help and advise them to contact the host directly. Be friendly and proffessional."
)


def upload_file(path):
    # Upload a file with an "assistants" purpose
    file = client.files.create(
        file=open("../../data/airbnb-faq.pdf", "rb"), purpose="assistants"
    )


def create_assistant(file):
    """
    You currently cannot set the temperature for Assistant via the API.
    """
    assistant = client.beta.assistants.create(
        name="CUZ Query Assistant",
        instructions="You're a helpful WhatsApp assistant that can assist students learning Catholic University in Zimbabwe Harare Campus. Use your knowledge base to best respond to customer queries. If you don't know the answer, say simply that you cannot help with question and advice to contact the host directly. Be friendly and professional.",
        tools=[{"type": "retrieval"}],
        model="gpt-4-1106-preview",
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
        max_output_tokens=512,
        temperature=0.7,
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
