"""Placeholder API handler: answers 503 until the first pipeline release replaces this code."""

import json


def handler(_event, _context):
    return {
        "statusCode": 503,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(
            {"error": {"code": "not_released", "message": "No release has been deployed yet."}}
        ),
    }
