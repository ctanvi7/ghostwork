"""Vercel entrypoint: exposes the Flask app as a serverless WSGI function.

vercel.json rewrites every path to this function; Flask does the routing.
Configuration comes from Vercel environment variables (never from .env).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

app = create_app()
