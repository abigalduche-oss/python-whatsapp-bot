import sys
import os
import re
from dotenv import load_dotenv
import logging


def load_recipient_waids():
    recipients = []
    for env_name, env_value in os.environ.items():
        if not env_value:
            continue
        if env_name == "RECIPIENT_WAID":
            recipients.append((0, env_value))
        else:
            match = re.match(r"RECIPIENT_WAID(\d+)$", env_name)
            if match:
                recipients.append((int(match.group(1)), env_value))
    recipients.sort(key=lambda item: item[0])
    return [value for _, value in recipients]


def load_configurations(app):
    load_dotenv()
    app.config["ACCESS_TOKEN"] = os.getenv("ACCESS_TOKEN")
    app.config["YOUR_PHONE_NUMBER"] = os.getenv("YOUR_PHONE_NUMBER")
    app.config["APP_ID"] = os.getenv("APP_ID")
    app.config["APP_SECRET"] = os.getenv("APP_SECRET")
    recipient_waids = load_recipient_waids()
    app.config["RECIPIENT_WAID"] = recipient_waids[0] if recipient_waids else None
    app.config["RECIPIENT_WAIDS"] = recipient_waids
    app.config["VERSION"] = os.getenv("VERSION")
    app.config["PHONE_NUMBER_ID"] = os.getenv("PHONE_NUMBER_ID")
    app.config["VERIFY_TOKEN"] = os.getenv("VERIFY_TOKEN")


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
