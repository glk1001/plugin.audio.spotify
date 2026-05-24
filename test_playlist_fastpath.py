import os
import sys
import types
import unittest


REPO_ROOT = os.path.dirname(__file__)
LIB_DIR = os.path.join(REPO_ROOT, "resources", "lib")


class FakeAddon:
    def getLocalizedString(self, string_id):
        return f"str-{string_id}"

    def getAddonInfo(self, key):
        return "SpotifyKodiConnect"

    def getSetting(self, key):
        return ""

    def setSetting(self, key, value):
        pass


class FakeWindow:
    def __init__(self, window_id=None):
        self.properties = {}

    def getProperty(self, key):
        return self.properties.get(key, "")

    def setProperty(self, key, value):
        self.properties[key] = value

    def clearProperty(self, key):
        self.properties.pop(key, None)


class FakeMusicInfoTag:
    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


class FakeListItem:
    def __init__(self, label="", path=None, offscreen=False):
        self.label = label
        self.path = path
        self.context_items = []
        self.properties = {}

    def getMusicInfoTag(self):
        return FakeMusicInfoTag()

    def setProperty(self, key, value):
        self.properties[key] = value

    def setArt(self, art):
        self.art = art

    def setContentLookup(self, value):
        self.content_lookup = value

    def addContextMenuItems(self, items, replaceItems=False):
        self.context_items.extend(items or [])

    def setMimeType(self, mime_type):
        self.mime_type = mime_type


class FakeMonitor:
    def abortRequested(self):
        return False


class RecordingPlaylist:
    instances = []

    def __init__(self, playlist_id):
        self.playlist_id = playlist_id
        self.items = []
        RecordingPlaylist.instances.append(self)

    def clear(self):
        self.items.clear()

    def add(self, url, listitem):
        self.items.append((url, listitem))


class RecordingPlayer:
    events = []

    def play(self, playlist):
        RecordingPlayer.events.append("play")


class DeferredThread:
    started_targets = []

    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        if getattr(self.target, "__name__", "") == "add_remaining":
            DeferredThread.started_targets.append(self.target)
            return
        self.target()

    def join(self):
        pass


class FakeCache:
    def get(self, key, checksum=None):
        return None

    def set(self, key, value, checksum=None):
        pass


def install_kodi_stubs():
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG = 0
    xbmc.LOGINFO = 1
    xbmc.LOGWARNING = 2
    xbmc.LOGERROR = 3
    xbmc.Monitor = FakeMonitor
    xbmc.PlayList = RecordingPlaylist
    xbmc.Player = RecordingPlayer
    xbmc.sleep = lambda millis: None
    xbmc.getLocalizedString = lambda string_id: f"kodi-{string_id}"
    xbmc.executebuiltin = lambda command: None
    xbmc.log = lambda message, level=0: None
    sys.modules["xbmc"] = xbmc

    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = lambda id=None: FakeAddon()
    sys.modules["xbmcaddon"] = xbmcaddon

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.Window = FakeWindow
    xbmcgui.ListItem = FakeListItem
    xbmcgui.Dialog = lambda: None
    sys.modules["xbmcgui"] = xbmcgui

    xbmcplugin = types.ModuleType("xbmcplugin")
    xbmcplugin.SORT_METHOD_UNSORTED = 0
    xbmcplugin.addDirectoryItems = lambda *args, **kwargs: None
    xbmcplugin.addDirectoryItem = lambda *args, **kwargs: None
    xbmcplugin.addSortMethod = lambda *args, **kwargs: None
    xbmcplugin.endOfDirectory = lambda *args, **kwargs: None
    xbmcplugin.setContent = lambda *args, **kwargs: None
    xbmcplugin.setPluginCategory = lambda *args, **kwargs: None
    xbmcplugin.setProperty = lambda *args, **kwargs: None
    sys.modules["xbmcplugin"] = xbmcplugin

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda path: path
    sys.modules["xbmcvfs"] = xbmcvfs

    simplecache = types.ModuleType("simplecache")
    simplecache.SimpleCache = lambda addon_id=None: FakeCache()
    sys.modules["simplecache"] = simplecache

    spotipy = types.ModuleType("spotipy")
    spotipy.Spotify = lambda auth=None: None
    sys.modules["spotipy"] = spotipy

    spotty = types.ModuleType("spotty")
    spotty.Spotty = object
    spotty.get_spotty = lambda helper: None
    sys.modules["spotty"] = spotty

    spotty_auth = types.ModuleType("spotty_auth")
    spotty_auth.SpottyAuth = object
    sys.modules["spotty_auth"] = spotty_auth

    spotty_helper = types.ModuleType("spotty_helper")
    spotty_helper.SpottyHelper = object
    sys.modules["spotty_helper"] = spotty_helper


def import_plugin_content():
    install_kodi_stubs()
    if LIB_DIR not in sys.path:
        sys.path.insert(0, LIB_DIR)
    sys.argv = ["plugin://plugin.audio.spotifykodiconnect", "1", "?"]
    sys.modules.pop("plugin_content", None)
    import plugin_content

    plugin_content.threading.Thread = DeferredThread
    return plugin_content


def spotify_track(index):
    return {
        "id": f"track-{index}",
        "uri": f"spotify:track:track-{index}",
        "name": f"Track {index}",
        "duration_ms": 180000,
        "popularity": 50,
        "artists": [{"id": f"artist-{index}", "name": f"Artist {index}"}],
        "album": {
            "name": "Album",
            "images": [],
            "album_type": "album",
            "release_date": "2024-01-01",
            "genres": [],
        },
    }


class FakeSpotify:
    def __init__(self, events, total=75):
        self.events = events
        self.total = total
        self.saved_track_calls = 0
        self.saved_album_calls = 0
        self.followed_artist_calls = 0
        self.artist_calls = 0

    def playlist(self, playlist_id, fields="", market=None):
        return {
            "id": playlist_id,
            "name": "Fast Playlist",
            "owner": {"id": "owner"},
            "snapshot_id": "snapshot-1",
            "tracks": {"total": self.total},
        }

    def playlist_items(self, playlist_id, market=None, fields="", limit=50, offset=0):
        self.events.append(f"fetch:{offset}")
        end = min(offset + limit, self.total)
        return {"items": [{"track": spotify_track(i)} for i in range(offset, end)]}

    def current_user_saved_tracks(self, limit=50, offset=0, market=None):
        self.saved_track_calls += 1
        return {"total": 0, "items": []}

    def current_user_saved_albums(self, limit=50, offset=0):
        self.saved_album_calls += 1
        return {"total": 0, "items": []}

    def current_user_followed_artists(self, limit=50, after=None):
        self.followed_artist_calls += 1
        return {"artists": {"total": 0, "items": [], "cursors": {"after": None}}}

    def artists(self, artist_ids):
        self.artist_calls += 1
        return {"artists": [{"id": artist_id, "images": []} for artist_id in artist_ids]}


class PlaylistFastPathTests(unittest.TestCase):
    def setUp(self):
        self.plugin_content = import_plugin_content()
        RecordingPlaylist.instances.clear()
        RecordingPlayer.events.clear()
        DeferredThread.started_targets.clear()

    def build_content(self, spotify):
        content = object.__new__(self.plugin_content.PluginContent)
        content.cache = FakeCache()
        content._PluginContent__spotipy = spotify
        content._PluginContent__user_country = "US"
        content._PluginContent__userid = "user"
        content._PluginContent__playlist_id = "playlist-1"
        content._PluginContent__addon = FakeAddon()
        content._PluginContent__addon_handle = 1
        content._PluginContent__base_url = "plugin://plugin.audio.spotifykodiconnect"
        content._PluginContent__params = {}
        content._PluginContent__cached_checksum = ""
        return content

    def test_play_playlist_starts_after_first_page_before_fetching_remaining_pages(self):
        events = RecordingPlayer.events
        spotify = FakeSpotify(events, total=75)
        content = self.build_content(spotify)

        content.play_playlist()

        self.assertEqual(["fetch:0", "play"], events[:2])
        self.assertEqual(1, len(DeferredThread.started_targets))
        self.assertEqual(50, len(RecordingPlaylist.instances[0].items))

    def test_play_playlist_skips_browse_only_metadata_calls(self):
        events = RecordingPlayer.events
        spotify = FakeSpotify(events, total=1)
        content = self.build_content(spotify)

        content.play_playlist()

        self.assertEqual(0, spotify.saved_track_calls)
        self.assertEqual(0, spotify.saved_album_calls)
        self.assertEqual(0, spotify.followed_artist_calls)
        self.assertEqual(0, spotify.artist_calls)


if __name__ == "__main__":
    unittest.main()
