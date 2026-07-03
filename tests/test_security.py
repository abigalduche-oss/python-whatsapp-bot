import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from app import create_app


class SecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["APP_SECRET"] = "test-secret"
        self.status_payload = json.dumps(
            {
                "object": "whatsapp",
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "statuses": [
                                        {
                                            "id": "status-id",
                                            "status": "delivered",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ],
            }
        ).encode("utf-8")
        self.chat_payload = json.dumps(
            {
                "object": "whatsapp",
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "contacts": [
                                        {
                                            "profile": {"name": "Test User"},
                                            "wa_id": "263777558099",
                                        }
                                    ],
                                    "messages": [
                                        {
                                            "from": "263777558099",
                                            "id": "wamid.HBgMMjYzNzc3NTU4MDk5FQIAERgSNjQxMkU0NTg1RUNFQkFERjkzAA==",
                                            "timestamp": "1688220000",
                                            "text": {"body": "hello"},
                                            "type": "text",
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ],
            }
        ).encode("utf-8")
        self.signature = hmac.new(
            b"test-secret",
            msg=self.status_payload,
            digestmod=hashlib.sha256,
        ).hexdigest()

    def test_signature_validator_accepts_valid_status_update(self):
        with self.app.test_client() as client:
            response = client.post(
                "/webhook",
                data=self.status_payload,
                content_type="application/json",
                headers={"X-Hub-Signature-256": f"sha256={self.signature}"},
            )
            self.assertEqual(response.status_code, 200)

    @patch("app.utils.whatsapp_utils.send_message")
    def test_signature_validator_accepts_valid_message_event(self, send_message_mock):
        signature = hmac.new(
            b"test-secret",
            msg=self.chat_payload,
            digestmod=hashlib.sha256,
        ).hexdigest()

        with self.app.test_client() as client:
            response = client.post(
                "/webhook",
                data=self.chat_payload,
                content_type="application/json",
                headers={"X-Hub-Signature-256": f"sha256={signature}"},
            )
            self.assertEqual(response.status_code, 200)
            send_message_mock.assert_called_once()

    def test_signature_validator_rejects_invalid_signature(self):
        with self.app.test_client() as client:
            response = client.post(
                "/webhook",
                data=self.status_payload,
                content_type="application/json",
                headers={"X-Hub-Signature-256": "sha256=bad-signature"},
            )
            self.assertEqual(response.status_code, 403)

    def test_signature_validator_rejects_missing_signature_header(self):
        with self.app.test_client() as client:
            response = client.post(
                "/webhook",
                data=self.status_payload,
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
