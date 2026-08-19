import soundcard as sc
import time
import warnings
import numpy as np

SAMPLE_RATE = 44100
BLOCK_SIZE = 2048  # frames per analysis chunk (~46ms at 44.1kHz)

# Suppress annoying soundcard discontinuity warnings when buffers drop
warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

def get_loopback_mic():
    """Returns a 'microphone' object that actually records the default
    speaker's output (loopback), not an actual mic."""
    speaker = sc.default_speaker()
    return sc.get_microphone(id=str(speaker.name), include_loopback=True)

def audio_stream(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE):
    """Generator yielding one block of audio (numpy array, shape
    [block_size, channels]) at a time, forever. Resilient to crashes."""
    
    while True:
        try:
            mic = get_loopback_mic()
            with mic.recorder(samplerate=sample_rate) as recorder:
                print("Audio capture started successfully.")
                while True:
                    chunk = recorder.record(numframes=block_size)
                    
                    # Silence detection
                    if np.max(np.abs(chunk)) < 1e-4:
                        yield None
                    else:
                        yield chunk
        except Exception as e:
            print(f"[Audio Error] Capture failed: {e}. Retrying in 2 seconds...")
            time.sleep(2.0)
