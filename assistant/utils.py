import numpy as np
import threading
import queue
import time
import json
import requests
import io
import wave
from datetime import datetime
from django.conf import settings

# Audio processing
import pyaudio
import speech_recognition as sr
from gtts import gTTS
import webrtcvad

# For wake word detection (using MyCroft Precise)
try:
    from precise_runner import PreciseRunner, PreciseEngine

    PRECISE_AVAILABLE = True
except ImportError:
    PRECISE_AVAILABLE = False
    print("Warning: Precise runner not available. Using simple keyword detection.")


class LatencyTracker:
    """Track latency for each stage of the pipeline"""

    def __init__(self):
        self.start_time = None
        self.wake_word_time = None
        self.stt_time = None
        self.llm_time = None
        self.tts_time = None
        self.total_time = None

    def start(self):
        self.start_time = time.time()

    def mark_wake_word(self):
        self.wake_word_time = time.time()

    def mark_stt(self):
        self.stt_time = time.time()

    def mark_llm(self):
        self.llm_time = time.time()

    def mark_tts(self):
        self.tts_time = time.time()

    def mark_total(self):
        self.total_time = time.time()

    def get_latencies(self):
        """Return latencies for each stage in milliseconds"""
        return {
            'wake_word_detection': round((self.wake_word_time - self.start_time) * 1000,
                                         2) if self.wake_word_time else None,
            'speech_to_text': round((self.stt_time - self.wake_word_time) * 1000, 2) if self.stt_time else None,
            'llm_processing': round((self.llm_time - self.stt_time) * 1000, 2) if self.llm_time else None,
            'text_to_speech': round((self.tts_time - self.llm_time) * 1000, 2) if self.tts_time else None,
            'total': round((self.total_time - self.start_time) * 1000, 2) if self.total_time else None
        }


class WakeWordDetector:
    """Wake word detection using MyCroft Precise or simple keyword detection"""

    def __init__(self, wake_word="hey"):
        self.wake_word = wake_word.lower()
        self.is_listening = False
        self.callback = None
        self.audio_queue = queue.Queue()

        if PRECISE_AVAILABLE:
            # Use Precise for better wake word detection
            self.setup_precise()
        else:
            # Fallback to simple VAD + keyword matching
            self.setup_simple_detector()

    def setup_precise(self):
        """Setup MyCroft Precise engine"""
        try:
            engine = PreciseEngine(settings.PRECISE_ENGINE_PATH)
            self.runner = PreciseRunner(engine, on_activation=self.on_wake_word)
            self.use_precise = True
        except:
            self.use_precise = False
            self.setup_simple_detector()

    def setup_simple_detector(self):
        """Simple VAD-based detector"""
        self.vad = webrtcvad.Vad(2)  # Aggressiveness level 2
        self.use_precise = False

    def on_wake_word(self):
        """Called when wake word is detected"""
        if self.callback:
            self.callback()

    def start_listening(self, callback):
        """Start listening for wake word"""
        self.callback = callback
        self.is_listening = True

        if self.use_precise:
            self.runner.start()
        else:
            self.simple_detection_loop()

    def simple_detection_loop(self):
        """Simple detection loop using VAD and keyword matching"""

        def detect():
            import speech_recognition as sr
            r = sr.Recognizer()

            while self.is_listening:
                try:
                    with sr.Microphone() as source:
                        print("Listening for wake word...")
                        audio = r.listen(source, timeout=1, phrase_time_limit=2)

                    # Check if audio contains speech
                    audio_data = np.frombuffer(audio.get_raw_data(), dtype=np.int16)
                    if self.vad.is_speech(audio_data.tobytes(), settings.SAMPLE_RATE):
                        # Try to transcribe
                        try:
                            text = r.recognize_google(audio).lower()
                            if self.wake_word in text:
                                print(f"Wake word detected: {text}")
                                self.on_wake_word()
                        except:
                            pass

                except Exception as e:
                    print(f"Error in detection loop: {e}")
                    time.sleep(0.1)

        thread = threading.Thread(target=detect)
        thread.daemon = True
        thread.start()

    def stop_listening(self):
        """Stop listening for wake word"""
        self.is_listening = False
        if self.use_precise:
            self.runner.stop()


class SpeechToText:
    """Convert speech to text"""

    def __init__(self):
        self.recognizer = sr.Recognizer()
        # Optimize for speed
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.5

    def listen_for_speech(self, timeout=5):
        """Listen for speech after wake word"""
        try:
            with sr.Microphone() as source:
                print("Listening for command...")
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=5)
                return audio
        except sr.WaitTimeoutError:
            return None

    def transcribe(self, audio):
        """Convert audio to text"""
        try:
            # Using Google's free STT API
            text = self.recognizer.recognize_google(audio)
            print(f"Transcribed: {text}")
            return text
        except sr.UnknownValueError:
            return "Could not understand audio"
        except sr.RequestError as e:
            return f"STT API error: {e}"


class LLMProcessor:
    """Process text through LLM API"""

    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        self.api_url = settings.LLM_API_URL
        self.model = settings.LLM_MODEL

    def process(self, text):
        """Send query to LLM and get response"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.model,
                "messages": [
                    {"role": "system",
                     "content": "You are a helpful voice assistant for a driver. Keep responses concise and clear."},
                    {"role": "user", "content": text}
                ],
                "max_tokens": 100  # Limit response length for speed
            }

            response = requests.post(self.api_url, headers=headers, json=data, timeout=5)

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                return f"Error: {response.status_code}"

        except Exception as e:
            return f"LLM Error: {str(e)}"


class TextToSpeech:
    """Convert text to speech"""

    def __init__(self):
        self.tts_queue = queue.Queue()

    def synthesize(self, text, lang='hi'):
        """Convert text to speech and return audio bytes"""
        try:
            tts = gTTS(text=text, lang=lang, slow=False)

            # Save to bytes buffer
            audio_bytes = io.BytesIO()
            tts.write_to_fp(audio_bytes)
            audio_bytes.seek(0)

            return audio_bytes.read()

        except Exception as e:
            print(f"TTS Error: {e}")
            return None

    def play_audio(self, audio_bytes):
        """Play audio bytes"""
        if not audio_bytes:
            return

        try:
            import pygame
            pygame.mixer.init()

            # Create a temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(delete=True, suffix='.mp3') as f:
                f.write(audio_bytes)
                f.flush()

                pygame.mixer.music.load(f.name)
                pygame.mixer.music.play()

                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)

        except Exception as e:
            print(f"Playback Error: {e}")


class VoiceAssistant:
    """Main voice assistant coordinator"""

    def __init__(self):
        self.wake_word_detector = WakeWordDetector(settings.WAKE_WORD)
        self.stt = SpeechToText()
        self.llm = LLMProcessor()
        self.tts = TextToSpeech()
        self.latency_tracker = LatencyTracker()
        self.is_active = False

    def on_wake_word_detected(self):
        """Handle wake word detection"""
        if self.is_active:
            return

        self.is_active = True
        self.latency_tracker.mark_wake_word()

        # Listen for command
        audio = self.stt.listen_for_speech()

        if audio:
            # Transcribe
            self.latency_tracker.mark_stt()
            text = self.stt.transcribe(audio)

            if text and "error" not in text.lower():
                # Get LLM response
                self.latency_tracker.mark_llm()
                response = self.llm.process(text)

                # Convert to speech
                self.latency_tracker.mark_tts()
                audio_response = self.tts.synthesize(response)

                # Play response
                if audio_response:
                    self.tts.play_audio(audio_response)

        self.latency_tracker.mark_total()

        # Log latencies
        latencies = self.latency_tracker.get_latencies()
        print("\n=== Latency Report ===")
        for stage, latency in latencies.items():
            if latency:
                print(f"{stage}: {latency} ms")

        self.is_active = False

    def start(self):
        """Start the voice assistant"""
        print(f"Voice Assistant started. Wake word: '{settings.WAKE_WORD}'")
        self.wake_word_detector.start_listening(self.on_wake_word_detected)

    def stop(self):
        """Stop the voice assistant"""
        self.wake_word_detector.stop_listening()