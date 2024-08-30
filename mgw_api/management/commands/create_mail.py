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
        mail_path = os.path.dirname(os.path.abspath(__file__))
        log_file_path = os.path.join(mail_path, "log_mail.log")
        self.handler = CustomHandler(log_file_path)
        self.controller = Controller(self.handler, hostname='localhost', port=1025)
        self.thread = threading.Thread(target=self.controller.start)
        self.thread.start()
        self.stdout.write(self.style.SUCCESS('Mail server started on port 1025'))

    def stop_mail_server(self):
        if hasattr(self, 'controller') and self.controller is not None:
            self.controller.stop()
            self.thread.join()  # Ensure the thread has finished
            self.stdout.write(self.style.SUCCESS('Mail server stopped'))
        else:
            self.stdout.write(self.style.WARNING('Mail server is not running'))
