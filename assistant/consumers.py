import json
import base64
import numpy as np
from channels.generic.websocket import AsyncWebsocketConsumer
from .utils import VoiceAssistant, LatencyTracker
import asyncio


class AudioConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.assistant = VoiceAssistant()
        self.latency_tracker = LatencyTracker()
        self.is_listening = False

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        data = json.loads(text_data)
        command = data.get('command')

        if command == 'start_listening':
            self.latency_tracker.start()
            self.is_listening = True

        elif command == 'audio_data':
            # Process audio chunk
            audio_data = base64.b64decode(data['audio'])

            # Check for wake word
            if self.is_listening:
                # Process audio for wake word detection
                # This would integrate with the wake word detector
                pass

        elif command == 'stop_listening':
            self.is_listening = False
            latencies = self.latency_tracker.get_latencies()

            await self.send(text_data=json.dumps({
                'type': 'latency_report',
                'latencies': latencies
            }))