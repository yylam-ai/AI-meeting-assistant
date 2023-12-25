import os
import re
import wave
import time
from configparser import ConfigParser
from utils import transcribe_gcs
from utils import get_text_with_time
from utils import convert_diarized_result_to_list
from SpeakerDiarization.diarization import SpeakerDiarization
from bucket import upload_to_bucket_path
from SpeechEnhancement import denoise

# input_path = './data/test/meeting.wav'

parser = ConfigParser()
parser.read("config.ini")
sad_scores = parser.get('files', 'sad_scores')
scd_scores = parser.get('files', 'scd_scores')
emb_scores = parser.get('files', 'emb_scores')
params = parser.get('files', 'params')
key = parser.get('bucket', 'key')
bucket_uri = parser.get('bucket', 'bucket_uri')
speech_enhancement = parser.getboolean('settings', 'enhancement')
lang_code = parser.get('settings', 'lang_code')
speaker_count = parser.getint('settings', 'speaker_count')
method = "Kmeans" # "Kmeans or "affinity_propagation, changing this also need to change params's path in config.ini"

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = key

def full_pipeline(input_path):
  input_audio = re.split('/', input_path)[-1]

  input_file_name = os.path.splitext(input_audio)[0]
  denoise_file_name = 'denoised_' + input_audio

  # variable to create new directory for storing output (.txt/ .wav)
  new_dir_name = os.path.join('./data/output', input_file_name)

  if not os.path.isdir(new_dir_name):
    os.mkdir(new_dir_name)

  # get audio's sample rate and channel count
  with wave.open(input_path, "rb") as wave_file:
    sr = wave_file.getframerate()
    n_channel = wave_file.getnchannels()


  # using speech enhancement will reduce the sample rate of audio to 8000
  # speech enhancement model is trained with 8000sr audio
  if speech_enhancement:
    sr = 8000
    n_channel = 1
    denoise_output_path = os.path.join('./data/output', input_file_name, denoise_file_name)
    txt_output_path = os.path.join(new_dir_name, "denoised_" + input_file_name + ".txt")

    # perform speech enhancement
    denoise(input_path, denoise_output_path)

    while not os.path.exists(denoise_output_path):
        time.sleep(1)

    audio= {'audio': denoise_output_path}

    # upload to google bucket
    bucket_path = bucket_uri + denoise_file_name
    upload_to_bucket_path(key, denoise_output_path, bucket_path)

  else:
    audio = {'audio': input_path}
    txt_output_path = os.path.join(new_dir_name, input_file_name + ".txt")

    # upload to google bucket
    bucket_path = bucket_uri + input_audio
    upload_to_bucket_path(key, input_path, bucket_path)
  
  # initialize speaker diarization model
  pipeline = SpeakerDiarization(
      sad_scores = {sad_scores: {'step': 0.1}},
      scd_scores = {scd_scores: {'step': 0.1}},
      embedding = {emb_scores: {'step': 0.1}},
      method=method,
      k=speaker_count)

  pipeline.load_params(params)

  # run speaker diarization and get result
  result = pipeline(audio)

  # convert results from speaker diarization to list
  diarized_result = convert_diarized_result_to_list(result)
 
  # run speech recognition and get result
  transcribed_result = transcribe_gcs(bucket_path, sr, n_channel, lang_code)

  # combines results from speaker diarization and speech recognition and output log to a .txt file
  get_text_with_time(diarized_result, transcribed_result, txt_output_path)