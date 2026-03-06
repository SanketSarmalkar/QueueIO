import requests
import json
import traceback
from datetime import datetime
from tasks.config import SLACK_WEBHOOK_URL


def send_slack_alert(
    message: str,
    status: str = "INFO",
    job_name: str = "Unknown Job",
    extra_data: dict = None
):
    """
    Send Slack alert using webhook.
    
    :param message: Main alert message
    :param status: INFO / SUCCESS / WARNING / ERROR
    :param job_name: Name of the job/service
    :param extra_data: Optional dictionary for extra details
    """

    color_map = {
        "INFO": "#439FE0",
        "SUCCESS": "#2EB67D",
        "WARNING": "#ECB22E",
        "ERROR": "#E01E5A",
    }

    payload = {
        "attachments": [
            {
                "color": color_map.get(status, "#439FE0"),
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{status} Alert - {job_name}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Message:*\n{message}"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Time:*\n{datetime.utcnow()} UTC"
                            }
                        ]
                    }
                ]
            }
        ]
    }

    if extra_data:
        payload["attachments"][0]["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Extra Data:*\n```{json.dumps(extra_data, indent=2)}```"
            }
        })

    response = requests.post(
        SLACK_WEBHOOK_URL,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"}
    )

    if response.status_code != 200:
        raise Exception(
            f"Slack notification failed: {response.status_code} - {response.text}"
        )