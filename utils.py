import time
from google.cloud import speech
from SpeechEnhancement import denoise
from pyannoteAudio.diarization import SpeakerDiarization

def transcribe_gcs(gcs_uri, sr, ch_count, lang_code):
    """Asynchronously transcribes the audio file specified by the gcs_uri."""
    
    start = time.time()
    client = speech.SpeechClient()

    audio = speech.RecognitionAudio(uri=gcs_uri)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz= sr,
        audio_channel_count= ch_count,
        language_code=lang_code,
        enable_word_time_offsets=True,
        enable_automatic_punctuation=True
    )

    operation = client.long_running_recognize(config=config, audio=audio)

    result = operation.result(timeout=300)
    print("[INFO]Speech Recognition Time Taken: {:.2f} seconds".format(time.time()-start))
    return result

def convert_diarized_result_to_list(result):
  prev_speaker = ""
  count = 0
  diarized = []
  for turn, _, speaker in result.itertracks(yield_label=True):
    count += 1

    if prev_speaker == "":
      prev_start_time = float("{:.1f}".format(turn.start))
      prev_end_time = float("{:.1f}".format(turn.end))
      prev_speaker = speaker

    # create new time stamp if the speaker changed
    elif prev_speaker != speaker:
      time_diff = abs(float("{:.1f}".format(turn.start)) - prev_end_time)

      # bridge the time gap when the difference is small by increasing the end time for the previous time stamp
      if time_diff >= 0.02 and time_diff < 2.3:
        prev_end_time += time_diff*0.7
        
      turn_start_time = "{:.0f}.{:.0f}".format(prev_start_time//60, prev_start_time%60)
      turn_end_time = "{:.0f}.{:.0f}".format(prev_end_time//60, prev_end_time%60)
      diarized.append(dict(start=prev_start_time, end=prev_end_time, tag=prev_speaker))
      prev_start_time = float("{:.1f}".format(turn.start))

      # bridge the time gap when the difference is small by decresing the start time for the current time stamp
      if time_diff >= 0.02 and time_diff < 2.3:
        prev_start_time -= time_diff*0.3
      prev_speaker = speaker

    prev_end_time = float("{:.1f}".format(turn.end))

    if count == len(result):
      turn_start_time = "{:.0f}.{:.0f}".format(prev_start_time//60, prev_start_time%60)
      turn_end_time = "{:.0f}.{:.0f}".format(prev_end_time//60, prev_end_time%60)
      diarized.append(dict(start=prev_start_time, end=prev_end_time, tag=prev_speaker))
    
  return diarized

def get_text_with_time(diarized_result, transcribed_result, output_path):
  substrings = []
  end_punct = [".", "?", ","]

  with open(output_path, 'w') as f:
    for i in range(len(diarized_result)):
      cur_block = diarized_result[i]
      for result in transcribed_result.results:
        alternative = result.alternatives[0]
        missed = True
        next_substrings = []

        for word_info in alternative.words:
          word = word_info.word
          start_time = word_info.start_time.total_seconds()
          end_time = word_info.end_time.total_seconds()
          
          if i < len(diarized_result)-1:
            next_block = diarized_result[i+1]
            
          # when the start time and end time of a word is within time stamp for current speaker tag
          if start_time >= cur_block['start'] and end_time <= cur_block['end']:
            if substrings and substrings[-1] == word:
              continue
            substrings.append(word)
            missed = False

          # when the start time and end time of a word is within time stamp for current and next speaker tag at the same time,
          # we will have a missed word
          elif start_time >= cur_block['start'] and start_time <= cur_block['end']:
            if end_time >= next_block['start'] and end_time <= next_block['end']:     
              # append the missed word to the current sentence it if does not end with punctuation in end_punct
              if substrings and substrings[-1][-1] not in end_punct:
                substrings.append(word)
              else:
                # missed word as the next sentence's first word if the current sentence ends with punctuation in end_punct
                next_substrings = [word]

          elif substrings and not missed:
            sentence = " ".join(substrings)
            diarized_start = "{:02.0f}:{:02.0f}".format(cur_block['start']//60, cur_block['start']%60)
            diarized_end = "{:02.0f}:{:02.0f}".format(cur_block['end']//60, cur_block['end']%60)
            f.write("[{} - {}] Speaker {}: {}\n".format(diarized_start, diarized_end, cur_block['tag'], sentence))
            print("[{} - {}] Speaker {}: {}".format(diarized_start, diarized_end, cur_block['tag'], sentence))
            
            substrings = next_substrings
            next_substrings = []

            missed = True
            break
  
    # last sentence will not be printed out when the last word from transcribed result is matched during the previous loop
    if not missed:
      end_block = diarized_result[-1]
      sentence = " ".join(substrings)
      diarized_start = "{:02.0f}:{:02.0f}".format(end_block['start']//60, end_block['start']%60)
      diarized_end = "{:02.0f}:{:02.0f}".format(end_block['end']//60, end_block['end']%60)
      f.write("[{} - {}] Speaker {}: {}\n".format(diarized_start, diarized_end, end_block['tag'], sentence))
      print("[{} - {}] Speaker {}: {}".format(diarized_start, diarized_end, end_block['tag'], sentence))