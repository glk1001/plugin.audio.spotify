# -*- coding: utf-8 -*-
import math
import struct
import threading
from io import BytesIO

# Would like to do the following submodule imports, but they won't work.
# See the comment in 'lib/__init__.py':
# 'from deps import cherrypy'
# 'from deps.cherrypy._cpnative_server import CPHTTPServer'
import cherrypy
import xbmc
from cherrypy._cpnative_server import CPHTTPServer

from utils import log_msg, log_exception, PROXY_PORT
from save_recently_played import SaveRecentlyPlayed

LIBRESPOT_INITIAL_VOLUME = "50"
SPOTTY_AUDIO_CHUNK_SIZE = 524288
SPOTIFY_TRACK_PREFIX = "spotify:track:"

SAVE_TO_RECENTLY_PLAYED_FILE = True


class Root:
    def __init__(self, spotty):
        self.spotty = spotty
        self.track_id: str = ""
        self.track_duration: int = 0
        self.wav_header: bytes = bytes()
        self.track_length = 0

        if SAVE_TO_RECENTLY_PLAYED_FILE:
            self.save_recently_played = SaveRecentlyPlayed()

    def set_track(self, track_id: str, track_duration: float) -> None:
        self.track_id = track_id
        self.track_duration = int(track_duration)
        self.wav_header, self.track_length = self.create_wav_header()

    @cherrypy.expose
    def index(self):
        return "Server started"

    @cherrypy.expose
    def track(self, track_id, flt_duration_str):
        try:
            self.set_track(track_id, float(flt_duration_str))

            # Check the sanity of the request.
            self._check_request()

            if SAVE_TO_RECENTLY_PLAYED_FILE:
                self.save_recently_played.save_currently_playing_track(track_id)

            # Response timeout must be at least the duration of the track read/write loop.
            # Checks for timeout and stops pushing audio to player if it occurs.
            cherrypy.response.timeout = int(math.ceil(self.track_duration * 1.5))

            # Set the cherrypy headers.
            request_range = cherrypy.request.headers.get("Range", "")
            range_l, range_r = self._set_cherrypy_headers(request_range)

            # If method was GET, then write the file content.
            if cherrypy.request.method.upper() == "GET":
                return self.send_audio_stream(range_r - range_l, range_l)
        except:
            log_exception("Error in 'track'")

    track._cp_config = {"response.stream": True}

    @staticmethod
    def _check_request():
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

    def _set_cherrypy_headers(self, request_range):
        if request_range and request_range != "bytes=0-":
            return self._set_partial_cherrypy_headers()
        return self._set_full_cherrypy_headers()

    def _set_partial_cherrypy_headers(self):
        # Partial request.
        cherrypy.response.status = "206 Partial Content"
        cherrypy.response.headers["Content-Type"] = "audio/x-wav"
        rng = cherrypy.request.headers["Range"].split("bytes=")[1].split("-")
        log_msg(f"Request header range: {cherrypy.request.headers['Range']}", xbmc.LOGDEBUG)
        range_l = int(rng[0])
        try:
            range_r = int(rng[1])
        except:
            range_r = self.track_length

        cherrypy.response.headers["Accept-Ranges"] = "bytes"
        cherrypy.response.headers["Content-Length"] = range_r - range_l
        cherrypy.response.headers[
            "Content-Range"
        ] = f"bytes {range_l}-{range_r}/{self.track_length}"
        log_msg(
            f"Partial request range: {cherrypy.response.headers['Content-Range']},"
            f" length: {cherrypy.response.headers['Content-Length']}",
            xbmc.LOGDEBUG,
        )

        return range_l, range_r

    def _set_full_cherrypy_headers(self):
        # Full file
        cherrypy.response.headers["Content-Type"] = "audio/x-wav"
        cherrypy.response.headers["Accept-Ranges"] = "bytes"
        cherrypy.response.headers["Content-Length"] = self.track_length
        log_msg(f"Full File. Size: {self.track_length}.", xbmc.LOGDEBUG)
        log_msg(f"Track ended?", xbmc.LOGDEBUG)

        return 0, self.track_length

    def send_audio_stream(self, range_len, range_l):
        """Chunked transfer of audio data from spotty binary"""
        self.spotty.kill_spotty()

        spotty_bin = None
        bytes_written = 0

        try:
            log_msg(f"Start transfer for track {self.track_id} - range: {range_l}", xbmc.LOGDEBUG)

            # Write wave header.
            # Only count bytes actually from the spotify stream.
            if not range_l:
                yield self.wav_header
                bytes_written = len(self.wav_header)

            # Get data from spotty stdout and append to our buffer.
            track_id_uri = SPOTIFY_TRACK_PREFIX + self.track_id
            args = [
                "--name",
                "temp",
                "--enable-volume-normalisation",
                "--normalisation-gain-type",
                "track",
                "--initial-volume",
                LIBRESPOT_INITIAL_VOLUME,
                "--single-track",
                track_id_uri,
            ]
            spotty_bin = self.spotty.run_spotty(args, use_creds=True)
            if not spotty_bin.returncode:
                log_msg(f"returncode: {spotty_bin.returncode}", xbmc.LOGDEBUG)

            log_msg(f"Reading track uri: {track_id_uri}, length = {range_len}", xbmc.LOGDEBUG)

            # Ignore the first x bytes to match the range request.
            if range_l:
                spotty_bin.stdout.read(range_l)

            # Loop as long as there's something to output.
            while bytes_written < range_len:
                frame = spotty_bin.stdout.read(SPOTTY_AUDIO_CHUNK_SIZE)
                if not frame:
                    log_msg("Nothing read from stdout.", xbmc.LOGDEBUG)
                    break
                bytes_written += len(frame)
                log_msg(
                    f"Continuing transfer for track {self.track_id} - bytes written = {bytes_written}",
                    xbmc.LOGDEBUG,
                )
                yield frame

            log_msg(
                f"FINISHED transfer for track {self.track_id}"
                f" - range {range_l} - bytes written {bytes_written}.",
                xbmc.LOGDEBUG,
            )
        except Exception:
            log_msg(
                "EXCEPTION FINISH transfer for track {track_id}"
                f" - range {range_l} - bytes written {bytes_written}.",
                xbmc.LOGERROR,
            )
            log_exception("Error with track transfer")
        finally:
            # Make sure spotty always gets terminated.
            if spotty_bin is not None:
                log_msg("Killing spotty.")
                spotty_bin.terminate()
                spotty_bin.communicate()
                self.spotty.kill_spotty()

    def create_wav_header(self):
        """generate a wave header for the stream"""
        try:
            log_msg(f"Start getting wave header. duration = {self.track_duration}", xbmc.LOGDEBUG)
            file = BytesIO()
            num_samples = 44100 * self.track_duration
            channels = 2
            sample_rate = 44100
            bits_per_sample = 16

            # Generate format chunk.
            format_chunk_spec = "<4sLHHLLHH"
            format_chunk = struct.pack(
                format_chunk_spec,
                "fmt ".encode(encoding="UTF-8"),  # Chunk id
                16,  # Size of this chunk (excluding chunk id and this field)
                1,  # Audio format, 1 for PCM
                channels,  # Number of channels
                sample_rate,  # Samplerate, 44100, 48000, etc.
                sample_rate * channels * (bits_per_sample // 8),  # Byterate
                channels * (bits_per_sample // 8),  # Blockalign
                bits_per_sample,  # 16 bits for two byte samples, etc.  => A METTRE A JOUR - POUR TEST
            )

            # Generate data chunk.
            data_chunk_spec = "<4sL"
            data_size = num_samples * channels * (bits_per_sample / 8)
            data_chunk = struct.pack(
                data_chunk_spec,
                "data".encode(encoding="UTF-8"),  # Chunk id
                int(data_size),  # Chunk size (excluding chunk id and this field)
            )
            sum_items = [
                # "WAVE" string following size field
                4,
                # "fmt " + chunk size field + chunk size
                struct.calcsize(format_chunk_spec),
                # Size of data chunk spec + data size
                struct.calcsize(data_chunk_spec) + data_size,
            ]

            # Generate main header.
            all_chunks_size = int(sum(sum_items))
            main_header_spec = "<4sL4s"
            main_header = struct.pack(
                main_header_spec,
                "RIFF".encode(encoding="UTF-8"),
                all_chunks_size,
                "WAVE".encode(encoding="UTF-8"),
            )

            # Write all the contents in.
            file.write(main_header)
            file.write(format_chunk)
            file.write(data_chunk)

            return file.getvalue(), all_chunks_size + 8

        except Exception:
            log_exception("Failed to create wave header.")


class ProxyRunner(threading.Thread):
    def __init__(self, spotty):
        self.__root = Root(spotty)

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
