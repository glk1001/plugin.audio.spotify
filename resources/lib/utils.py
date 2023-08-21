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
import time
from threading import Thread, Event
from traceback import format_exc

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from xbmc import LOGDEBUG, LOGINFO, LOGERROR

DEBUG = True
PROXY_PORT = 52308

ADDON_ID = "plugin.audio.spotify"
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}")
ADDON_WINDOW_ID = 10000

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

try:
    from multiprocessing.pool import ThreadPool

    SUPPORTS_POOL = True
except Exception:
    SUPPORTS_POOL = False


def log_msg(msg, loglevel=LOGDEBUG, caller_name=None):
    if isinstance(msg, str):
        msg = msg.encode("utf-8")
    if DEBUG and (loglevel == LOGDEBUG):
        loglevel = LOGINFO
    if not caller_name:
        caller_name = get_formatted_caller_name(inspect.stack()[1][1], inspect.stack()[1][3])

    xbmc.log(f"{ADDON_ID}:{caller_name} --> {msg}", level=loglevel)


def get_formatted_caller_name(filename, function_name):
    return f"{os.path.splitext(os.path.basename(filename))[0]}:{function_name}"


def log_exception(exception_details):
    """helper to properly log an exception"""
    the_caller_name = get_formatted_caller_name(inspect.stack()[1][1], inspect.stack()[1][3])
    log_msg(format_exc(), loglevel=LOGERROR, caller_name=the_caller_name)
    log_msg(f"Exception --> {exception_details}.", loglevel=LOGERROR, caller_name=the_caller_name)


def addon_setting(setting_name, set_value=None):
    """get/set addon setting"""
    addon = xbmcaddon.Addon(id=ADDON_ID)
    if not set_value:
        return addon.getSetting(setting_name)

    addon.setSetting(setting_name, set_value)


def kill_on_timeout(done, timeout, proc):
    if not done.wait(timeout):
        proc.kill()


def cache_value_in_kodi(kodi_property_id, value):
    win = xbmcgui.Window(ADDON_WINDOW_ID)
    win.setProperty(kodi_property_id, value)


def get_cached_value_from_kodi(kodi_property_id, wait_ms=500):
    win = xbmcgui.Window(ADDON_WINDOW_ID)

    count = 10
    while count > 0:
        value = win.getProperty(kodi_property_id)
        if value:
            return value
        xbmc.sleep(wait_ms)
        count -= 1

    return None


def cache_auth_token(auth_token):
    cache_value_in_kodi(KODI_PROPERTY_SPOTIFY_TOKEN, auth_token)


def get_cached_auth_token():
    return get_cached_value_from_kodi(KODI_PROPERTY_SPOTIFY_TOKEN)


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


def get_user_playlists(spotipy, limit=50, offset=0):
    userid = spotipy.me()["id"]
    playlists = spotipy.user_playlists(userid, limit=limit, offset=offset)

    own_playlists = []
    own_playlist_names = []
    for playlist in playlists["items"]:
        if playlist["owner"]["id"] == userid:
            own_playlists.append(playlist)
            own_playlist_names.append(playlist["name"])

    return own_playlists, own_playlist_names


def get_user_playlist_id(spotipy, playlist_name):
    offset = 0
    while True:
        own_playlists, own_playlist_names = get_user_playlists(spotipy, limit=50, offset=offset)
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
    # This doesn't make sense - track["track"] is a bool
    # if "track" in track:
    #     track = track["track"]
    if track.get("images"):
        thumb = track["images"][0]["url"]
    elif track["album"].get("images"):
        thumb = track["album"]["images"][0]["url"]
    else:
        thumb = "DefaultMusicSongs"

    duration = track["duration_ms"] / 1000

    url = f"http://localhost:{PROXY_PORT}/track/{track['id']}/{duration}"

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
