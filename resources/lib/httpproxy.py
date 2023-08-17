# -*- coding: utf-8 -*-
import json
import math
import struct
import threading
import time
from io import BytesIO

# Would like to do the following submodule imports, but they won't work.
# See the comment in 'lib/__init__.py':
# 'from deps import cherrypy'
# 'from deps.cherrypy._cpnative_server import CPHTTPServer'
import cherrypy
import spotipy
import xbmc
import xbmcaddon
import xbmcgui
from cherrypy._cpnative_server import CPHTTPServer

import utils
from utils import log_msg, log_exception, PROXY_PORT, ADDON_ID, ADDON_DATA_PATH

LIBRESPOT_INITIAL_VOLUME = "50"
SPOTTY_AUDIO_CHUNK_SIZE = 524288
SPOTIFY_TRACK_PREFIX = "spotify:track:"

SAVE_TO_RECENTLY_PLAYED_FILE = True
if SAVE_TO_RECENTLY_PLAYED_FILE:
    import os

    ADDON_OUTPUT_PATH = f"{ADDON_DATA_PATH}/output"


class Root:
    def __init__(self, spotty):
        self.spotty = spotty
        self.track_id: str = ""
        self.track_duration: int = 0
        self.wav_header: bytes = bytes()
        self.track_length = 0

        self.requested_kodi_volume = self.get_spotify_volume_setting()
        self.kodi_volume_has_been_reset = False
        self.saved_volume = -1

        self.spotipy = None
        self.win = xbmcgui.Window(10000)
        self.my_recently_played_playlist_name = self.get_my_recently_played_playlist_name()
        self.my_recently_played_playlist_id = None

        if SAVE_TO_RECENTLY_PLAYED_FILE:
            os.makedirs(ADDON_OUTPUT_PATH, exist_ok=True)
            timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
            self.recently_played_file = f"{ADDON_OUTPUT_PATH}/recently_played_{timestamp}.txt"

    def set_track(self, track_id: str, track_duration: float) -> None:
        self.track_id = track_id
        self.track_duration = int(track_duration)
        self.wav_header, self.track_length = self.create_wav_header()

    @staticmethod
    def get_spotify_volume_setting():
        requested_kodi_volume = xbmcaddon.Addon(id=ADDON_ID).getSetting("initial_volume")
        if not requested_kodi_volume:
            return -1
        requested_kodi_volume = int(requested_kodi_volume)
        if (requested_kodi_volume < -1) or (requested_kodi_volume > 100):
            raise Exception(
                f'Invalid initial volume "{requested_kodi_volume}".'
                f" Must in the range [-1, 100]."
            )
        return int(requested_kodi_volume)

    @staticmethod
    def get_current_playback_volume():
        volume_query = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "Application.GetProperties",
            "params": {"properties": ["volume", "muted"]},
        }
        result = xbmc.executeJSONRPC(json.dumps(volume_query))
        result = json.loads(result)
        result = result.get("result")
        return result["volume"]

    @staticmethod
    def set_volume(percent_value):
        xbmc.executeJSONRPC(
            f'{{"jsonrpc":"2.0","method":"Application.SetVolume",'
            f'"id":1,"params":{{"volume": {percent_value}}}}}'
        )

    def reset_kodi_volume(self):
        if self.kodi_volume_has_been_reset or self.requested_kodi_volume == -1:
            return

        self.set_volume(self.requested_kodi_volume)
        time.sleep(0.5)
        if self.requested_kodi_volume != self.get_current_playback_volume():
            raise Exception(
                f'Error: Could not set spotify volume to "{self.requested_kodi_volume}".'
            )
        self.kodi_volume_has_been_reset = True
        log_msg(
            f"Saved volume: {self.saved_volume}%,"
            f" new spotify volume: {self.requested_kodi_volume}%.",
            xbmc.LOGDEBUG,
        )

    def reset_volume_to_saved(self):
        if not self.kodi_volume_has_been_reset:
            return

        time.sleep(0.2)
        self.set_volume(self.saved_volume)
        self.kodi_volume_has_been_reset = False
        log_msg(f"Reset volume to saved volume: {self.saved_volume}%.", xbmc.LOGDEBUG)

    if SAVE_TO_RECENTLY_PLAYED_FILE:

        def save_currently_playing_track_to_recently_played(self, track_id):
            if not xbmc.Player().isPlaying():
                log_msg(f"Player not active. Not saving track to recently played.", xbmc.LOGWARNING)
                return

            if self.my_recently_played_playlist_name:
                if not self.my_recently_played_playlist_id:
                    self.set_my_recently_played_playlist_id()
                self.spotipy.playlist_add_items(self.my_recently_played_playlist_id, [track_id])
                log_msg(
                    f"Saved track to '{self.my_recently_played_playlist_name}' playlist.",
                    xbmc.LOGDEBUG,
                )

            log_msg("Getting music info tag of currently playing item.", xbmc.LOGDEBUG)
            info_tag = xbmc.Player().getPlayingItem().getMusicInfoTag()
            artist = str(info_tag.getArtist())
            title = str(info_tag.getTitle())
            track_name = f"{artist} ---- {title}"

            log_msg(f"Saving track '{track_name}' to '{self.recently_played_file}'.", xbmc.LOGDEBUG)
            try:
                with open(self.recently_played_file, "a", encoding="utf-8") as f:
                    f.write(f"{track_name}\n")
            except Exception as ex:
                log_msg(f"Error saving track: {ex}'.", xbmc.LOGERROR)

            log_msg(f"Saved track '{track_name}' to '{self.recently_played_file}'.", xbmc.LOGDEBUG)

    @staticmethod
    def get_my_recently_played_playlist_name():
        return xbmcaddon.Addon(id=ADDON_ID).getSetting("my_recently_played_playlist_name")

    def set_my_recently_played_playlist_id(self):
        self.spotipy = spotipy.Spotify(auth=utils.get_authkey_from_kodi())
        userid = self.win.getProperty(utils.KODI_PROPERTY_SPOTIFY_USERNAME)
        log_msg(
            f"Getting id for '{self.my_recently_played_playlist_name}' playlist.", xbmc.LOGDEBUG
        )
        self.my_recently_played_playlist_id = utils.get_user_playlist_id(
            self.spotipy, userid, self.my_recently_played_playlist_name
        )

        if not self.my_recently_played_playlist_id:
            log_msg(
                f"Did not find a '{self.my_recently_played_playlist_name}' playlist."
                " Creating one now.",
                xbmc.LOGINFO,
            )
            playlist = self.spotipy.user_playlist_create(
                userid, self.my_recently_played_playlist_name, False
            )
            self.my_recently_played_playlist_id = playlist["id"]

            if not self.my_recently_played_playlist_id:
                raise Exception(
                    f"Could not create a '{self.my_recently_played_playlist_name}' playlist."
                )

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
                self.save_currently_playing_track_to_recently_played(track_id)

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

    def _set_cherrypy_headers(self, request_range):
        if request_range and request_range != "bytes=0-":
            return self._set_partial_cherrypy_headers()
        return self._set_full_cherrypy_headers()

    @staticmethod
    def _set_partial_cherrypy_headers():
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
        self.reset_volume_to_saved()

        return 0, self.track_length

    def send_audio_stream(self, range_len, range_l):
        """Chunked transfer of audio data from spotty binary"""
        self.spotty.kill_spotty()

        spotty_bin = None
        bytes_written = 0

        try:
            self.reset_kodi_volume()

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
