# mgw_api/management/commands/manage_crons.py

import os
import signal
import sys
from django.core.management.base import BaseCommand
from aiosmtpd.controller import Controller
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

from mgw.settings import LOGGER
from mgw.settings import LOG_DIR


class Command(BaseCommand):
    help = "Start or stop the mail server"

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'stop'])

    def handle(self, *args, **options):
        action = options['action']
        if action == 'start':
            self.start_mail_server()
        elif action == 'stop':
            self.stop_mail_server()

    def start_mail_server(self):
        ########################################################################
        class CustomHandler:
            def __init__(self, log_file):
                self.log_file = log_file
            async def handle_DATA(self, server, session, envelope):
                with open(self.log_file, 'a') as f:
                    f.write(f"Message from {envelope.mail_from}\n")
                    f.write(f"Message for {', '.join(envelope.rcpt_tos)}\n")
                    f.write('Message data:\n')
                    f.write(envelope.content.decode('utf8', errors='replace'))
                    f.write('\nEnd of message\n\n')
                return '250 Message accepted for delivery'
        log_file_path = LOG_DIR / "mail.log"
        self.handler = CustomHandler(log_file_path)
        self.controller = Controller(self.handler, hostname='localhost', port=1025)
        self.thread = threading.Thread(target=self.controller.start)
        self.thread.start()
        LOGGER.info('Mail server started on port 1025')

    def stop_mail_server(self):
        if hasattr(self, 'controller') and self.controller is not None:
            self.controller.stop()
            self.thread.join()  # Ensure the thread has finished
            LOGGER.info('Mail server stopped')
        else:
            LOGGER.warning('Mail server is not running')
