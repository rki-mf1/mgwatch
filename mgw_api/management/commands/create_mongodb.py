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
        log_file_path = os.path.join(mail_path, "mail.log")
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



def start_mongodb_server():
    pass
    # mkdir -p mongodb/data/db
    # chmod -R 700 mongodb/data/db
    # mamba run --live-stream -n ${arg_one} \
    # mongod --dbpath mongodb/data/db --port 27017 --fork --logpath mongodb/mongod.log

def stop_mongodb_server():
    pass
    #mamba run --live-stream -n ${arg_one} \
    #mongod --shutdown --dbpath mongodb/data/db



# conda install conda-forge::awscli=2.17.28
# 


# https://aws.amazon.com/marketplace/pp/prodview-53agqvt7fxmzg#usage
# Description
# Metadata files for the Sequence Read Archive, ready to load into AWS Glue and query with Amazon Athena.
# 
# Resource type
# S3 Bucket
# Amazon Resource Name (ARN)
# 
# arn:aws:s3:::sra-pub-metadata-us-east-1/sra/metadata
# AWS Region
# us-east-1
# AWS CLI Access (No AWS account required)
# 
# aws s3 ls --no-sign-request s3://sra-pub-metadata-us-east-1/sra/metadata/




#import pandas as pd
#df = pd.read_parquet('your_file.parquet')
#print(df.head())




#conda install conda-forge::boto3=1.34.159
#

import boto3
import os

s3_client = boto3.client('s3')

# Define the S3 bucket and prefix
bucket_name = 'sra-pub-metadata-us-east-1'
prefix = 'sra/metadata/'

# Create a directory for inputs
os.makedirs('inputs', exist_ok=True)

# Download files
def download_parquet_files():
    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    for obj in response.get('Contents', []):
        file_name = obj['Key'].split('/')[-1]
        if file_name.endswith('.parquet'):
            s3_client.download_file(bucket_name, obj['Key'], os.path.join('inputs', file_name))

download_parquet_files()



import pandas as pd
import pyarrow.parquet as pq

# Load all Parquet files from the inputs directory
def load_and_process_parquet_files():
    dfs = []
    for file in os.listdir('inputs'):
        if file.endswith('.parquet'):
            df = pd.read_parquet(os.path.join('inputs', file))
            
            # Extract the lat_lon value
            df['lat_lon'] = df['attributes'].apply(
                lambda attrs: next((attr['v'] for attr in attrs if attr['k'] == 'lat_lon_sam_s_dpl34'), None)
            )
            
            dfs.append(df)

    # Combine all dataframes into one
    combined_df = pd.concat(dfs, ignore_index=True)

    return combined_df

df = load_and_process_parquet_files()

# Save the subset as a Parquet file if needed
df.to_parquet('subset.parquet', compression='zstd')



from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['your_database_name']  # Replace with your database name
collection = db['sra_metadata']  # Replace with your collection name

# Insert the DataFrame into MongoDB
def save_to_mongodb(df):
    # Convert DataFrame to a list of dictionaries
    data_dict = df.to_dict('records')

    # Insert data into MongoDB
    collection.insert_many(data_dict)

save_to_mongodb(df)



