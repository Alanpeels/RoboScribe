import wave
from discord.ext import voice_recv

class WavAudioSink(voice_recv.AudioSink):
    def __init__(self, filename):
        self.filename = filename
        self.audio_data = []
    
    def write(self, user, data):
        # Collect PCM audio data from all users (mixed)
        self.audio_data.append(data.pcm)
    
    def wants_opus(self):
        return False  # We want PCM data, not Opus
    
    def cleanup(self):
        # Write collected audio to WAV file
        if self.audio_data:
            with wave.open(self.filename, 'wb') as wav_file:
                wav_file.setnchannels(2)  # Stereo
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(48000)  # Discord uses 48kHz
                for chunk in self.audio_data:
                    wav_file.writeframes(chunk)
