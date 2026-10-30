"""ASGI entrypoint (T00A03).

This is the composition root: it loads the typed settings once, configures
logging, and builds the app with the sandbox host guard active. Importing the
app factory itself stays environment-free for tests.
"""

from fairpool.api.app import create_app
from fairpool.config import get_settings
from fairpool.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
app = create_app(settings)
