import math
import threading
from typing import Callable

import xbmc

# Would like to do the following submodule imports, but they won't work.
# See the comment in 'lib/__init__.py':
# 'from deps import cherrypy'
# 'from deps.cherrypy._cpnative_server import CPHTTPServer'
import cherrypy
from cherrypy._cpnative_server import CPHTTPServer
from spotty_audio_streamer import SpottyAudioStreamer
from utils import log_msg, log_exception, PROXY_PORT


class Root:
    def __init__(self, spotty_streamer: SpottyAudioStreamer):
        self.__spotty_streamer = spotty_streamer

    def set_notify_track_finished(self, func: Callable[[str], None]) -> None:
        self.__spotty_streamer.set_notify_track_finished(func)

    @cherrypy.expose
    def index(self):
        return "Server started"

    @cherrypy.expose
    def track(self, track_id, flt_duration_str):
        try:
            self.__spotty_streamer.set_track(track_id, float(flt_duration_str))

            # Check the sanity of the request.
            self.__check_request()

            # Response timeout must be at least the duration of the track read/write loop.
            # Checks for timeout and stops pushing audio to player if it occurs.
            cherrypy.response.timeout = int(
                math.ceil(self.__spotty_streamer.get_track_duration() * 1.5)
            )

            # Set the cherrypy headers.
            request_range = cherrypy.request.headers.get("Range", "")
            range_l, range_r = self.__set_cherrypy_headers(request_range)

            # If method was GET, then write the file content.
            if cherrypy.request.method.upper() == "GET":
                return self.__spotty_streamer.send_part_audio_stream(range_r - range_l, range_l)
        except Exception as exc:
            log_exception(exc, "Error in 'track'")

    track._cp_config = {"response.stream": True}

    @staticmethod
    def __check_request():
        method = cherrypy.request.method.upper()
        # headers = cherrypy.request.headers
        # Fail for other methods than get or head.
        if method not in ("GET", "HEAD"):
            raise cherrypy.HTTPError(405)
        # Error if the requester is not allowed.
        # For now this is a simple check just checking if the useragent matches Kodi.
        # user_agent = headers['User-Agent'].lower()
        # if not ("Kodi" in user_agent or "osmc" in user_agent):
        #     raise cherrypy.HTTPError(403)
        return method

    def __set_cherrypy_headers(self, request_range):
        if request_range and request_range != "bytes=0-":
            return self.__set_partial_cherrypy_headers()
        return self.__set_full_cherrypy_headers()

    def __set_partial_cherrypy_headers(self):
        # Partial request.
        cherrypy.response.status = "206 Partial Content"
        cherrypy.response.headers["Content-Type"] = "audio/x-wav"
        rng = cherrypy.request.headers["Range"].split("bytes=")[1].split("-")
        log_msg(f"Request header range: {cherrypy.request.headers['Range']}", xbmc.LOGDEBUG)
        range_l = int(rng[0])
        try:
            range_r = int(rng[1])
        except:
            range_r = self.__spotty_streamer.get_track_length()

        cherrypy.response.headers["Accept-Ranges"] = "bytes"
        cherrypy.response.headers["Content-Length"] = range_r - range_l
        cherrypy.response.headers[
            "Content-Range"
        ] = f"bytes {range_l}-{range_r}/{self.__spotty_streamer.get_track_length()}"
        log_msg(
            f"Partial request range: {cherrypy.response.headers['Content-Range']},"
            f" length: {cherrypy.response.headers['Content-Length']}",
            xbmc.LOGDEBUG,
        )

        return range_l, range_r

    def __set_full_cherrypy_headers(self):
        # Full file
        cherrypy.response.headers["Content-Type"] = "audio/x-wav"
        cherrypy.response.headers["Accept-Ranges"] = "bytes"
        cherrypy.response.headers["Content-Length"] = self.__spotty_streamer.get_track_length()
        log_msg(f"Full File. Size: {self.__spotty_streamer.get_track_length()}.", xbmc.LOGDEBUG)
        log_msg(f"Track ended?", xbmc.LOGDEBUG)

        return 0, self.__spotty_streamer.get_track_length()


class ProxyRunner(threading.Thread):
    def __init__(self, spotty_streamer: SpottyAudioStreamer):
        self.__root = Root(spotty_streamer)

        log = cherrypy.log
        log.screen = True
        # log.access_file = ADDON_DATA_PATH + "/cherrypy-access.log"
        # log.access_log.setLevel(logging.DEBUG)
        # log.error_file = ADDON_DATA_PATH + "/cherrypy-error.log"
        # log.error_log.setLevel(logging.DEBUG)

        cherrypy.config.update(
            {"server.socket_host": "127.0.0.1", "server.socket_port": PROXY_PORT}
        )
        self.__server = cherrypy.server.httpserver = CPHTTPServer(cherrypy.server)
        log_msg(f"Set cherrypy host, port to '{self.get_host()}:{self.get_port()}'.")
        if self.get_port() != PROXY_PORT:
            raise Exception(f"Wrong cherrypy port set: {self.get_port()} instead of {PROXY_PORT}.")
        threading.Thread.__init__(self)

    def run(self):
        log_msg("Running cherrypy quickstart.")
        conf = {"/": {}}
        cherrypy.quickstart(self.__root, "/", conf)

    def get_port(self):
        return self.__server.bind_addr[1]

    def get_host(self):
        return self.__server.bind_addr[0]

    def stop(self):
        log_msg("Running cherrypy engine exit.")
        cherrypy.engine.exit()
        self.join(0)
        del self.__root
        del self.__server
