import threading
import time
from typing import Callable

import bottle
from spotty import Spotty
from spotty_audio_streamer import SpottyAudioStreamer
from utils import log_msg, LOGDEBUG


class HTTPSpottyAudioStreamer:
    def __init__(
        self,
        spotty: Spotty,
        gap_between_tracks: int = 0,
        use_normalization: bool = True,
        problem_with_terminate_streaming=False,
    ):
        self.__spotty: Spotty = spotty
        self.__gap_between_tracks: int = gap_between_tracks
        self.__problem_with_terminate_streaming = problem_with_terminate_streaming

        self.__spotty_streamer: SpottyAudioStreamer = SpottyAudioStreamer(self.__spotty)
        self.__spotty_streamer.use_normalization = use_normalization

        self.__is_streaming = False
        self.__stream_lock = threading.Lock()

    def use_normalization(self, value):
        self.__spotty_streamer.use_normalization = value

    def set_notify_track_finished(self, func: Callable[[str], None]) -> None:
        self.__spotty_streamer.set_notify_track_finished(func)

    def stop(self) -> None:
        log_msg("Stopping spotty audio streaming.", LOGDEBUG)
        if self.__is_streaming:
            self.__terminate_streaming()
        else:
            log_msg("No running audio streamer. Nothing to stop.", LOGDEBUG)

    def __terminate_streaming(self) -> None:
        if self.__spotty_streamer.terminate_stream():
            log_msg(f"Terminated running streamer.", LOGDEBUG)
        else:
            log_msg(f"No running streamer. Nothing to terminate.", LOGDEBUG)

    SPOTTY_AUDIO_TRACK_ROUTE = "/track/<track_id>/<duration>"
    # e.g., track_id = "2eHtBGvfD7PD7SiTl52Vxr", duration = 178.795

    # IMPORTANT: If Kodi is running in non-buffered file mode (e.g., cache/buffermode=3 in
    #   'advancedsettings.xml'), then 'CurlFile::Open' will do multiple HTTP GETs for a stream
    #   and eventually request a partial range. That's why there's the added complication
    #   of the '__is_streaming' flag and 'request ranges' code below. (Not to mention
    #   requiring a multithreaded web server to handle the streaming.)
    def spotty_stream_audio_track(self, track_id: str, duration: str) -> bottle.Response:
        log_msg(f"GET request: {bottle.request}", LOGDEBUG)

        if self.__is_streaming:
            if self.__problem_with_terminate_streaming:
                log_msg("Already streaming. But flag 'problem_with_terminate_streaming' = True,"
                        " so NOT terminating current streamer.")
            else:
                with self.__stream_lock:
                    log_msg("Already streaming. Terminating current streamer.")
                    self.__terminate_streaming()

        self.__is_streaming = True

        if self.__gap_between_tracks:
            # TODO - Can we improve on this? Sometimes, when playing a playlist
            #        with no gap between tracks, Kodi does not shutdown the visualizer
            #        before starting the next track and visualizer. So one visualizer
            #        instance is stopping at the same time as another is starting.
            # Give some time for visualizations to finish.
            log_msg(f"Delay {self.__gap_between_tracks}s before starting track.")
            time.sleep(self.__gap_between_tracks)

        self.__spotty_streamer.set_track(track_id, float(duration))

        log_msg(
            f"Start streaming spotify track '{track_id}',"
            f" track length {self.__spotty_streamer.get_track_length()}."
        )

        file_size = self.__spotty_streamer.get_track_length()
        range_begin = 0
        range_end = file_size

        def generate() -> str:
            range_len = range_end - range_begin
            return self.__spotty_streamer.send_part_audio_stream(range_len, range_begin)

        request_range = bottle.request.headers.get("Range", "")
        log_msg(f"Request header range: '{request_range}'.", LOGDEBUG)

        if not request_range or (request_range == "bytes=0-"):
            status = 200
            content_range = ""
            log_msg(f"Full request, content length = {range_end- range_begin}.", LOGDEBUG)
        else:
            status = "206 Partial Content"
            stream_range = bottle.request.headers["Range"].split("bytes=")[1].split("-")
            range_begin = int(stream_range[0])
            range_end = int(stream_range[1]) if stream_range[1].isdigit() else file_size
            content_range = f"bytes {range_begin}-{range_end}/{file_size}"
            log_msg(
                f"Partial request, range = {content_range}," f" length = {range_end - range_begin}",
                LOGDEBUG,
            )

        bottle.response.status = status
        bottle.response.headers["Accept-Ranges"] = "bytes"
        bottle.response.content_type = "audio/x-wav"
        bottle.response.content_length = range_end - range_begin
        if content_range:
            bottle.response.headers["Content-Range"] = content_range

        if bottle.request.method.upper() == "GET":
            return bottle.Response(generate())

        return bottle.Response()

    spotty_stream_audio_track.route = SPOTTY_AUDIO_TRACK_ROUTE
