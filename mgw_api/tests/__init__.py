import logging

# Keep routine 404s and debug sync logs out of successful test output.
logging.getLogger("django.request").setLevel(logging.ERROR)
logging.getLogger("mgw.settings").setLevel(logging.INFO)
