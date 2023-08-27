import time
from typing import Callable

import bottle
from spotty import Spotty
from spotty_audio_streamer import SpottyAudioStreamer
from utils import log_msg, LOGDEBUG


class HTTPSpottyAudioStreamer:
    def __init__(self, spotty: Spotty, gap_between_tracks: int = 0):
        self.__spotty: Spotty = spotty
        self.__gap_between_tracks: int = gap_between_tracks

        self.__spotty_streamer: SpottyAudioStreamer = SpottyAudioStreamer(self.__spotty)
        self.__spotty_audio_stream_generator = None

    def set_notify_track_finished(self, func: Callable[[str], None]) -> None:
        self.__spotty_streamer.set_notify_track_finished(func)

    def stop(self) -> None:
        self.__close_spotty_stream_generator()

    def __generate_spotty_audio_stream(self) -> str:
        return self.__spotty_streamer.send_audio_stream(0)

    def __close_spotty_stream_generator(self) -> None:
        if self.__spotty_audio_stream_generator:
            log_msg("Closing spotty audio stream generator.", LOGDEBUG)
            self.__spotty_audio_stream_generator.close()

    SPOTTY_AUDIO_TRACK_ROUTE = "/track/<track_id>/<duration>"
    # e.g., track_id = "2eHtBGvfD7PD7SiTl52Vxr", duration = 178.795

    def spotty_stream_audio_track(self, track_id: str, duration: str) -> bottle.Response:
        log_msg(f"GET request: {bottle.request}", LOGDEBUG)

        if self.__gap_between_tracks:
            # TODO - Can we improve on this? Sometimes, when playing a playlist
            #        with no gap between tracks, Kodi does not shutdown the visualizer
            #        before starting the next track and visualizer. So one visualizer
            #        instance is stopping at the same time as another is starting.
            # Give some time for visualizations to finish.
            time.sleep(self.__gap_between_tracks)

        self.__spotty_streamer.set_track(track_id, float(duration))

        log_msg(
            f"Start streaming spotify track '{track_id}',"
            f" track length {self.__spotty_streamer.get_track_length()}."
        )

        self.__close_spotty_stream_generator()

        def generate() -> str:
            self.__spotty_audio_stream_generator = self.__generate_spotty_audio_stream()
            return self.__spotty_audio_stream_generator

        bottle.response.content_type = "audio/x-wav"
        bottle.response.content_length = self.__spotty_streamer.get_track_length()

        if bottle.request.method.upper() == "GET":
            return bottle.Response(generate(), status=200)

        return bottle.Response(status=200)

    spotty_stream_audio_track.route = SPOTTY_AUDIO_TRACK_ROUTE
