import os
import re
import time
from google.cloud import storage


def read_key(key):
  os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = key
  storage_client = storage.Client()

  return storage_client

# Download file
def download_file_from_bucket(key, blob_name, file_path, bucket_name):
  try:
    storage_client = read_key(key)
    bucket = storage_client.get_bucket(bucket_name)
    blob = bucket.blob(blob_name)
    with open (file_path, 'wb') as f:
      storage_client.download_blob_to_file(blob, f)
    return True
  except Exception as e:
    print(e)
    return False

def download_with_bucket_path(key, input_path):
  if input_path.startswith('gs://'):
    bucket_path = input_path[5:]
    split_bucket_path = re.split('/', bucket_path)
    bucket_name = split_bucket_path[0]
    file_name = split_bucket_path[-1]
    file_path = ""
    for idx in range(1, len(split_bucket_path)):
      file_path = os.path.join(file_path, split_bucket_path[idx])

    if not os.path.exists("./bucket"):
      os.mkdir("bucket")
    
    while not os.path.exists("./bucket"):
      time.sleep(1)

    stored_directory = os.path.join("./bucket", file_name)

    download_file_from_bucket(key, file_path, stored_directory, bucket_name)

    return stored_directory
  
def upload_to_bucket(key, blob_name, file_path, bucket_name):
  try:
    storage_client = read_key(key)
    bucket = storage_client.get_bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(file_path)
  except Exception as e:
    print(e)
    return False

  # response = upload_to_bucket('Voice List', 'Voice List.csv', bucket_name)

def upload_to_bucket_path(key, input_path, output_path):
  if output_path.startswith('gs://'):
    bucket_path = output_path[5:]
    split_bucket_path = re.split('/', bucket_path)
    bucket_name = split_bucket_path[0]

    blob_name = ""
    for idx in range(1, len(split_bucket_path)):
      blob_name = os.path.join(blob_name, split_bucket_path[idx]) 

    upload_to_bucket(key, blob_name, input_path, bucket_name)
