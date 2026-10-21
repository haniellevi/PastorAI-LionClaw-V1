"""Closed self-only command; no target, free-form reason or model routing."""
from app.services.private_erasure_requests import COMMAND


def route(text):
    return isinstance(text, str) and " ".join(text.split()).upper() == COMMAND
