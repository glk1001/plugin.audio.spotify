import threading
import time
from typing import Callable, Union

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
        self.__use_normalization = use_normalization
        self.__problem_with_terminate_streaming = problem_with_terminate_streaming

        self.__notify_track_finished: Callable[[str], None] = lambda x: None

        # The streamer of the most recent GET request.
        self.__current_streamer: Union[SpottyAudioStreamer, None] = None
        self.__stream_lock = threading.Lock()

    def use_normalization(self, value):
        self.__use_normalization = value

    def set_notify_track_finished(self, func: Callable[[str], None]) -> None:
        self.__notify_track_finished = func

    def stop(self) -> None:
        log_msg("Stopping spotty audio streaming.", LOGDEBUG)
        with self.__stream_lock:
            streamer = self.__current_streamer
            self.__current_streamer = None
        if streamer:
            self.__terminate_streaming(streamer)
        else:
            log_msg("No running audio streamer. Nothing to stop.", LOGDEBUG)

    @staticmethod
    def __terminate_streaming(streamer: SpottyAudioStreamer) -> None:
        if streamer.terminate_stream():
            log_msg(f"Terminated running streamer for track '{streamer.get_track_id()}'.", LOGDEBUG)
        else:
            log_msg(f"No running streamer. Nothing to terminate.", LOGDEBUG)

    SPOTTY_AUDIO_TRACK_ROUTE = "/track/<track_id>/<duration>"
    # e.g., track_id = "2eHtBGvfD7PD7SiTl52Vxr", duration = 178.795

    # IMPORTANT: If Kodi is running in non-buffered file mode (e.g., cache/buffermode=3 in
    #   'advancedsettings.xml'), then 'CurlFile::Open' will do multiple HTTP GETs for a stream
    #   and eventually request a partial range. Kodi also reconnects with a range request
    #   if a connection breaks. That's why there's the 'request ranges' code below. (Not to
    #   mention requiring a multithreaded web server to handle the streaming.)
    def spotty_stream_audio_track(self, track_id: str, duration: str) -> bottle.Response:
        log_msg(f"{bottle.request.method} request: {bottle.request}", LOGDEBUG)

        streamer = SpottyAudioStreamer(
            self.__spotty, track_id, float(duration), self.__use_normalization
        )
        file_size = streamer.get_track_length()

        request_range = bottle.request.headers.get("Range", "")
        log_msg(f"Request header range: '{request_range}'.", LOGDEBUG)

        range_begin = 0
        range_end = file_size - 1  # inclusive, as in HTTP
        content_range = ""
        if request_range and (request_range != "bytes=0-"):
            try:
                stream_range = request_range.split("bytes=")[1].split(",")[0].split("-")
                range_begin = int(stream_range[0])
                if stream_range[1].strip().isdigit():
                    range_end = min(int(stream_range[1]), file_size - 1)
            except (IndexError, ValueError):
                log_msg(f"Ignoring unparsable range header '{request_range}'.")
                range_begin = 0
                range_end = file_size - 1
            if range_begin >= file_size or range_begin > range_end:
                bottle.response.status = 416
                bottle.response.headers["Content-Range"] = f"bytes */{file_size}"
                return bottle.Response()
            if range_begin != 0 or range_end != file_size - 1:
                content_range = f"bytes {range_begin}-{range_end}/{file_size}"
        range_len = range_end - range_begin + 1

        if content_range:
            bottle.response.status = "206 Partial Content"
            bottle.response.headers["Content-Range"] = content_range
            log_msg(f"Partial request, range = {content_range}, length = {range_len}", LOGDEBUG)
        else:
            bottle.response.status = 200
            log_msg(f"Full request, content length = {range_len}.", LOGDEBUG)
        bottle.response.headers["Accept-Ranges"] = "bytes"
        bottle.response.content_type = "audio/x-wav"
        bottle.response.content_length = range_len

        # HEAD (or other non-GET) requests, e.g., Kodi probing an item, must not touch a
        # running stream.
        if bottle.request.method.upper() != "GET":
            return bottle.Response()

        with self.__stream_lock:
            previous_streamer = self.__current_streamer
            self.__current_streamer = streamer
        if previous_streamer:
            if self.__problem_with_terminate_streaming:
                log_msg(
                    "Already streaming. But flag 'problem_with_terminate_streaming' = True,"
                    " so NOT terminating current streamer."
                )
            else:
                log_msg("Already streaming. Terminating previous streamer.")
                self.__terminate_streaming(previous_streamer)

        if self.__gap_between_tracks and (range_begin == 0):
            # TODO - Can we improve on this? Sometimes, when playing a playlist
            #        with no gap between tracks, Kodi does not shutdown the visualizer
            #        before starting the next track and visualizer. So one visualizer
            #        instance is stopping at the same time as another is starting.
            # Give some time for visualizations to finish.
            log_msg(f"Delay {self.__gap_between_tracks}s before starting track.")
            time.sleep(self.__gap_between_tracks)

        log_msg(f"Start streaming spotify track '{track_id}', track length {file_size}.")

        return bottle.Response(
            streamer.send_part_audio_stream(range_begin, range_len, self.__notify_track_finished)
        )

    spotty_stream_audio_track.route = SPOTTY_AUDIO_TRACK_ROUTE
