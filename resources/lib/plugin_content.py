import math
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Tuple, Union

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
from simplecache import SimpleCache

from string_ids import *
import utils
from deps import spotipy
from utils import ADDON_ID, PROXY_PORT, log_exception, log_msg, get_chunks

PlayList = Dict[str, Union[str, Dict[str, List[Any]]]]


class PluginContent:
    action = ""
    spotipy = None
    userid = ""
    user_country = ""
    offset = 0
    playlist_id = ""
    album_id = ""
    track_id = ""
    artist_id = ""
    artist_name = ""
    owner_id = ""
    filter = ""
    token = ""
    limit = 50
    params = {}
    base_url = sys.argv[0]
    addon_handle = int(sys.argv[1])
    _cache_checksum = ""
    last_playlist_position = 0

    def __init__(self):
        try:
            self.addon: xbmcaddon.Addon = xbmcaddon.Addon(id=ADDON_ID)
            self.win: xbmcgui.Window = xbmcgui.Window(utils.ADDON_WINDOW_ID)
            self.cache: SimpleCache = SimpleCache()

            auth_token: str = self.get_authkey()
            if not auth_token:
                xbmcplugin.endOfDirectory(handle=self.addon_handle)
                return

            self.append_artist_to_title: bool = (
                self.addon.getSetting("appendArtistToTitle") == "true"
            )
            self.default_view_songs: str = self.addon.getSetting("songDefaultView")
            self.default_view_artists: str = self.addon.getSetting("artistDefaultView")
            self.default_view_playlists: str = self.addon.getSetting("playlistDefaultView")
            self.default_view_albums: str = self.addon.getSetting("albumDefaultView")
            self.default_view_category: str = self.addon.getSetting("categoryDefaultView")
            self.parse_params()
            self.spotipy: spotipy.Spotify = spotipy.Spotify(auth=auth_token)
            self.userid: str = self.spotipy.me()["id"]
            self.user_country = self.spotipy.me()["country"]
            if self.action:
                log_msg(f"Evaluating action '{self.action}'.")
                action = "self." + self.action
                eval(action)()
            else:
                log_msg("Browse main and setting up precache library.")
                self.browse_main()
                self.precache_library()

        except Exception as exc:
            log_exception(exc, "PluginContent init error")
            xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_authkey(self) -> str:
        """get authentication key"""
        auth_token = utils.get_cached_auth_token()

        if not auth_token:
            msg = self.addon.getLocalizedString(NO_CREDENTIALS_MSG_STR_ID)
            dialog = xbmcgui.Dialog()
            header = self.addon.getAddonInfo("name")
            dialog.ok(header, msg)

        return auth_token

    def parse_params(self):
        """parse parameters from the plugin entry path"""
        log_msg(f"sys.argv = {str(sys.argv)}")
        self.params: Dict[str, Any] = urllib.parse.parse_qs(sys.argv[2][1:])
        action = self.params.get("action", None)
        if action:
            self.action = action[0].lower()
            log_msg(f"Set action to '{self.action}'.")
        playlist_id = self.params.get("playlistid", None)
        if playlist_id:
            self.playlist_id = playlist_id[0]
        owner_id = self.params.get("ownerid", None)
        if owner_id:
            self.owner_id = owner_id[0]
        track_id = self.params.get("trackid", None)
        if track_id:
            self.track_id = track_id[0]
        album_id = self.params.get("albumid", None)
        if album_id:
            self.album_id = album_id[0]
        artist_id = self.params.get("artistid", None)
        if artist_id:
            self.artist_id = artist_id[0]
        artist_name = self.params.get("artistname", None)
        if artist_name:
            self.artist_name = artist_name[0]
        offset = self.params.get("offset", None)
        if offset:
            self.offset = int(offset[0])
        filt = self.params.get("applyfilter", None)
        if filt:
            self.filter = filt[0]

    def cache_checksum(self, opt_value: Any = None) -> str:
        """simple cache checksum based on a few most important values"""
        result = self._cache_checksum
        if not result:
            saved_tracks = self.get_saved_track_ids()
            saved_albums = self.get_savedalbumsids()
            followed_artists = self.get_followedartists()
            generic_checksum = self.addon.getSetting("cache_checksum")
            result = (
                f"{len(saved_tracks)}-{len(saved_albums)}-{len(followed_artists)}"
                f"-{generic_checksum}"
            )
            self._cache_checksum = result

        if opt_value:
            result += f"-{opt_value}"

        return result

    def build_url(self, query: Dict[str, str]) -> str:
        query_encoded = {}
        for key, value in list(query.items()):
            if isinstance(key, str):
                key = key.encode("utf-8")
            if isinstance(value, str):
                value = value.encode("utf-8")
            query_encoded[key] = value

        return self.base_url + "?" + urllib.parse.urlencode(query_encoded)

    def refresh_listing(self) -> None:
        self.addon.setSetting("cache_checksum", time.strftime("%Y%m%d%H%M%S", time.gmtime()))
        xbmc.executebuiltin("Container.Refresh")

    def add_track_listitems(self, tracks, append_artist_to_label: bool = False) -> None:
        list_items = self.get_track_list(tracks, append_artist_to_label)
        xbmcplugin.addDirectoryItems(self.addon_handle, list_items, totalItems=len(list_items))

    @staticmethod
    def get_track_name(track, append_artist_to_label: bool) -> str:
        if not append_artist_to_label:
            return track["name"]
        return f"{track['artist']} - {track['name']}"

    @staticmethod
    def get_track_rating(popularity: int) -> int:
        if not popularity:
            return 0

        return int(math.ceil(popularity * 6 / 100.0)) - 1

    def get_track_list(
        self, tracks, append_artist_to_label: bool = False
    ) -> List[Tuple[str, xbmcgui.ListItem, bool]]:
        list_items = []
        for count, track in enumerate(tracks):
            list_items.append(self.get_track_item(track, append_artist_to_label) + (False,))

        return list_items

    def get_track_item(
        self, track: Dict[str, Any], append_artist_to_label: bool = False
    ) -> Tuple[str, xbmcgui.ListItem]:
        duration = track["duration_ms"] / 1000
        label = self.get_track_name(track, append_artist_to_label)
        title = label if self.append_artist_to_title else track["name"]

        # Local playback by using proxy on this machine.
        url = f"http://localhost:{PROXY_PORT}/track/{track['id']}/{duration}"

        li = xbmcgui.ListItem(label, offscreen=True)
        li.setProperty("isPlayable", "true")
        li.setInfo(
            "music",
            {
                "title": title,
                "genre": track["genre"],
                "year": track["year"],
                "tracknumber": track["track_number"],
                "album": track["album"]["name"],
                "artist": track["artist"],
                "rating": track["rating"],
                "duration": duration,
            },
        )
        li.setArt({"thumb": track["thumb"]})
        li.setProperty("spotifytrackid", track["id"])
        li.setContentLookup(False)
        li.addContextMenuItems(track["contextitems"], True)
        li.setProperty("do_not_analyze", "true")
        li.setMimeType("audio/wave")

        return url, li

    def browse_main(self) -> None:
        # Main listing.
        xbmcplugin.setContent(self.addon_handle, "files")

        items = [
            (
                self.addon.getLocalizedString(MY_MUSIC_FOLDER_STR_ID),
                "plugin://plugin.audio.spotify/?action=browse_main_library",
                "DefaultMusicCompilations.png",
                True,
            ),
            (
                self.addon.getLocalizedString(EXPLORE_STR_ID),
                "plugin://plugin.audio.spotify/?action=browse_main_explore",
                "DefaultMusicGenres.png",
                True,
            ),
            (
                xbmc.getLocalizedString(137),
                "plugin://plugin.audio.spotify/?action=search",
                "DefaultMusicSearch.png",
                True,
            ),
        ]
        cur_user_label = self.spotipy.me()["display_name"]
        if not cur_user_label:
            cur_user_label = self.spotipy.me()["id"]
        label = f"{self.addon.getLocalizedString(CURRENT_USER_STR_ID)}: {cur_user_label}"
        items.append(
            (label, "plugin://plugin.audio.spotify/?action=switch_user", "DefaultActor.png", False)
        )
        for item in items:
            li = xbmcgui.ListItem(
                item[0],
                path=item[1]
                # iconImage=item[2]
            )
            li.setProperty("IsPlayable", "false")
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle, url=item[1], listitem=li, isFolder=item[3]
            )

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def browse_main_library(self) -> None:
        # Library nodes.
        xbmcplugin.setContent(self.addon_handle, "files")
        xbmcplugin.setProperty(
            self.addon_handle, "FolderName", self.addon.getLocalizedString(MY_MUSIC_FOLDER_STR_ID)
        )

        items = [
            (
                xbmc.getLocalizedString(136),
                f"plugin://plugin.audio.spotify/?action=browse_playlists&ownerid={self.userid}",
                "DefaultMusicPlaylists.png",
            ),
            (
                xbmc.getLocalizedString(132),
                "plugin://plugin.audio.spotify/?action=browse_savedalbums",
                "DefaultMusicAlbums.png",
            ),
            (
                xbmc.getLocalizedString(134),
                "plugin://plugin.audio.spotify/?action=browse_savedtracks",
                "DefaultMusicSongs.png",
            ),
            (
                xbmc.getLocalizedString(133),
                "plugin://plugin.audio.spotify/?action=browse_savedartists",
                "DefaultMusicArtists.png",
            ),
            (
                self.addon.getLocalizedString(MOST_PLAYED_ARTISTS_STR_ID),
                "plugin://plugin.audio.spotify/?action=browse_topartists",
                "DefaultMusicArtists.png",
            ),
            (
                self.addon.getLocalizedString(MOST_PLAYED_TRACKS_STR_ID),
                "plugin://plugin.audio.spotify/?action=browse_toptracks",
                "DefaultMusicSongs.png",
            ),
        ]

        for item in items:
            li = xbmcgui.ListItem(
                item[0],
                path=item[1]
                # iconImage=item[2]
            )
            li.setProperty("do_not_analyze", "true")
            li.setProperty("IsPlayable", "false")
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle, url=item[1], listitem=li, isFolder=True
            )

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def browse_topartists(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "artists")
        result = self.spotipy.current_user_top_artists(limit=20, offset=0)

        cache_str = f"spotify.topartists.{self.userid}"
        checksum = self.cache_checksum(result["total"])
        items = self.cache.get(cache_str, checksum=checksum)
        if not items:
            count = len(result["items"])
            while result["total"] > count:
                result["items"] += self.spotipy.current_user_top_artists(limit=20, offset=count)[
                    "items"
                ]
                count += 50
            items = self.prepare_artist_listitems(result["items"])
            self.cache.set(cache_str, items, checksum=checksum)
        self.add_artist_listitems(items)

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def browse_toptracks(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "songs")
        results = self.spotipy.current_user_top_tracks(limit=20, offset=0)

        cache_str = f"spotify.toptracks.{self.userid}"
        checksum = self.cache_checksum(results["total"])
        tracks = self.cache.get(cache_str, checksum=checksum)
        if not tracks:
            tracks = results["items"]
            while results["next"]:
                results = self.spotipy.next(results)
                tracks.extend(results["items"])
            tracks = self.prepare_track_listitems(tracks=tracks)
            self.cache.set(cache_str, tracks, checksum=checksum)
        self.add_track_listitems(tracks, True)

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def get_explore_categories(self) -> List[Tuple[Any, str, Union[str, Any]]]:
        items = []

        categories = self.spotipy.categories(
            country=self.user_country, limit=50, locale=self.user_country
        )
        count = len(categories["categories"]["items"])
        while categories["categories"]["total"] > count:
            categories["categories"]["items"] += self.spotipy.categories(
                country=self.user_country, limit=50, offset=count, locale=self.user_country
            )["categories"]["items"]
            count += 50

        for item in categories["categories"]["items"]:
            thumb = "DefaultMusicGenre.png"
            for icon in item["icons"]:
                thumb = icon["url"]
                break
            items.append(
                (
                    item["name"],
                    f"plugin://plugin.audio.spotify/"
                    f"?action=browse_category&applyfilter={item['id']}",
                    thumb,
                )
            )

        return items

    def browse_main_explore(self) -> None:
        # Explore nodes.
        xbmcplugin.setContent(self.addon_handle, "files")
        xbmcplugin.setProperty(
            self.addon_handle, "FolderName", self.addon.getLocalizedString(EXPLORE_STR_ID)
        )
        items = [
            (
                self.addon.getLocalizedString(FEATURED_PLAYLISTS_STR_ID),
                "plugin://plugin.audio.spotify/?action=browse_playlists&applyfilter=featured",
                "DefaultMusicPlaylists.png",
            ),
            (
                self.addon.getLocalizedString(BROWSE_NEW_RELEASES_STR_ID),
                "plugin://plugin.audio.spotify/?action=browse_newreleases",
                "DefaultMusicAlbums.png",
            ),
        ]

        # Add categories.
        items += self.get_explore_categories()
        for item in items:
            li = xbmcgui.ListItem(
                item[0],
                path=item[1]
                # iconImage=item[2]
            )
            li.setProperty("do_not_analyze", "true")
            li.setProperty("IsPlayable", "false")
            li.setArt({"fanart": "special://home/addons/plugin.audio.spotify/fanart.jpg"})
            li.addContextMenuItems([], True)
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle, url=item[1], listitem=li, isFolder=True
            )

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def get_album_tracks(self, album: Dict[str, Any]) -> List[Dict[str, Any]]:
        cache_str = f"spotify.albumtracks{album['id']}"
        checksum = self.cache_checksum()

        album_tracks = self.cache.get(cache_str, checksum=checksum)
        if not album_tracks:
            track_ids = []
            count = 0
            while album["tracks"]["total"] > count:
                tracks = self.spotipy.album_tracks(
                    album["id"], market=self.user_country, limit=50, offset=count
                )["items"]
                for track in tracks:
                    track_ids.append(track["id"])
                count += 50
            album_tracks = self.prepare_track_listitems(track_ids, album_details=album)
            self.cache.set(cache_str, album_tracks, checksum=checksum)

        return album_tracks

    def browse_album(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "songs")
        album = self.spotipy.album(self.album_id, market=self.user_country)
        xbmcplugin.setProperty(self.addon_handle, "FolderName", album["name"])
        tracks = self.get_album_tracks(album)
        if album.get("album_type") == "compilation":
            self.add_track_listitems(tracks, True)
        else:
            self.add_track_listitems(tracks)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TRACKNUM)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_ARTIST)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def artist_toptracks(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(
            self.addon_handle, "FolderName", self.addon.getLocalizedString(ARTIST_TOP_TRACKS_STR_ID)
        )
        tracks = self.spotipy.artist_top_tracks(self.artist_id, country=self.user_country)
        tracks = self.prepare_track_listitems(tracks=tracks["tracks"])
        self.add_track_listitems(tracks)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TRACKNUM)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def related_artists(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(
            self.addon_handle, "FolderName", self.addon.getLocalizedString(RELATED_ARTISTS_STR_ID)
        )
        cache_str = f"spotify.relatedartists.{self.artist_id}"
        checksum = self.cache_checksum()
        artists = self.cache.get(cache_str, checksum=checksum)
        if not artists:
            artists = self.spotipy.artist_related_artists(self.artist_id)
            artists = self.prepare_artist_listitems(artists["artists"])
            self.cache.set(cache_str, artists, checksum=checksum)
        self.add_artist_listitems(artists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def get_playlist_details(self, playlist_id: str) -> PlayList:
        playlist = self.spotipy.playlist(
            playlist_id, fields="tracks(total),name,owner(id),id", market=self.user_country
        )
        # Get from cache first.
        cache_str = f"spotify.playlistdetails.{playlist['id']}"
        checksum = self.cache_checksum(playlist["tracks"]["total"])
        playlist_details = self.cache.get(cache_str, checksum=checksum)
        if not playlist_details:
            # Get listing from api.
            count = 0
            playlist_details = playlist
            playlist_details["tracks"]["items"] = []
            while playlist["tracks"]["total"] > count:
                playlist_details["tracks"]["items"] += self.spotipy.user_playlist_tracks(
                    playlist["owner"]["id"],
                    playlist["id"],
                    market=self.user_country,
                    fields="",
                    limit=50,
                    offset=count,
                )["items"]
                count += 50
            playlist_details["tracks"]["items"] = self.prepare_track_listitems(
                tracks=playlist_details["tracks"]["items"], playlist_details=playlist
            )
            # log_msg(f"playlist_details = {playlist_details}")
            self.cache.set(cache_str, playlist_details, checksum=checksum)

        return playlist_details

    def browse_playlist(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "songs")
        playlist_details = self.get_playlist_details(self.playlist_id)
        xbmcplugin.setProperty(self.addon_handle, "FolderName", playlist_details["name"])
        self.add_track_listitems(playlist_details["tracks"]["items"], True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def play_playlist(self) -> None:
        """play entire playlist"""
        playlist_details = self.get_playlist_details(self.playlist_id)
        log_msg(f"Start playing playlist '{playlist_details['name']}'.")

        kodi_playlist = xbmc.PlayList(0)
        kodi_playlist.clear()

        def add_to_playlist(trk) -> None:
            url, li = self.get_track_item(trk, True)
            kodi_playlist.add(url, li)

        # Add first track and start playing.
        add_to_playlist(playlist_details["tracks"]["items"][0])
        kodi_player = xbmc.Player()
        kodi_player.play(kodi_playlist)

        # Add remaining tracks to the playlist while already playing.
        for track in playlist_details["tracks"]["items"][1:]:
            add_to_playlist(track)

    def get_category(self, categoryid: str) -> PlayList:
        category = self.spotipy.category(
            categoryid, country=self.user_country, locale=self.user_country
        )
        playlists = self.spotipy.category_playlists(
            categoryid, country=self.user_country, limit=50, offset=0
        )
        playlists["category"] = category["name"]
        count = len(playlists["playlists"]["items"])
        while playlists["playlists"]["total"] > count:
            playlists["playlists"]["items"] += self.spotipy.category_playlists(
                categoryid, country=self.user_country, limit=50, offset=count
            )["playlists"]["items"]
            count += 50
        playlists["playlists"]["items"] = self.prepare_playlist_listitems(
            playlists["playlists"]["items"]
        )

        return playlists

    def browse_category(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "files")
        playlists = self.get_category(self.filter)
        self.add_playlist_listitems(playlists["playlists"]["items"])
        xbmcplugin.setProperty(self.addon_handle, "FolderName", playlists["category"])
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_category:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_category})")

    def follow_playlist(self) -> None:
        self.spotipy.current_user_follow_playlist(self.playlist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def add_track_to_playlist(self) -> None:
        xbmc.executebuiltin("ActivateWindow(busydialog)")

        if not self.track_id and xbmc.getInfoLabel("MusicPlayer.(1).Property(spotifytrackid)"):
            self.track_id = xbmc.getInfoLabel("MusicPlayer.(1).Property(spotifytrackid)")

        own_playlists, own_playlist_names = utils.get_user_playlists(self.spotipy, 50)
        own_playlist_names.append(xbmc.getLocalizedString(525))

        xbmc.executebuiltin("Dialog.Close(busydialog)")
        select = xbmcgui.Dialog().select(xbmc.getLocalizedString(524), own_playlist_names)
        if select != -1 and own_playlist_names[select] == xbmc.getLocalizedString(525):
            # create new playlist...
            kb = xbmc.Keyboard("", xbmc.getLocalizedString(21381))
            kb.setHiddenInput(False)
            kb.doModal()
            if kb.isConfirmed():
                name = kb.getText()
                playlist = self.spotipy.user_playlist_create(self.userid, name, False)
                self.spotipy.playlist_add_items(playlist["id"], [self.track_id])
        elif select != -1:
            playlist = own_playlists[select]
            self.spotipy.playlist_add_items(playlist["id"], [self.track_id])

    def remove_track_from_playlist(self) -> None:
        self.spotipy.playlist_remove_all_occurrences_of_items(self.playlist_id, [self.track_id])
        self.refresh_listing()

    def unfollow_playlist(self) -> None:
        self.spotipy.current_user_unfollow_playlist(self.playlist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def follow_artist(self) -> None:
        self.spotipy.user_follow_artists(self.artist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def unfollow_artist(self) -> None:
        self.spotipy.user_unfollow_artists(self.artist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def save_album(self) -> None:
        self.spotipy.current_user_saved_albums_add([self.album_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def remove_album(self) -> None:
        self.spotipy.current_user_saved_albums_delete([self.album_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def save_track(self) -> None:
        self.spotipy.current_user_saved_tracks_add([self.track_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def remove_track(self) -> None:
        self.spotipy.current_user_saved_tracks_delete([self.track_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def follow_user(self) -> None:
        self.spotipy.user_follow_users(self.userid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def unfollow_user(self) -> None:
        self.spotipy.user_unfollow_users(self.userid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def get_featured_playlists(self) -> PlayList:
        playlists = self.spotipy.featured_playlists(country=self.user_country, limit=50, offset=0)
        count = len(playlists["playlists"]["items"])
        total = playlists["playlists"]["total"]
        while total > count:
            playlists["playlists"]["items"] += self.spotipy.featured_playlists(
                country=self.user_country, limit=50, offset=count
            )["playlists"]["items"]
            count += 50
        playlists["playlists"]["items"] = self.prepare_playlist_listitems(
            playlists["playlists"]["items"]
        )

        return playlists

    def get_user_playlists(self, userid):
        playlists = self.spotipy.user_playlists(userid, limit=1, offset=0)
        count = len(playlists["items"])
        total = playlists["total"]
        cache_str = f"spotify.userplaylists.{userid}"
        checksum = self.cache_checksum(total)

        cache = self.cache.get(cache_str, checksum=checksum)
        if cache:
            playlists = cache
        else:
            while total > count:
                playlists["items"] += self.spotipy.user_playlists(userid, limit=50, offset=count)[
                    "items"
                ]
                count += 50
            playlists = self.prepare_playlist_listitems(playlists["items"])
            self.cache.set(cache_str, playlists, checksum=checksum)

        return playlists

    def get_curuser_playlistids(self) -> List[str]:
        playlists = self.spotipy.current_user_playlists(limit=1, offset=0)
        count = len(playlists["items"])
        total = playlists["total"]
        cache_str = f"spotify.userplaylistids.{self.userid}"
        playlist_ids = self.cache.get(cache_str, checksum=total)
        if not playlist_ids:
            playlist_ids = []
            while total > count:
                playlists["items"] += self.spotipy.current_user_playlists(limit=50, offset=count)[
                    "items"
                ]
                count += 50
            for playlist in playlists["items"]:
                playlist_ids.append(playlist["id"])
            self.cache.set(cache_str, playlist_ids, checksum=total)
        return playlist_ids

    def browse_playlists(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "files")
        if self.filter == "featured":
            playlists = self.get_featured_playlists()
            xbmcplugin.setProperty(self.addon_handle, "FolderName", playlists["message"])
            playlists = playlists["playlists"]["items"]
        else:
            xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(136))
            playlists = self.get_user_playlists(self.owner_id)

        self.add_playlist_listitems(playlists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_playlists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_playlists})")

    def get_newreleases(self):
        albums = self.spotipy.new_releases(country=self.user_country, limit=50, offset=0)
        count = len(albums["albums"]["items"])
        while albums["albums"]["total"] > count:
            albums["albums"]["items"] += self.spotipy.new_releases(
                country=self.user_country, limit=50, offset=count
            )["albums"]["items"]
            count += 50

        album_ids = []
        for album in albums["albums"]["items"]:
            album_ids.append(album["id"])
        albums = self.prepare_album_listitems(album_ids)

        return albums

    def browse_newreleases(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(
            self.addon_handle, "FolderName", self.addon.getLocalizedString(NEW_RELEASES_STR_ID)
        )
        albums = self.get_newreleases()
        self.add_album_listitems(albums)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_albums:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_albums})")

    def prepare_track_listitems(
        self, track_ids=None, tracks=None, playlist_details=None, album_details=None
    ) -> List[Dict[str, Any]]:
        if tracks is None:
            tracks = []
        if track_ids is None:
            track_ids = []

        new_tracks: List[Dict[str, Any]] = []

        # For tracks, we always get the full details unless full tracks already supplied.
        if track_ids and not tracks:
            for chunk in get_chunks(track_ids, 20):
                tracks += self.spotipy.tracks(chunk, market=self.user_country)["tracks"]

        saved_track_ids = self.get_saved_track_ids()

        followed_artists = []
        for artist in self.get_followedartists():
            followed_artists.append(artist["id"])

        for track in tracks:
            if track.get("track"):
                track = track["track"]
            if album_details:
                track["album"] = album_details
            if track.get("images"):
                thumb = track["images"][0]["url"]
            elif track.get("album", {}).get("images"):
                thumb = track["album"]["images"][0]["url"]
            else:
                thumb = "DefaultMusicSongs.png"
            track["thumb"] = thumb

            # skip local tracks in playlists
            if not track.get("id"):
                continue

            artists = []
            for artist in track["artists"]:
                artists.append(artist["name"])
            track["artist"] = " / ".join(artists)
            track["artistid"] = track["artists"][0]["id"]

            track["genre"] = " / ".join(track["album"].get("genres", []))

            # Allow for 'release_date' being empty.
            release_date = "0" if "album" not in track else track["album"].get("release_date", "0")
            track["year"] = (
                1900
                if not release_date
                else int(track["album"].get("release_date", "0").split("-")[0])
            )

            track["rating"] = str(self.get_track_rating(track["popularity"]))
            if playlist_details:
                track["playlistid"] = playlist_details["id"]

            # Use original track id for actions when the track was relinked.
            if track.get("linked_from"):
                real_track_id = track["linked_from"]["id"]
                real_track_uri = track["linked_from"]["uri"]
            else:
                real_track_id = track["id"]
                real_track_uri = track["uri"]

            contextitems = []
            if track["id"] in saved_track_ids:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(REMOVE_TRACKS_FROM_MY_MUSIC_STR_ID),
                        f"RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=remove_track&trackid={real_track_id})",
                    )
                )
            else:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(SAVE_TRACKS_TO_MY_MUSIC_STR_ID),
                        f"RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=save_track&trackid={real_track_id})",
                    )
                )

            if playlist_details and playlist_details["owner"]["id"] == self.userid:
                contextitems.append(
                    (
                        f"{self.addon.getLocalizedString(REMOVE_FROM_PLAYLIST_STR_ID)}"
                        f" {playlist_details['name']}",
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        "?action=remove_track_from_playlist&trackid="
                        f"{real_track_uri}&playlistid={playlist_details['id']})",
                    )
                )

            contextitems.append(
                (
                    xbmc.getLocalizedString(526),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=add_track_to_playlist&trackid={real_track_uri})",
                )
            )

            contextitems.append(
                (
                    self.addon.getLocalizedString(ARTIST_TOP_TRACKS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=artist_toptracks&artistid={track['artistid']})",
                )
            )
            contextitems.append(
                (
                    self.addon.getLocalizedString(RELATED_ARTISTS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=related_artists&artistid={track['artistid']})",
                )
            )
            contextitems.append(
                (
                    self.addon.getLocalizedString(ALL_ALBUMS_FOR_ARTIST_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=browse_artistalbums&artistid={track['artistid']})",
                )
            )

            if track["artistid"] in followed_artists:
                # unfollow artist
                contextitems.append(
                    (
                        self.addon.getLocalizedString(UNFOLLOW_ARTIST_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=unfollow_artist&artistid={track['artistid']})",
                    )
                )
            else:
                # follow artist
                contextitems.append(
                    (
                        self.addon.getLocalizedString(FOLLOW_ARTIST_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=follow_artist&artistid={track['artistid']})",
                    )
                )

            contextitems.append(
                (
                    self.addon.getLocalizedString(REFRESH_LISTING_STR_ID),
                    "RunPlugin(plugin://plugin.audio.spotify/" "?action=refresh_listing)",
                )
            )
            track["contextitems"] = contextitems
            new_tracks.append(track)

        return new_tracks

    def prepare_album_listitems(
        self, album_ids: List[str] = None, albums: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        if albums is None:
            albums: List[Dict[str, Any]] = []
        if album_ids is None:
            album_ids = []
        if not albums and album_ids:
            # Get full info in chunks of 20.
            for chunk in get_chunks(album_ids, 20):
                albums += self.spotipy.albums(chunk, market=self.user_country)["albums"]

        saved_albums = self.get_savedalbumsids()

        # process listing
        for track in albums:
            if track.get("images"):
                track["thumb"] = track["images"][0]["url"]
            else:
                track["thumb"] = "DefaultMusicAlbums.png"

            track["url"] = self.build_url({"action": "browse_album", "albumid": track["id"]})

            artists = []
            for artist in track["artists"]:
                artists.append(artist["name"])
            track["artist"] = " / ".join(artists)
            track["genre"] = " / ".join(track["genres"])
            track["year"] = int(track["release_date"].split("-")[0])
            track["rating"] = str(self.get_track_rating(track["popularity"]))
            track["artistid"] = track["artists"][0]["id"]

            contextitems = [
                (xbmc.getLocalizedString(1024), f"RunPlugin({track['url']})"),
                (
                    xbmc.getLocalizedString(208),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=connect_playback&albumid={track['id']})",
                ),
                (
                    self.addon.getLocalizedString(ARTIST_TOP_TRACKS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=artist_toptracks&artistid={track['artistid']})",
                ),
                (
                    self.addon.getLocalizedString(RELATED_ARTISTS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=related_artists&artistid={track['artistid']})",
                ),
                (
                    self.addon.getLocalizedString(ALL_ALBUMS_FOR_ARTIST_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=browse_artistalbums&artistid={track['artistid']})",
                ),
                (
                    self.addon.getLocalizedString(REFRESH_LISTING_STR_ID),
                    "RunPlugin(plugin://plugin.audio.spotify/" "?action=refresh_listing)",
                ),
            ]

            if track["id"] in saved_albums:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(REMOVE_TRACKS_FROM_MY_MUSIC_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=remove_album&albumid={track['id']})",
                    )
                )
            else:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(SAVE_TRACKS_TO_MY_MUSIC_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=save_album&albumid={track['id']})",
                    )
                )

            track["contextitems"] = contextitems

        return albums

    def add_album_listitems(
        self, albums: List[Dict[str, Any]], append_artist_to_label: bool = False
    ) -> None:
        # Process listing.
        for track in albums:
            label = self.get_track_name(track, append_artist_to_label)

            li = xbmcgui.ListItem(label, path=track["url"], offscreen=True)
            info_labels = {
                "title": track["name"],
                "genre": track["genre"],
                "year": track["year"],
                "album": track["name"],
                "artist": track["artist"],
                "rating": track["rating"],
            }
            li.setInfo(type="Music", infoLabels=info_labels)
            li.setArt({"thumb": track["thumb"]})
            li.setProperty("do_not_analyze", "true")
            li.setProperty("IsPlayable", "false")
            li.addContextMenuItems(track["contextitems"], True)
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle, url=track["url"], listitem=li, isFolder=True
            )

    def prepare_artist_listitems(
        self, artists: List[Dict[str, Any]], is_followed: bool = False
    ) -> List[Dict[str, Any]]:
        followed_artists = []
        if not is_followed:
            for artist in self.get_followedartists():
                followed_artists.append(artist["id"])

        for item in artists:
            if not item:
                return []
            if item.get("artist"):
                item = item["artist"]
            if item.get("images"):
                item["thumb"] = item["images"][0]["url"]
            else:
                item["thumb"] = "DefaultMusicArtists.png"

            item["url"] = self.build_url({"action": "browse_artistalbums", "artistid": item["id"]})

            item["genre"] = " / ".join(item["genres"])
            item["rating"] = str(self.get_track_rating(item["popularity"]))
            item["followerslabel"] = f"{item['followers']['total']} followers"

            contextitems = [
                (xbmc.getLocalizedString(132), f"Container.Update({item['url']})"),
                (
                    xbmc.getLocalizedString(208),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=connect_playback&artistid={item['id']})",
                ),
                (
                    self.addon.getLocalizedString(ARTIST_TOP_TRACKS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=artist_toptracks&artistid={item['id']})",
                ),
                (
                    self.addon.getLocalizedString(RELATED_ARTISTS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=related_artists&artistid={item['id']})",
                ),
            ]

            if is_followed or item["id"] in followed_artists:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(UNFOLLOW_ARTIST_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=unfollow_artist&artistid={item['id']})",
                    )
                )
            else:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(FOLLOW_ARTIST_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=follow_artist&artistid={item['id']})",
                    )
                )

            item["contextitems"] = contextitems

        return artists

    def add_artist_listitems(self, artists: List[Dict[str, Any]]) -> None:
        for item in artists:
            li = xbmcgui.ListItem(item["name"], path=item["url"], offscreen=True)
            info_labels = {
                "title": item["name"],
                "genre": item["genre"],
                "artist": item["name"],
                "rating": item["rating"],
            }
            li.setInfo(type="Music", infoLabels=info_labels)
            li.setArt({"thumb": item["thumb"]})
            li.setProperty("do_not_analyze", "true")
            li.setProperty("IsPlayable", "false")
            li.setLabel2(item["followerslabel"])
            li.addContextMenuItems(item["contextitems"], True)
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle,
                url=item["url"],
                listitem=li,
                isFolder=True,
                totalItems=len(artists),
            )

    def prepare_playlist_listitems(self, playlists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        playlists2 = []
        followed_playlists = self.get_curuser_playlistids()

        for item in playlists:
            if not item:
                continue

            if item.get("images"):
                item["thumb"] = item["images"][0]["url"]
            else:
                item["thumb"] = "DefaultMusicAlbums.png"

            item["url"] = self.build_url(
                {
                    "action": "browse_playlist",
                    "playlistid": item["id"],
                    "ownerid": item["owner"]["id"],
                }
            )

            contextitems = [
                (
                    xbmc.getLocalizedString(208),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=play_playlist&playlistid={item['id']}&ownerid={item['owner']['id']})",
                ),
                (
                    self.addon.getLocalizedString(REFRESH_LISTING_STR_ID),
                    "RunPlugin(plugin://plugin.audio.spotify/?action=refresh_listing)",
                ),
            ]

            if item["owner"]["id"] != self.userid and item["id"] in followed_playlists:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(UNFOLLOW_PLAYLIST_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=unfollow_playlist&playlistid={item['id']}"
                        f"&ownerid={item['owner']['id']})",
                    )
                )
            elif item["owner"]["id"] != self.userid:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(FOLLOW_PLAYLIST_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=follow_playlist&playlistid={item['id']}"
                        f"&ownerid={item['owner']['id']})",
                    )
                )

            item["contextitems"] = contextitems
            playlists2.append(item)

        return playlists2

    def add_playlist_listitems(self, playlists: List[Dict[str, Any]]) -> None:
        for item in playlists:
            li = xbmcgui.ListItem(item["name"], path=item["url"], offscreen=True)
            li.setProperty("do_not_analyze", "true")
            li.setProperty("IsPlayable", "false")

            li.addContextMenuItems(item["contextitems"], True)
            li.setArt(
                {
                    "fanart": "special://home/addons/plugin.audio.spotify/fanart.jpg",
                    "thumb": item["thumb"],
                }
            )
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle, url=item["url"], listitem=li, isFolder=True
            )

    def browse_artistalbums(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(132))
        artist_albums = self.spotipy.artist_albums(
            self.artist_id,
            album_type="album,single,compilation",
            country=self.user_country,
            limit=50,
            offset=0,
        )
        count = len(artist_albums["items"])
        albumids = []
        while artist_albums["total"] > count:
            artist_albums["items"] += self.spotipy.artist_albums(
                self.artist_id,
                album_type="album,single,compilation",
                country=self.user_country,
                limit=50,
                offset=count,
            )["items"]
            count += 50
        for album in artist_albums["items"]:
            albumids.append(album["id"])
        albums = self.prepare_album_listitems(albumids)
        self.add_album_listitems(albums)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_ALBUM_IGNORE_THE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_albums:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_albums})")

    def get_savedalbumsids(self) -> List[str]:
        albums = self.spotipy.current_user_saved_albums(limit=1, offset=0)
        cache_str = f"spotify-savedalbumids.{self.userid}"
        checksum = albums["total"]
        cache = self.cache.get(cache_str, checksum=checksum)
        if cache:
            return cache

        album_ids = []
        if albums and albums.get("items"):
            count = len(albums["items"])
            album_ids = []
            while albums["total"] > count:
                albums["items"] += self.spotipy.current_user_saved_albums(limit=50, offset=count)[
                    "items"
                ]
                count += 50
            for album in albums["items"]:
                album_ids.append(album["album"]["id"])
            self.cache.set(cache_str, album_ids, checksum=checksum)

        return album_ids

    def get_savedalbums(self) -> List[Dict[str, Any]]:
        album_ids = self.get_savedalbumsids()
        cache_str = f"spotify.savedalbums.{self.userid}"
        checksum = self.cache_checksum(len(album_ids))
        albums = self.cache.get(cache_str, checksum=checksum)
        if not albums:
            albums = self.prepare_album_listitems(album_ids)
            self.cache.set(cache_str, albums, checksum=checksum)
        return albums

    def browse_savedalbums(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(132))
        albums = self.get_savedalbums()
        self.add_album_listitems(albums, True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_ALBUM_IGNORE_THE)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_VIDEO_YEAR)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_SONG_RATING)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        xbmcplugin.setContent(self.addon_handle, "albums")
        if self.default_view_albums:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_albums})")

    def get_saved_track_ids(self) -> List[str]:
        saved_tracks = self.spotipy.current_user_saved_tracks(
            limit=1, offset=self.offset, market=self.user_country
        )
        total = saved_tracks["total"]
        cache_str = f"spotify.savedtracksids.{self.userid}"
        cache = self.cache.get(cache_str, checksum=total)
        if cache:
            return cache

        # Get from api.
        track_ids = []
        count = len(saved_tracks["items"])
        while total > count:
            saved_tracks["items"] += self.spotipy.current_user_saved_tracks(
                limit=50, offset=count, market=self.user_country
            )["items"]
            count += 50
        for track in saved_tracks["items"]:
            track_ids.append(track["track"]["id"])
        self.cache.set(cache_str, track_ids, checksum=total)

        return track_ids

    def get_saved_tracks(self):
        # Get from cache first.
        track_ids = self.get_saved_track_ids()
        cache_str = f"spotify.savedtracks.{self.userid}"

        tracks = self.cache.get(cache_str, checksum=len(track_ids))
        if not tracks:
            # Get from api.
            tracks = self.prepare_track_listitems(track_ids)
            self.cache.set(cache_str, tracks, checksum=len(track_ids))

        return tracks

    def browse_savedtracks(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(134))
        tracks = self.get_saved_tracks()
        self.add_track_listitems(tracks, True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def get_savedartists(self) -> List[Dict[str, Any]]:
        saved_albums = self.get_savedalbums()
        followed_artists = self.get_followedartists()
        cache_str = f"spotify.savedartists.{self.userid}"
        checksum = len(saved_albums) + len(followed_artists)
        artists = self.cache.get(cache_str, checksum=checksum)
        if not artists:
            all_artist_ids = []
            artists = []
            # extract the artists from all saved albums
            for item in saved_albums:
                for artist in item["artists"]:
                    if artist["id"] not in all_artist_ids:
                        all_artist_ids.append(artist["id"])
            for chunk in get_chunks(all_artist_ids, 50):
                artists += self.prepare_artist_listitems(self.spotipy.artists(chunk)["artists"])
            # append artists that are followed
            for artist in followed_artists:
                if not artist["id"] in all_artist_ids:
                    artists.append(artist)
            self.cache.set(cache_str, artists, checksum=checksum)

        return artists

    def browse_savedartists(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(133))
        artists = self.get_savedartists()
        self.add_artist_listitems(artists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def get_followedartists(self) -> List[Dict[str, Any]]:
        artists = self.spotipy.current_user_followed_artists(limit=50)
        cache_str = f"spotify.followedartists.{self.userid}"
        checksum = artists["artists"]["total"]

        cache = self.cache.get(cache_str, checksum=checksum)
        if cache:
            artists = cache
        else:
            count = len(artists["artists"]["items"])
            after = artists["artists"]["cursors"]["after"]
            while artists["artists"]["total"] > count:
                result = self.spotipy.current_user_followed_artists(limit=50, after=after)
                artists["artists"]["items"] += result["artists"]["items"]
                after = result["artists"]["cursors"]["after"]
                count += 50
            artists = self.prepare_artist_listitems(artists["artists"]["items"], is_followed=True)
            self.cache.set(cache_str, artists, checksum=checksum)

        return artists

    def browse_followedartists(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(133))
        artists = self.get_followedartists()
        self.add_artist_listitems(artists)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def search_artists(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(133))

        result = self.spotipy.search(
            q=f"artist:{self.artist_id}",
            type="artist",
            limit=self.limit,
            offset=self.offset,
            market=self.user_country,
        )

        artists = self.prepare_artist_listitems(result["artists"]["items"])
        self.add_artist_listitems(artists)
        self.add_next_button(result["artists"]["total"])

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def search_tracks(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(134))

        result = self.spotipy.search(
            q=f"track:{self.track_id}",
            type="track",
            limit=self.limit,
            offset=self.offset,
            market=self.user_country,
        )

        tracks = self.prepare_track_listitems(tracks=result["tracks"]["items"])
        self.add_track_listitems(tracks, True)
        self.add_next_button(result["tracks"]["total"])

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def search_albums(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(132))

        result = self.spotipy.search(
            q=f"album:{self.album_id}",
            type="album",
            limit=self.limit,
            offset=self.offset,
            market=self.user_country,
        )

        album_ids = []
        for album in result["albums"]["items"]:
            album_ids.append(album["id"])
        albums = self.prepare_album_listitems(album_ids)
        self.add_album_listitems(albums, True)
        self.add_next_button(result["albums"]["total"])

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

        if self.default_view_albums:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_albums})")

    def search_playlists(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "files")

        result = self.spotipy.search(
            q=self.playlist_id,
            type="playlist",
            limit=self.limit,
            offset=self.offset,
            market=self.user_country,
        )

        log_msg(result)
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(136))
        playlists = self.prepare_playlist_listitems(result["playlists"]["items"])
        self.add_playlist_listitems(playlists)
        self.add_next_button(result["playlists"]["total"])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)

        if self.default_view_playlists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_playlists})")

    def search(self) -> None:
        xbmcplugin.setContent(self.addon_handle, "files")
        xbmcplugin.setPluginCategory(self.addon_handle, xbmc.getLocalizedString(283))

        kb = xbmc.Keyboard("", xbmc.getLocalizedString(16017))
        kb.doModal()
        if kb.isConfirmed():
            value = kb.getText()
            items = []
            result = self.spotipy.search(
                q=f"{value}",
                type="artist,album,track,playlist",
                limit=1,
                market=self.user_country,
            )
            items.append(
                (
                    f"{xbmc.getLocalizedString(133)} ({result['artists']['total']})",
                    f"plugin://plugin.audio.spotify/?action=search_artists&artistid={value}",
                )
            )
            items.append(
                (
                    f"{xbmc.getLocalizedString(136)} ({result['playlists']['total']})",
                    f"plugin://plugin.audio.spotify/?action=search_playlists&playlistid={value}",
                )
            )
            items.append(
                (
                    f"{xbmc.getLocalizedString(132)} ({result['albums']['total']})",
                    f"plugin://plugin.audio.spotify/?action=search_albums&albumid={value}",
                )
            )
            items.append(
                (
                    f"{xbmc.getLocalizedString(134)} ({result['tracks']['total']})",
                    f"plugin://plugin.audio.spotify/?action=search_tracks&trackid={value}",
                )
            )
            for item in items:
                li = xbmcgui.ListItem(
                    item[0],
                    path=item[1],
                    # iconImage="DefaultMusicAlbums.png"
                )
                li.setProperty("do_not_analyze", "true")
                li.setProperty("IsPlayable", "false")
                li.addContextMenuItems([], True)
                xbmcplugin.addDirectoryItem(
                    handle=self.addon_handle, url=item[1], listitem=li, isFolder=True
                )

        xbmcplugin.endOfDirectory(handle=self.addon_handle)

    def add_next_button(self, list_total: int) -> None:
        # Adds a next button if needed.
        params = self.params
        if list_total > self.offset + self.limit:
            params["offset"] = [str(self.offset + self.limit)]
            url = "plugin://plugin.audio.spotify/"

            for key, value in list(params.items()):
                if key == "action":
                    url += f"?{key}={value[0]}"
                elif key == "offset":
                    url += f"&{key}={value}"
                else:
                    url += f"&{key}={value[0]}"

            li = xbmcgui.ListItem(
                xbmc.getLocalizedString(33078),
                path=url,
                # iconImage="DefaultMusicAlbums.png"
            )
            li.setProperty("do_not_analyze", "true")
            li.setProperty("IsPlayable", "false")

            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle, url=url, listitem=li, isFolder=True
            )

    def precache_library(self) -> None:
        if not self.win.getProperty("Spotify.PreCachedItems"):
            monitor = xbmc.Monitor()
            self.win.setProperty("Spotify.PreCachedItems", "busy")
            user_playlists = self.get_user_playlists(self.userid)
            for playlist in user_playlists:
                self.get_playlist_details(playlist["id"])
                if monitor.abortRequested():
                    return
            self.get_savedalbums()
            if monitor.abortRequested():
                return
            self.get_savedartists()
            if monitor.abortRequested():
                return
            self.get_saved_tracks()
            del monitor
            self.win.setProperty("Spotify.PreCachedItems", "done")
