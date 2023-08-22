import inspect
import math
import os
import signal
import unicodedata
from traceback import format_exception

import xbmc
import xbmcgui
import xbmcvfs
from xbmc import LOGDEBUG, LOGINFO, LOGERROR

DEBUG = True
PROXY_PORT = 52308

ADDON_ID = "plugin.audio.spotify"
ADDON_DATA_PATH = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}")
ADDON_WINDOW_ID = 10000

KODI_PROPERTY_SPOTIFY_TOKEN = "spotify-token"


def log_msg(msg: str, loglevel: int = LOGDEBUG, caller_name: str = "") -> None:
    if DEBUG and (loglevel == LOGDEBUG):
        loglevel = LOGINFO
    if not caller_name:
        caller_name = get_formatted_caller_name(inspect.stack()[1][1], inspect.stack()[1][3])

    xbmc.log(f"{ADDON_ID}:{caller_name}: {msg}", level=loglevel)


def log_exception(exc: Exception, exception_details: str) -> None:
    the_caller_name = get_formatted_caller_name(inspect.stack()[1][1], inspect.stack()[1][3])
    log_msg(" ".join(format_exception(exc)), loglevel=LOGERROR, caller_name=the_caller_name)
    log_msg(f"Exception --> {exception_details}.", loglevel=LOGERROR, caller_name=the_caller_name)


def get_formatted_caller_name(filename: str, function_name: str) -> str:
    return f"{os.path.splitext(os.path.basename(filename))[0]}:{function_name}"


def kill_process_by_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def bytes_to_megabytes(byts: int):
    return (byts / 1024.0) / 1024.0


def get_chunks(data, chunk_size):
    return [data[x : x + chunk_size] for x in range(0, len(data), chunk_size)]


def try_encode(text, encoding="utf-8"):
    try:
        return text.encode(encoding, "ignore")
    except UnicodeEncodeError:
        return text


def try_decode(text, encoding="utf-8"):
    try:
        return text.decode(encoding, "ignore")
    except UnicodeDecodeError:
        return text


def normalize_string(text):
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


def cache_auth_token(auth_token):
    cache_value_in_kodi(KODI_PROPERTY_SPOTIFY_TOKEN, auth_token)


def get_cached_auth_token():
    return get_cached_value_from_kodi(KODI_PROPERTY_SPOTIFY_TOKEN)


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
