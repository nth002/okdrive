import json
import base64
import time
import io
import tempfile
import os
import random
import wave
import audioop
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from datetime import datetime

# Import speech recognition
import speech_recognition as sr
from gtts import gTTS

# Global variables
latency_data = {
    'wake_word_detection': 0,
    'speech_to_text': 0,
    'llm_processing': 0,
    'text_to_speech': 0,
    'total': 0
}


# Load responses from JSON file
def load_responses_from_json(json_file_path):
    """Load responses from a JSON file"""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        response_map = {}

        # Handle different JSON structures
        if isinstance(data, dict):
            # Case 1: Direct key-value pairs
            # {"hello": "Hello!", "how are you": "I'm fine"}
            if all(isinstance(v, str) for v in data.values()):
                return data

            # Case 2: Nested structure with patterns and responses
            # {"intents": [{"tag": "greeting", "patterns": ["hello"], "responses": ["Hello!"]}]}
            elif "intents" in data:
                for intent in data["intents"]:
                    if "patterns" in intent and "responses" in intent:
                        for pattern in intent["patterns"]:
                            if pattern not in response_map:
                                response_map[pattern.lower()] = intent["responses"]

        elif isinstance(data, list):
            # Case 3: List of objects
            # [{"question": "hello", "answer": "Hello!"}]
            for item in data:
                if "question" in item and "answer" in item:
                    response_map[item["question"].lower()] = item["answer"]
                elif "pattern" in item and "response" in item:
                    response_map[item["pattern"].lower()] = item["response"]

        print(f"✅ Loaded {len(response_map)} responses from JSON file")
        return response_map

    except Exception as e:
        print(f"❌ Error loading JSON file: {e}")
        return {}


# Path to your JSON file - UPDATE THIS PATH
JSON_FILE_PATH = os.path.join(os.path.dirname(__file__), 'responses.json')

# Load responses from JSON
JSON_RESPONSE_MAP = load_responses_from_json(JSON_FILE_PATH)

# Direct response mapping (fallback if JSON doesn't have certain responses)
DEFAULT_RESPONSE_MAP = {
    # Wake word responses
    'hey okdriver': "Yes, I'm listening. How can I help you?",
    'ok driver': "I'm here. What do you need?",

    # Greetings
    'hello': "Hello! How can I help you today?",
    'hi': "Hi there! What can I do for you?",
    'hey': "Hey! How's it going?",
    'good morning': "Good morning! How can I assist you today?",
    'good afternoon': "Good afternoon! What can I do for you?",
    'good evening': "Good evening! How can I help?",

    # How are you
    'how are you': "I'm doing great, thank you for asking! How can I help you?",
    'how do you do': "I'm functioning well! Thanks for asking. What do you need?",
    'how are you doing': "I'm excellent and ready to assist you!",

    # Who are you
    'who are you': "I'm OKDriver, your personal driving assistant!",
    'what is your name': "My name is OKDriver, and I'm here to help you on your journey.",
    'your name': "I'm OKDriver - your friendly voice assistant for the road.",

    # Time
    'what time is it': "The current time is {time}.",
    'tell me the time': "It's {time} right now.",
    'current time': "Right now, it's {time}.",
    'time now': "The time is {time}.",

    # Date
    'what is the date': "Today's date is {date}.",
    'today\'s date': "It's {date}.",
    'current date': "Today is {date}.",
    'what day is it': "Today is {day}.",

    # Thanks
    'thank you': "You're welcome! Happy to help!",
    'thanks': "My pleasure! Drive safely!",
    'thank you so much': "Anytime! That's what I'm here for.",

    # Goodbye
    'bye': "Goodbye! Drive safely and have a great day!",
    'goodbye': "See you later! Safe travels!",
    'see you later': "Take care! I'll be here when you need me.",

    # Help
    'help': "I can help you with time, date, navigation, traffic, weather, and general questions. Just ask me anything!",
    'what can you do': "I can tell you the time and date, help with navigation, provide traffic info, share weather updates, and answer general questions. What do you need?",

    # Jokes
    'tell me a joke': "Why don't scientists trust atoms? Because they make up everything!",
    'joke': "What do you call a fake noodle? An impasta!",
    'make me laugh': "Why did the scarecrow win an award? He was outstanding in his field!",

    # Fun facts
    'fun fact': "Did you know that honey never spoils? Archaeologists found 3000-year-old honey in Egyptian tombs that was still edible!",
    'tell me something interesting': "A day on Venus is longer than a year on Venus!",

    # Driving tips
    'driving tip': "Always maintain a safe following distance of at least 3 seconds behind the car in front of you.",
    'safety tip': "Remember to check your blind spots before changing lanes. Your mirrors don't show everything!",

    # Weather
    'weather': "I don't have real-time weather data. Please check your weather app for accurate information.",
    'weather today': "For weather updates, I'd recommend checking a weather app or website.",

    # Traffic
    'traffic': "I recommend checking Google Maps or Waze for real-time traffic updates.",
    'traffic conditions': "For accurate traffic information, your navigation app would be the best source.",

    # Navigation
    'navigate': "I'd recommend using your favorite maps app for turn-by-turn directions.",
    'directions': "Please open Google Maps or your preferred navigation app for directions.",

    # Emergency
    'emergency': "If this is an emergency, please call 911 or your local emergency services immediately.",
    'accident': "If you're in an accident, make sure everyone is safe and call for help if needed.",
}

# Merge JSON responses with defaults (JSON takes precedence)
RESPONSE_MAP = {**DEFAULT_RESPONSE_MAP, **JSON_RESPONSE_MAP}

# Also create a map for partial matching with multiple possible responses
PARTIAL_MATCH_RESPONSES = {}
for key, value in RESPONSE_MAP.items():
    # If value is a list, store it as is, otherwise convert to list
    if isinstance(value, list):
        PARTIAL_MATCH_RESPONSES[key] = value
    else:
        PARTIAL_MATCH_RESPONSES[key] = [value]

# Wake word variations
WAKE_WORDS = ['hey okdriver', 'ok driver', 'hey driver', 'okdriver']

# Friendly prompts when recognition fails
FRIENDLY_PROMPTS = [
    "I didn't catch that. Could you please speak clearly?",
    "Sorry, I couldn't hear you well. Please try again.",
    "Would you mind repeating that?",
    "I'm having trouble understanding. Can you speak a bit slower?",
    "Let's try again. What would you like to ask?",
]


def index(request):
    """Main page view"""
    return render(request, 'assistant/index.html')


def get_status(request):
    """Get assistant status"""
    return JsonResponse({
        'status': 'ready',
        'wake_word': getattr(settings, 'WAKE_WORD', 'Hey OKDriver'),
        'message': "Assistant is ready. Click the mic and ask anything!",
        'responses_loaded': len(RESPONSE_MAP)
    })


@csrf_exempt
@require_http_methods(["POST"])
def process_audio(request):
    """Process audio with improved recognition"""
    global latency_data

    temp_audio_path = None

    try:
        start_time = time.time()

        # Get audio data
        data = json.loads(request.body)
        audio_data = base64.b64decode(data['audio'])

        # Save as WAV file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as f:
            f.write(audio_data)
            temp_audio_path = f.name

        # Wake word timing
        latency_data['wake_word_detection'] = round((time.time() - start_time) * 1000, 2)

        # Preprocess audio
        preprocess_audio(temp_audio_path)

        # Speech recognition
        stt_start = time.time()
        text = english_speech_recognition(temp_audio_path)
        latency_data['speech_to_text'] = round((time.time() - stt_start) * 1000, 2)

        print(f"Recognized: '{text}'")

        # Get response
        llm_start = time.time()

        if text:
            response_text = get_best_response(text)
        else:
            response_text = random.choice(FRIENDLY_PROMPTS)

        latency_data['llm_processing'] = round((time.time() - llm_start) * 1000, 2)

        # Text to speech
        tts_start = time.time()
        audio_response = text_to_speech(response_text)
        latency_data['text_to_speech'] = round((time.time() - tts_start) * 1000, 2)

        latency_data['total'] = round((time.time() - start_time) * 1000, 2)

        audio_base64 = base64.b64encode(audio_response).decode('utf-8') if audio_response else None

        return JsonResponse({
            'success': True,
            'text': text if text else "",
            'response': response_text,
            'audio': audio_base64,
            'latency': latency_data
        })

    except Exception as e:
        print(f"Error: {e}")
        return JsonResponse({
            'success': True,
            'text': "",
            'response': random.choice(FRIENDLY_PROMPTS),
            'audio': None,
            'latency': latency_data
        })

    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except:
                pass


def english_speech_recognition(audio_path):
    """English speech recognition"""

    if not os.path.exists(audio_path):
        return None

    recognizer = sr.Recognizer()

    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8

    try:
        with sr.AudioFile(audio_path) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.record(source)

            # Try English languages
            languages = ['en-US', 'en-GB', 'en-IN']

            for lang in languages:
                try:
                    text = recognizer.recognize_google(audio, language=lang)
                    if text and len(text.strip()) > 0:
                        print(f"Recognized with {lang}: {text}")
                        return text
                except:
                    continue

            return None

    except Exception as e:
        print(f"Recognition error: {e}")
        return None


def preprocess_audio(audio_path):
    """Preprocess audio file for better recognition"""
    try:
        with wave.open(audio_path, 'rb') as wav:
            params = wav.getparams()
            frames = wav.readframes(params.nframes)

        if params.nchannels > 1:
            frames = audioop.tomono(frames, params.sampwidth, 0.5, 0.5)
            params = (1, params.sampwidth, params.framerate, params.nframes,
                      params.comptype, params.compname)

        frames = audioop.mul(frames, params.sampwidth, 2.0)

        with wave.open(audio_path, 'wb') as wav:
            wav.setparams(params)
            wav.writeframes(frames)

    except Exception as e:
        print(f"Audio preprocessing error: {e}")


def get_best_response(text):
    """Get the best response based on the input text"""

    if not text:
        return "What would you like to know?"

    text_lower = text.lower().strip()

    # Check for wake word only
    if text_lower in WAKE_WORDS:
        return "Yes, I'm listening. How can I help you?"

    # Check for time queries
    if any(word in text_lower for word in ['time', 'clock']):
        current_time = datetime.now().strftime("%I:%M %p")
        return f"The current time is {current_time}."

    # Check for date queries
    if any(word in text_lower for word in ['date', 'day']):
        if 'day' in text_lower and 'date' not in text_lower:
            current_day = datetime.now().strftime("%A")
            return f"Today is {current_day}."
        else:
            current_date = datetime.now().strftime("%B %d, %Y")
            return f"Today's date is {current_date}."

    # Check for exact matches in response map
    if text_lower in PARTIAL_MATCH_RESPONSES:
        responses = PARTIAL_MATCH_RESPONSES[text_lower]
        response = random.choice(responses) if isinstance(responses, list) else responses
        # Format dynamic responses if needed
        if '{time}' in response:
            return response.format(time=datetime.now().strftime("%I:%M %p"))
        elif '{date}' in response:
            return response.format(date=datetime.now().strftime("%B %d, %Y"))
        elif '{day}' in response:
            return response.format(day=datetime.now().strftime("%A"))
        return response

    # Check for partial matches
    for key, responses in PARTIAL_MATCH_RESPONSES.items():
        if key in text_lower or text_lower in key:
            response = random.choice(responses) if isinstance(responses, list) else responses
            # Format dynamic responses if needed
            if '{time}' in response:
                return response.format(time=datetime.now().strftime("%I:%M %p"))
            elif '{date}' in response:
                return response.format(date=datetime.now().strftime("%B %d, %Y"))
            elif '{day}' in response:
                return response.format(day=datetime.now().strftime("%A"))
            return response

    # Default response for unknown queries
    default_responses = [
        f"I heard you say '{text}'. How can I help you with that?",
        f"You asked about '{text}'. I'm here to assist you.",
        f"I understand you're asking about '{text}'. What would you like to know?",
        f"Interesting question about '{text}'. Could you tell me more?"
    ]
    return random.choice(default_responses)


@csrf_exempt
@require_http_methods(["POST"])
def process_command(request):
    """Process text command"""
    global latency_data

    try:
        data = json.loads(request.body)
        command = data.get('command', '')

        start_time = time.time()

        if command:
            response_text = get_best_response(command)
        else:
            response_text = "Hello! I'm OKDriver. What would you like to know?"

        latency_data['llm_processing'] = round((time.time() - start_time) * 1000, 2)

        tts_start = time.time()
        audio_response = text_to_speech(response_text)
        latency_data['text_to_speech'] = round((time.time() - tts_start) * 1000, 2)

        latency_data['total'] = round((time.time() - start_time) * 1000, 2)

        audio_base64 = base64.b64encode(audio_response).decode('utf-8') if audio_response else None

        return JsonResponse({
            'success': True,
            'response': response_text,
            'audio': audio_base64,
            'latency': latency_data
        })

    except Exception as e:
        print(f"Command error: {e}")
        return JsonResponse({
            'success': True,
            'response': "Hello! I'm OKDriver. How can I help you today?",
            'audio': None,
            'latency': latency_data
        })


def get_latency(request):
    """Get latency data"""
    return JsonResponse(latency_data)


def text_to_speech(text):
    """Convert text to speech - English only"""
    try:
        if not text:
            text = "Hello! I'm OKDriver. How can I help you?"

        tts = gTTS(text=text, lang='en', slow=False)
        audio_bytes = io.BytesIO()
        tts.write_to_fp(audio_bytes)
        audio_bytes.seek(0)

        return audio_bytes.read()

    except Exception as e:
        print(f"TTS Error: {e}")
        return None


# Optional: Add a debug endpoint to see loaded responses
@csrf_exempt
@require_http_methods(["GET"])
def debug_responses(request):
    """Debug endpoint to see loaded responses"""
    return JsonResponse({
        'total_responses': len(RESPONSE_MAP),
        'sample_keys': list(RESPONSE_MAP.keys())[:10],
        'json_loaded': len(JSON_RESPONSE_MAP) > 0
    })