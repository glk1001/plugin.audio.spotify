#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
    plugin.audio.spotify
    Spotify player for Kodi
    utils.py
    Various helper methods
"""

import inspect
import math
import os
import platform
import stat
import struct
import subprocess
import time
from io import BytesIO
from threading import Thread, Event
from traceback import format_exc

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

DEBUG = True
PROXY_PORT = 52308

ADDON_ID = "plugin.audio.spotify"
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}")

SPOTTY_SCOPE = [
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-modify-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-follow-modify",
    "user-follow-read",
    "user-library-read",
    "user-library-modify",
    "user-read-private",
    "user-read-email",
    "user-read-birthdate",
    "user-top-read",
]
CLIENT_ID = "2eb96f9b37494be1824999d58028a305"
CLIENT_SECRET = "038ec3b4555f46eab1169134985b9013"

KODI_PROPERTY_SPOTIFY_TOKEN = "spotify-token"
KODI_PROPERTY_SPOTIFY_USERNAME = "spotify-username"
KODI_PROPERTY_SPOTIFY_COUNTRY = "spotify - country"

try:
    from multiprocessing.pool import ThreadPool

    SUPPORTS_POOL = True
except Exception:
    SUPPORTS_POOL = False


def log_msg(msg, loglevel=xbmc.LOGDEBUG, caller_name=None):
    if isinstance(msg, str):
        msg = msg.encode("utf-8")
    if DEBUG and (loglevel == xbmc.LOGDEBUG):
        loglevel = xbmc.LOGINFO
    if not caller_name:
        caller_name = get_formatted_caller_name(inspect.stack()[1][1], inspect.stack()[1][3])

    xbmc.log(f"{ADDON_ID}:{caller_name} --> {msg}", level=loglevel)


def get_formatted_caller_name(filename, function_name):
    return f"{os.path.splitext(os.path.basename(filename))[0]}:{function_name}"


# def get_log_level_str(loglevel):
#     match loglevel:
#         case xbmc.LOGDEBUG:
#             return "debug"
#         case xbmc.LOGINFO:
#             return "info"
#         case xbmc.LOGWARNING:
#             return "warn"
#         case xbmc.LOGERROR:
#             return "error"
#         case xbmc.LOGFATAL:
#             return "fatal"
#         case xbmc.LOGNONE:
#             return "none"


def log_exception(exception_details):
    """helper to properly log an exception"""
    the_caller_name = get_formatted_caller_name(inspect.stack()[1][1], inspect.stack()[1][3])
    log_msg(format_exc(), loglevel=xbmc.LOGERROR, caller_name=the_caller_name)
    log_msg(
        f"Exception --> {exception_details}.", loglevel=xbmc.LOGERROR, caller_name=the_caller_name
    )


def addon_setting(setting_name, set_value=None):
    """get/set addon setting"""
    addon = xbmcaddon.Addon(id=ADDON_ID)
    if not set_value:
        return addon.getSetting(setting_name)

    addon.setSetting(setting_name, set_value)


def kill_on_timeout(done, timeout, proc):
    if not done.wait(timeout):
        proc.kill()


def get_authkey_from_kodi():
    win = xbmcgui.Window(10000)
    auth_token = None

    count = 10
    while not auth_token and count:
        auth_token = win.getProperty(KODI_PROPERTY_SPOTIFY_TOKEN)
        count -= 1
        if not auth_token:
            xbmc.sleep(500)

    return auth_token


def get_token(spotty):
    # Get authentication token for api - prefer cached version.
    token_info = None
    try:
        if spotty.playback_supported:
            # Try to get a token with spotty.
            token_info = request_token_spotty(spotty, use_creds=False)
            if token_info:
                # Save current username in cached spotty creds.
                spotty.get_username()
            if not token_info:
                token_info = request_token_spotty(spotty, use_creds=True)
    except Exception:
        log_exception("Spotify get token error")
        token_info = None

    if not token_info:
        log_msg(
            "Couldn't request authentication token. Username/password error?"
            " If you're using a facebook account with Spotify,"
            " make sure to generate a device account/password in the Spotify accountdetails."
        )

    return token_info


def request_token_spotty(spotty, use_creds=True):
    """request token by using the spotty binary"""
    if not spotty.playback_supported:
        return None

    token_info = None

    try:
        args = [
            "-t",
            "--client-id",
            CLIENT_ID,
            "--scope",
            ",".join(SPOTTY_SCOPE),
            "-n",
            "temp-spotty",
        ]
        spotty = spotty.run_spotty(arguments=args, use_creds=use_creds)

        done = Event()
        watcher = Thread(target=kill_on_timeout, args=(done, 5, spotty))
        watcher.daemon = True
        watcher.start()

        stdout, stderr = spotty.communicate()
        done.set()

        log_msg(f"request_token_spotty stdout: {stdout}")
        result = None
        for line in stdout.split():
            line = line.strip()
            if line.startswith(b'{"accessToken"'):
                result = eval(line)

        # Transform token info to spotipy compatible format.
        if result:
            token_info = {
                "access_token": result["accessToken"],
                "expires_in": result["expiresIn"],
                "expires_at": int(time.time()) + result["expiresIn"],
                "refresh_token": result["accessToken"],
            }
    except Exception:
        log_exception("Spotify request token error")

    return token_info


def create_wave_header(duration):
    """generate a wave header for the stream"""
    file = BytesIO()
    num_samples = 44100 * duration
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


def process_method_on_list(method_to_run, items):
    """helper method that processes a method on each list item
    with pooling if the system supports it"""
    all_items = []

    if not SUPPORTS_POOL:
        all_items = [method_to_run(item) for item in items]
    else:
        pool = ThreadPool()
        try:
            all_items = pool.map(method_to_run, items)
        except Exception:
            # Catch exception to prevent threadpool running forever.
            log_exception(f"Error in '{method_to_run}'")
        pool.close()
        pool.join()

    all_items = [f for f in all_items if f]

    return all_items


def get_user_playlists(spotipy, userid, limit=50, offset=0):
    playlists = spotipy.user_playlists(userid, limit=limit, offset=offset)

    own_playlists = []
    own_playlist_names = []
    for playlist in playlists["items"]:
        if playlist["owner"]["id"] == userid:
            own_playlists.append(playlist)
            own_playlist_names.append(playlist["name"])

    return own_playlists, own_playlist_names


def get_user_playlist_id(spotipy, userid, playlist_name):
    offset = 0
    while True:
        own_playlists, own_playlist_names = get_user_playlists(
            spotipy, userid, limit=50, offset=offset
        )
        if len(own_playlists) == 0:
            break
        for playlist in own_playlists:
            if playlist_name == playlist["name"]:
                return playlist["id"]
        offset += 50

    return None


def get_track_rating(popularity):
    if not popularity:
        return 0

    return int(math.ceil(popularity * 6 / 100.0)) - 1


def parse_spotify_track(track, is_album_track=True):
    if "track" in track:
        track = track["track"]
    if track.get("images"):
        thumb = track["images"][0]["url"]
    elif track["album"].get("images"):
        thumb = track["album"]["images"][0]["url"]
    else:
        thumb = "DefaultMusicSongs"

    duration = track["duration_ms"] / 1000

    url = "http://localhost:%s/track/%s/%s" % (PROXY_PORT, track["id"], duration)

    info_labels = {
        "title": track["name"],
        "genre": " / ".join(track["album"].get("genres", [])),
        "year": int(track["album"].get("release_date", "0").split("-")[0]),
        "album": track["album"]["name"],
        "artist": " / ".join([artist["name"] for artist in track["artists"]]),
        "rating": str(get_track_rating(track["popularity"])),
        "duration": duration,
    }

    li = xbmcgui.ListItem(track["name"], path=url, offscreen=True)
    if is_album_track:
        info_labels["tracknumber"] = track["track_number"]
        info_labels["discnumber"] = track["disc_number"]
    li.setArt({"thumb": thumb})
    li.setInfo(type="Music", infoLabels=info_labels)
    li.setProperty("spotifytrackid", track["id"])
    li.setContentLookup(False)
    li.setProperty("do_not_analyze", "true")
    li.setMimeType("audio/wave")

    return url, li


def get_chunks(data, chunk_size):
    return [data[x : x + chunk_size] for x in range(0, len(data), chunk_size)]


def try_encode(text, encoding="utf-8"):
    try:
        return text.encode(encoding, "ignore")
    except:
        return text


def try_decode(text, encoding="utf-8"):
    try:
        return text.decode(encoding, "ignore")
    except:
        return text


def normalize_string(text):
    import unicodedata

    text = text.replace(":", "")
    text = text.replace("/", "-")
    text = text.replace("\\", "-")
    text = text.replace("<", "")
    text = text.replace(">", "")
    text = text.replace("*", "")
    text = text.replace("?", "")
    text = text.replace("|", "")
    text = text.replace("(", "")
    text = text.replace(")", "")
    text = text.replace('"', "")
    text = text.strip()
    text = text.rstrip(".")
    text = unicodedata.normalize("NFKD", try_decode(text))

    return text


def get_player_name():
    player_name = xbmc.getInfoLabel("System.FriendlyName")
    if player_name == "Kodi":
        import socket

        player_name = "Kodi - %s" % socket.gethostname()
    return player_name


class Spotty(object):
    """
    Spotty is wrapped into a separate class to store common properties.
    This is done to prevent hitting a kodi issue where calling one of the
    infolabel methods at playback time causes a crash of the playback.
    """

    def __init__(self):
        self.__cache_path = f"{ADDON_DATA_PATH}/spotty-cache"
        self.player_name = get_player_name()
        self.__spotty_binary = self.get_spotty_binary()

        if self.__spotty_binary and self.test_spotty(self.__spotty_binary):
            self.playback_supported = True
            xbmc.executebuiltin("SetProperty(spotify.supportsplayback, true, Home)")
        else:
            self.playback_supported = False
            log_msg(
                "Error while verifying spotty. Local playback is disabled.", loglevel=xbmc.LOGERROR
            )

    @staticmethod
    def test_spotty(binary_path):
        """self-test spotty binary"""
        try:
            st = os.stat(binary_path)
            os.chmod(binary_path, st.st_mode | stat.S_IEXEC)
            args = [binary_path, "-n", "selftest", "--disable-discovery", "-x", "-v"]
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            spotty = subprocess.Popen(
                args,
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )

            stdout, stderr = spotty.communicate()

            log_msg(stdout)

            if "ok spotty".encode(encoding="UTF-8") in stdout:
                return True

            if xbmc.getCondVisibility("System.Platform.Windows"):
                log_msg(
                    "Unable to initialize spotty binary for playback."
                    "Make sure you have the VC++ 2015 runtime installed.",
                    xbmc.LOGERROR,
                )

        except Exception:
            log_exception("Test spotty binary error")

        return False

    def run_spotty(self, arguments=None, use_creds=False, ap_port="54443"):
        """on supported platforms we include the spotty binary"""
        try:
            # os.environ["RUST_LOG"] = "debug"
            args = [
                self.__spotty_binary,
                "-c",
                self.__cache_path,
                "-b",
                "320",
                "-v",
                "--enable-audio-cache",
                "--ap-port",
                ap_port,
            ]

            if arguments:
                args += arguments
            if "-n" not in args:
                args += ["-n", self.player_name]

            loggable_args = args.copy()

            if use_creds:
                # Use username/password login for spotty.
                addon = xbmcaddon.Addon(id=ADDON_ID)
                username = addon.getSetting("username")
                password = addon.getSetting("password")
                del addon
                if username and password:
                    args += ["-u", username, "-p", password]
                    loggable_args += ["-u", username, "-p", "****"]

            log_msg("run_spotty args: %s" % " ".join(loggable_args))

            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            return subprocess.Popen(
                args, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        except Exception:
            log_exception("Run spotty error")

        return None

    def kill_spotty(self):
        """make sure we don't have any (remaining) spotty processes running before we start one"""
        if xbmc.getCondVisibility("System.Platform.Windows"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(["taskkill", "/IM", "spotty.exe"], startupinfo=startupinfo, shell=True)
        else:
            if self.__spotty_binary is not None:
                sp_binary_file = os.path.basename(self.__spotty_binary)
                os.system("killall " + sp_binary_file)

    def get_spotty_binary(self):
        """find the correct spotty binary belonging to the platform"""
        sp_binary = None
        if xbmc.getCondVisibility("System.Platform.Windows"):
            sp_binary = os.path.join(
                os.path.dirname(__file__), "deps/spotty", "windows", "spotty.exe"
            )
        elif xbmc.getCondVisibility("System.Platform.OSX"):
            sp_binary = os.path.join(os.path.dirname(__file__), "deps/spotty", "macos", "spotty")
        elif xbmc.getCondVisibility("System.Platform.Linux + !System.Platform.Android"):
            architecture = platform.machine()
            log_msg(f"Reported architecture: '{architecture}'.")
            if architecture.startswith("AMD64") or architecture.startswith("x86_64"):
                # Generic linux x86_64 binary.
                sp_binary = os.path.join(
                    os.path.dirname(__file__), "deps/spotty", "x86-linux", "spotty-x86_64"
                )
            else:
                # When we're unsure about the platform/cpu, try by testing to get
                # the correct binary path.
                paths = [
                    os.path.join(
                        os.path.dirname(__file__), "deps/spotty", "arm-linux", "spotty-hf"
                    ),
                    os.path.join(os.path.dirname(__file__), "deps/spotty", "x86-linux", "spotty"),
                ]
                for binary_path in paths:
                    if self.test_spotty(binary_path):
                        sp_binary = binary_path
                        break

        if not sp_binary:
            log_msg(
                "Spotty: failed to detect architecture or platform not supported!"
                " Local playback will not be available.",
                loglevel=xbmc.LOGERROR,
            )
            return None

        st = os.stat(sp_binary)
        os.chmod(sp_binary, st.st_mode | stat.S_IEXEC)
        log_msg(f"Spotty architecture detected. Using spotty binary '{sp_binary}'.")

        return sp_binary

    @staticmethod
    def get_username():
        """obtain/check (last) username of the credentials obtained by spotify connect"""
        username = ""

        cred_file = xbmcvfs.translatePath(f"{ADDON_DATA_PATH}/credentials.json")

        if xbmcvfs.exists(cred_file):
            with open(cred_file) as cred_file:
                data = cred_file.read()
                data = eval(data)
                username = data["username"]

        addon_setting("connect_username", username)

        return username
