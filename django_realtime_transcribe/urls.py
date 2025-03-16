from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("start_recording/", views.start_recording, name="start_recording"),
    path("stop_recording/", views.stop_recording, name="stop_recording"),
    path(
        "stream_transcription/", views.stream_transcription, name="stream_transcription"
    ),
    path("record_chunk/", views.record_chunk, name="record_chunk"),
    path("translate/", views.translate_text_view, name="translate"),
]
