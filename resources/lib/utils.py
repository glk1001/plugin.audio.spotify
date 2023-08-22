import inspect
import os
import platform
import signal
import unicodedata
from traceback import format_exception
from typing import Any, Dict, List, Tuple, Union

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
        if platform.system() != "Windows":
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def bytes_to_megabytes(byts: int) -> float:
    return (byts / 1024.0) / 1024.0


def get_chunks(data, chunk_size: int):
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


def cache_auth_token(auth_token: str) -> None:
    cache_value_in_kodi(KODI_PROPERTY_SPOTIFY_TOKEN, auth_token)


def get_cached_auth_token() -> str:
    return get_cached_value_from_kodi(KODI_PROPERTY_SPOTIFY_TOKEN)


def cache_value_in_kodi(kodi_property_id: str, value: Any):
    win = xbmcgui.Window(ADDON_WINDOW_ID)
    win.setProperty(kodi_property_id, value)


def get_cached_value_from_kodi(kodi_property_id: str, wait_ms: int = 500) -> Any:
    win = xbmcgui.Window(ADDON_WINDOW_ID)

    count = 10
    while count > 0:
        value = win.getProperty(kodi_property_id)
        if value:
            return value
        xbmc.sleep(wait_ms)
        count -= 1

    return None


def get_user_playlists(
    spotipy, limit: int = 50, offset: int = 0
) -> Tuple[List[Dict[str, Any]], List[str]]:
    userid = spotipy.me()["id"]
    playlists = spotipy.user_playlists(userid, limit=limit, offset=offset)

    own_playlists = []
    own_playlist_names = []
    for playlist in playlists["items"]:
        if playlist["owner"]["id"] == userid:
            own_playlists.append(playlist)
            own_playlist_names.append(playlist["name"])

    return own_playlists, own_playlist_names


def get_user_playlist_id(spotipy, playlist_name: str) -> Union[str, None]:
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
