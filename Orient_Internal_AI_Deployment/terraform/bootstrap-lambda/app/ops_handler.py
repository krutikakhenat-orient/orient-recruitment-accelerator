"""Placeholder ops handler: refuses to run until the first pipeline release replaces this code."""


def handler(_event, _context):
    return {"status": "error", "result": "No release has been deployed yet."}
