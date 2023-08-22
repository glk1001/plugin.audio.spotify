from typing import Callable

import bottle
from spotty import Spotty
from spotty_audio_streamer import SpottyAudioStreamer
from utils import log_msg, LOGDEBUG


class HTTPSpottyAudioStreamer:
    def __init__(self, spotty: Spotty):
        self.__spotty = spotty

        self.__spotty_streamer = SpottyAudioStreamer(self.__spotty)
        self.__spotty_audio_stream_generator = None

    def set_notify_track_finished(self, func: Callable[[str], None]) -> None:
        self.__spotty_streamer.set_notify_track_finished(func)

    def stop(self) -> None:
        self.__close_spotty_stream_generator()

    def __generate_spotty_audio_stream(self, track_id: str, flt_duration: float) -> str:
        range_l = 0
        # range_r = file_size

        self.__spotty_streamer.set_track(track_id, flt_duration)

        return self.__spotty_streamer.send_audio_stream(range_l)

    def __close_spotty_stream_generator(self) -> None:
        if self.__spotty_audio_stream_generator:
            log_msg("Closing spotty audio stream generator.", LOGDEBUG)
            self.__spotty_audio_stream_generator.close()

    SPOTTY_AUDIO_TRACK_ROUTE = "/track/<track_id>/<duration>"
    # e.g., track_id = "2eHtBGvfD7PD7SiTl52Vxr", duration = 178.795

    def spotty_stream_audio_track(self, track_id: str, duration: str) -> bottle.Response:
        log_msg(f"GET request: {bottle.request}", LOGDEBUG)
        log_msg(f"Start streaming spotify track '{track_id}'.")

        self.__close_spotty_stream_generator()

        def generate() -> str:
            self.__spotty_audio_stream_generator = self.__generate_spotty_audio_stream(
                track_id, float(duration)
            )
            return self.__spotty_audio_stream_generator

        return bottle.Response(generate(), mimetype="audio/x-wav")

    spotty_stream_audio_track.route = SPOTTY_AUDIO_TRACK_ROUTE
