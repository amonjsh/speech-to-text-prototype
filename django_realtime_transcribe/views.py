# views.py
import json
import threading
import queue
import os
import time
import struct

from django.shortcuts import render
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from google.cloud import speech_v2 as speech
from google.oauth2 import service_account
from google.cloud import translate_v2 as translate  # Import Translate API

# Configuration (Keep your existing configuration)
PROJECT_ID = "avian-direction-453820-q1"
CREDENTIALS_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
LANGUAGE_CODE = "en-US"
CHUNK_SIZE = 1024

# Global Variables (Keep your existing global variables)
audio_queue = queue.Queue()
transcript_queue = queue.Queue()
recording_active = False
client = None
speech_settings = None
credentials_loaded = False
streaming_thread = None
translate_client = None  # Add Translate client


def load_credentials():
    """Load Google Speech and Translate API credentials."""
    global client, speech_settings, credentials_loaded, translate_client
    try:
        if CREDENTIALS_FILE and os.path.exists(CREDENTIALS_FILE):
            credentials = service_account.Credentials.from_service_account_file(
                CREDENTIALS_FILE
            )
            client = speech.SpeechClient(
                credentials=credentials,
                client_options={"api_endpoint": "us-central1-speech.googleapis.com"},
            )
            speech_settings = speech.StreamingRecognitionConfig(
                config=speech.RecognitionConfig(
                    auto_decoding_config={},
                    language_codes=[LANGUAGE_CODE],
                    model="latest_long",
                    features=speech.RecognitionFeatures(
                        enable_automatic_punctuation=True
                    ),
                ),
            )
            print("✅ Google Cloud Speech client initialized.")

            # Initialize Translate client (remove project argument)
            translate_client = translate.Client(credentials=credentials)
            print("✅ Google Cloud Translate client initialized.")

            credentials_loaded = True
        else:
            print(f"❌ Error: Credentials file not found at {CREDENTIALS_FILE}")
            client, speech_settings, credentials_loaded, translate_client = (
                None,
                None,
                False,
                None,
            )
    except Exception as e:
        print(f"❌ Error loading credentials: {e}")
        client, speech_settings, credentials_loaded, translate_client = (
            None,
            None,
            False,
            None,
        )


def request_generator():
    global speech_settings
    if speech_settings:
        yield speech.StreamingRecognizeRequest(
            streaming_config=speech_settings,
            recognizer=f"projects/{PROJECT_ID}/locations/us-central1/recognizers/_",
        )
        print("👂 Initial streaming config sent.")
        while recording_active:
            try:
                chunk = audio_queue.get(
                    timeout=None
                )  # Block indefinitely until a chunk arrives
                yield speech.StreamingRecognizeRequest(audio=chunk)
                print(f"👂 Sent audio chunk of size: {len(chunk)}")
            except Exception as e:
                print(f"⚠️ Error in request generator: {e}")
                break
        print("🔴 Closing transcription stream.")


def transcribe_audio():
    global recording_active, client, speech_settings, transcript_queue
    print("🎤 Transcription started.")
    if not client or not speech_settings:
        print("❌ Speech API not initialized.")
        return

    requests = request_generator()
    try:
        responses = client.streaming_recognize(requests=requests)
        print("📡 Streaming started.")
        for response in responses:
            if not response.results:
                print("⚪️ No result in response.")
                continue
            result = response.results[0]
            if not result.alternatives:
                print("⚪️ No alternative in result.")
                continue
            transcript = result.alternatives[0].transcript
            is_final = result.is_final
            print(f"📝 Received transcript: '{transcript}', is_final: {is_final}")
            transcript_queue.put({"text": transcript, "is_final": is_final})
            print(f"📤 Added to transcript_queue: '{transcript}'")
            if is_final:
                print(f"✅ Final transcript: {transcript}")
                if not recording_active and audio_queue.empty():
                    break
    except Exception as e:
        print(f"❌ Error during transcription: {e}")
    finally:
        print("🛑 Transcription thread stopped.")
        recording_active = False


def index(request):
    return render(request, "index.html")


@csrf_exempt
def start_recording(request):
    global recording_active, audio_queue, transcript_queue, credentials_loaded, streaming_thread
    if request.method == "POST":
        print("🎬 Starting recording...")
        if not credentials_loaded:
            load_credentials()
            if not credentials_loaded:
                return JsonResponse(
                    {"status": "error", "message": "Could not load credentials."}
                )

        if streaming_thread and streaming_thread.is_alive():
            print("🕓 Waiting for previous transcription to stop...")
            recording_active = False
            streaming_thread.join(timeout=1)

        recording_active = True
        audio_queue = queue.Queue()
        transcript_queue = queue.Queue()

        streaming_thread = threading.Thread(target=transcribe_audio)
        streaming_thread.start()

        return JsonResponse({"status": "recording started"})
    return JsonResponse({"status": "error", "message": "Could not start recording"})


@csrf_exempt
def stop_recording(request):
    global recording_active, streaming_thread
    if request.method == "POST" and recording_active:
        print("🛑 Stopping recording...")
        recording_active = False
        if streaming_thread and streaming_thread.is_alive():
            streaming_thread.join(timeout=1)
        return JsonResponse({"status": "recording stopped"})
    return JsonResponse({"status": "error", "message": "Recording not active"})


def stream_transcription(request):
    def event_stream():
        global recording_active, transcript_queue
        print("➡️ Event stream started.")

        while recording_active or not transcript_queue.empty():
            print(
                f"⏳ Event stream loop - recording_active: {recording_active}, transcript_queue size: {transcript_queue.qsize()}"
            )
            try:
                transcript_data = transcript_queue.get(timeout=0.1)
                print(f"⬇️ Got from transcript_queue: {transcript_data}")
                yield f"data: {json.dumps(transcript_data)}\n\n"
                print(f"⬆️ Sent SSE data: {json.dumps(transcript_data)}")
            except queue.Empty:
                time.sleep(0.01)
            except Exception as e:
                print(f"⚠️ Error in event stream: {e}")
                break

        print("🔚 Event stream finished.")
        yield f"data: {json.dumps({'text': '[TRANSCRIBING ENDED]', 'is_final': True})}\n\n"

    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


@csrf_exempt
def record_chunk(request):
    if request.method == "POST":
        audio_blob = request.FILES.get("audio_data")

        if not audio_blob:
            return JsonResponse(
                {"status": "error", "message": "No audio data received"}
            )

        audio_content = audio_blob.read()
        audio_queue.put(audio_content)
        print(
            f"📥 Received audio chunk of size: {len(audio_content)}, queue size: {audio_queue.qsize()}"
        )
        return JsonResponse({"status": "chunk received"})

    return JsonResponse({"status": "error", "message": "Invalid request"})


@csrf_exempt
def translate_text_view(request):
    if request.method == "POST":
        text = request.POST.get("text")
        target_language = request.POST.get("target_language")

        if not text or not target_language or not translate_client:
            return JsonResponse(
                {"error": "Missing parameters or Translate API not initialized."},
                status=400,
            )

        try:
            translation = translate_client.translate(
                text, target_language=target_language, source_language=LANGUAGE_CODE
            )
            return JsonResponse({"translated_text": translation["translatedText"]})
        except Exception as e:
            print(f"❌ Error during translation: {e}")
            return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"error": "Invalid request method."}, status=405)


# Initialize on startup (Keep this)
load_credentials()
