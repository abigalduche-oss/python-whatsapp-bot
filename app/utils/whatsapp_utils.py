import logging
from flask import current_app, jsonify
import json
import requests

from app.services.openai_service import generate_response
import re


def get_recipient_waids():
    recipients = current_app.config.get("RECIPIENT_WAIDS") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    return [r for r in recipients if r]


def get_default_recipient():
    recipients = get_recipient_waids()
    return recipients[0] if recipients else None


def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )


# def generate_response(response):
#     # Return text in uppercase
#     return response.upper()


def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }

    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"

    try:
        response = requests.post(
            url, data=data, headers=headers, timeout=10
        )  # 10 seconds timeout as an example
        response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
    except requests.Timeout:
        logging.error("Timeout occurred while sending message")
        return jsonify({"status": "error", "message": "Request timed out"}), 408
    except (
        requests.RequestException
    ) as e:  # This will catch any general request exception
        logging.error(f"Request failed due to: {e}")
        # If the exception has a response, log its details for easier debugging
        try:
            resp = e.response
            if resp is not None:
                log_http_response(resp)
                try:
                    return jsonify({"status": "error", "message": resp.text}), resp.status_code
                except Exception:
                    return jsonify({"status": "error", "message": "Failed to send message"}), 500
        except Exception:
            # Fallback when e.response isn't available or logging fails
            pass
        return jsonify({"status": "error", "message": "Failed to send message"}), 500
    else:
        # Process the response as normal
        log_http_response(response)
        return response


def process_text_for_whatsapp(text):
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text


def process_whatsapp_message(body):
    # Log the raw incoming payload for debugging
    try:
        logging.info(f"Incoming webhook payload: {body}")
    except Exception:
        pass

    entry = body.get("entry", [])[0] if body.get("entry") else {}
    change = entry.get("changes", [])[0] if entry.get("changes") else {}
    value = change.get("value", {})

    contacts = value.get("contacts", [])
    messages = value.get("messages", [])

    wa_id = None
    name = None
    if contacts:
        contact = contacts[0]
        wa_id = contact.get("wa_id")
        profile = contact.get("profile", {})
        name = profile.get("name")

    if not messages:
        logging.info("No messages field in webhook payload; nothing to process.")
        return

    message = messages[0]

    # Safely extract text body if present
    text_obj = message.get("text")
    if text_obj and isinstance(text_obj, dict):
        message_body = text_obj.get("body", "")
    else:
        # Unsupported or non-text message types (e.g., interactive, image, button)
        logging.info(f"Received non-text or unsupported message type: {message.get('type')}")
        logging.debug(f"Full message object: {message}")
        return

    # Generate the assistant response for this sender
    if wa_id is None:
        logging.warning("Incoming WhatsApp payload missing wa_id; falling back to default recipient.")
        wa_id = get_default_recipient()
        name = name or "Guest"

    response = generate_response(message_body, wa_id, name)
    response = process_text_for_whatsapp(response)

    recipient = wa_id or get_default_recipient()
    if recipient is None:
        logging.error("No recipient WAID available to send the WhatsApp response.")
        return

    data = get_text_message_input(recipient, response)
    resp = send_message(data)
    try:
        logging.info(f"Sent message response to {recipient}: {resp}")
    except Exception:
        pass


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
