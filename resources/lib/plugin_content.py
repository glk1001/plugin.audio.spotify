# -*- coding: utf8 -*-
from __future__ import print_function, unicode_literals

import sys
import time
import urllib
from urllib.parse import urlparse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
from simplecache import SimpleCache

import utils
from deps import spotipy
from utils import (
    ADDON_ID,
    PROXY_PORT,
    log_exception,
    log_msg,
    get_chunks,
    get_track_rating,
    parse_spotify_track,
)

NEW_RELEASES_STR_ID = 11005
SAVE_TRACKS_TO_MY_MUSIC_STR_ID = 11007
REMOVE_TRACKS_FROM_MY_MUSIC_STR_ID = 11008
FOLLOW_PLAYLIST_STR_ID = 11009
UNFOLLOW_PLAYLIST_STR_ID = 11010
ARTIST_TOP_TRACKS_STR_ID = 11011
RELATED_ARTISTS_STR_ID = 11012
MY_MUSIC_FOLDER_STR_ID = 11013
EXPLORE_STR_ID = 11014
FEATURED_PLAYLISTS_STR_ID = 11015
BROWSE_NEW_RELEASES_STR_ID = 11016
REMOVE_FROM_PLAYLIST_STR_ID = 11017
ALL_ALBUMS_FOR_ARTIST_STR_ID = 11018
MOST_PLAYED_ARTISTS_STR_ID = 11023
MOST_PLAYED_TRACKS_STR_ID = 11024
FOLLOW_ARTIST_STR_ID = 11025
UNFOLLOW_ARTIST_STR_ID = 11026
REFRESH_LISTING_STR_ID = 11027
LOCAL_PLAYBACK_STR_ID = 11037
PLAYBACK_DEVICE_STR_ID = 11039
CURRENT_USER_STR_ID = 11047
NO_CREDENTIALS_MSG_STR_ID = 11050


class MyPlayer(xbmc.Player):
    def onPlayBackStarted(self) -> None:
        log_msg("onPlayBackStarted called.")

    def onAVStarted(self) -> None:
        log_msg("onAVStarted called.")

    def onAVChange(self) -> None:
        log_msg("onAVChange called.")

    def onPlayBackEnded(self) -> None:
        log_msg("onPlayBackEnded called.")

    def onPlayBackStopped(self) -> None:
        log_msg("onPlayBackStopped called.")

    def onPlayBackError(self) -> None:
        log_msg("onPlayBackError called.")

    def onPlayBackPaused(self) -> None:
        log_msg("onPlayBackPaused called.")

    def onPlayBackResumed(self) -> None:
        log_msg("onPlayBackResumed called.")


class PluginContent:
    action = ""
    sp = None
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
            self.addon = xbmcaddon.Addon(id=ADDON_ID)
            self.win = xbmcgui.Window(utils.ADDON_WINDOW_ID)
            self.cache = SimpleCache()

            auth_token = self.get_authkey()
            if not auth_token:
                xbmcplugin.endOfDirectory(handle=self.addon_handle)
                return

            self.append_artist_to_title = self.addon.getSetting("appendArtistToTitle") == "true"
            self.default_view_songs = self.addon.getSetting("songDefaultView")
            self.default_view_artists = self.addon.getSetting("artistDefaultView")
            self.default_view_playlists = self.addon.getSetting("playlistDefaultView")
            self.default_view_albums = self.addon.getSetting("albumDefaultView")
            self.default_view_category = self.addon.getSetting("categoryDefaultView")
            self.parse_params()
            self.sp = spotipy.Spotify(auth=auth_token)
            self.userid = self.sp.me()["id"]
            self.user_country = self.sp.me()["country"]
            self.playername = self.active_playback_device()
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

    def get_authkey(self):
        """get authentication key"""
        auth_token = utils.get_cached_auth_token()

        if not auth_token:
            if self.win.getProperty("spotify.supportsplayback"):
                msg = self.addon.getLocalizedString(NO_CREDENTIALS_MSG_STR_ID)
                dialog = xbmcgui.Dialog()
                header = self.addon.getAddonInfo("name")
                dialog.ok(header, msg)
                del dialog

        return auth_token

    def parse_params(self):
        """parse parameters from the plugin entry path"""
        log_msg(f"sys.argv = {str(sys.argv)}")
        self.params = urllib.parse.parse_qs(sys.argv[2][1:])
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
        # default settings

    def cache_checksum(self, opt_value=None):
        """simple cache checksum based on a few most important values"""
        result = self._cache_checksum
        if not result:
            saved_tracks = self.get_saved_tracks_ids()
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

    def build_url(self, query):
        query_encoded = {}
        for key, value in list(query.items()):
            if isinstance(key, str):
                key = key.encode("utf-8")
            if isinstance(value, str):
                value = value.encode("utf-8")
            query_encoded[key] = value

        return self.base_url + "?" + urllib.parse.urlencode(query_encoded)

    def refresh_listing(self):
        self.addon.setSetting("cache_checksum", time.strftime("%Y%m%d%H%M%S", time.gmtime()))
        xbmc.executebuiltin("Container.Refresh")

    def browse_main(self):
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
            (
                f"{self.addon.getLocalizedString(PLAYBACK_DEVICE_STR_ID)}: {self.playername}",
                "plugin://plugin.audio.spotify/?action=browse_playback_devices",
                "DefaultMusicPlugins.png",
                True,
            ),
        ]
        cur_user_label = self.sp.me()["display_name"]
        if not cur_user_label:
            cur_user_label = self.sp.me()["id"]
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

    def active_playback_device(self):
        device_name = self.addon.getLocalizedString(LOCAL_PLAYBACK_STR_ID)

        return device_name

    def browse_main_library(self):
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

    def browse_topartists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        result = self.sp.current_user_top_artists(limit=20, offset=0)

        cache_str = f"spotify.topartists.{self.userid}"
        checksum = self.cache_checksum(result["total"])
        items = self.cache.get(cache_str, checksum=checksum)
        if not items:
            count = len(result["items"])
            while result["total"] > count:
                result["items"] += self.sp.current_user_top_artists(limit=20, offset=count)["items"]
                count += 50
            items = self.prepare_artist_listitems(result["items"])
            self.cache.set(cache_str, items, checksum=checksum)
        self.add_artist_listitems(items)

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def browse_toptracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        results = self.sp.current_user_top_tracks(limit=20, offset=0)

        cache_str = f"spotify.toptracks.{self.userid}"
        checksum = self.cache_checksum(results["total"])
        items = self.cache.get(cache_str, checksum=checksum)
        if not items:
            items = results["items"]
            while results["next"]:
                results = self.sp.next(results)
                items.extend(results["items"])
            items = self.prepare_track_listitems(tracks=items)
            self.cache.set(cache_str, items, checksum=checksum)
        self.add_track_listitems(items, True)

        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def get_explore_categories(self):
        items = []

        categories = self.sp.categories(
            country=self.user_country, limit=50, locale=self.user_country
        )
        count = len(categories["categories"]["items"])
        while categories["categories"]["total"] > count:
            categories["categories"]["items"] += self.sp.categories(
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

    def browse_main_explore(self):
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

    def get_album_tracks(self, album):
        cache_str = f"spotify.albumtracks{album['id']}"
        checksum = self.cache_checksum()

        album_tracks = self.cache.get(cache_str, checksum=checksum)
        if not album_tracks:
            track_ids = []
            count = 0
            while album["tracks"]["total"] > count:
                album_tracks = self.sp.album_tracks(
                    album["id"], market=self.user_country, limit=50, offset=count
                )["items"]
                for track in album_tracks:
                    track_ids.append(track["id"])
                count += 50
            album_tracks = self.prepare_track_listitems(track_ids, album_details=album)
            self.cache.set(cache_str, album_tracks, checksum=checksum)

        return album_tracks

    def browse_album(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        album = self.sp.album(self.album_id, market=self.user_country)
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

    def artist_toptracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(
            self.addon_handle, "FolderName", self.addon.getLocalizedString(ARTIST_TOP_TRACKS_STR_ID)
        )
        tracks = self.sp.artist_top_tracks(self.artist_id, country=self.user_country)
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

    def related_artists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(
            self.addon_handle, "FolderName", self.addon.getLocalizedString(RELATED_ARTISTS_STR_ID)
        )
        cache_str = f"spotify.relatedartists.{self.artist_id}"
        checksum = self.cache_checksum()
        artists = self.cache.get(cache_str, checksum=checksum)
        if not artists:
            artists = self.sp.artist_related_artists(self.artist_id)
            artists = self.prepare_artist_listitems(artists["artists"])
            self.cache.set(cache_str, artists, checksum=checksum)
        self.add_artist_listitems(artists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def get_playlist_details(self, playlistid):
        playlist = self.sp.playlist(
            playlistid, fields="tracks(total),name,owner(id),id", market=self.user_country
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
                playlist_details["tracks"]["items"] += self.sp.user_playlist_tracks(
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
            self.cache.set(cache_str, playlist_details, checksum=checksum)

        return playlist_details

    def browse_playlist(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        playlist_details = self.get_playlist_details(self.playlist_id)
        xbmcplugin.setProperty(self.addon_handle, "FolderName", playlist_details["name"])
        self.add_track_listitems(playlist_details["tracks"]["items"], True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def play_track(self):
        """play track"""
        track = self.sp.track(self.track_id)
        log_msg(f"Play track '{track['name']} ({self.track_id})'.")
        url, li = parse_spotify_track(track)

        kodi_player = MyPlayer()
        kodi_player.play(url, li)

        while not kodi_player.isPlaying():
            time.sleep(0.1)
        log_msg("Starting wait loop.")
        while kodi_player.isPlaying():
            time.sleep(0.5)
        log_msg("Finished wait loop.")

    def play_playlist(self):
        """play entire playlist"""
        playlist_details = self.get_playlist_details(self.playlist_id)
        log_msg(f"Play playlist '{playlist_details['name']}'.")

        # Add tracks to the playlist then start playing.
        kodi_player = MyPlayer()
        track_num = 1
        for track in playlist_details["tracks"]["items"]:
            log_msg(f"Playing track {track_num}.")
            url, li = parse_spotify_track(track)
            kodi_player.play(url, li)
            while not kodi_player.isPlaying():
                time.sleep(0.1)
            track_num += 1
            log_msg("Starting wait loop.")
            while kodi_player.isPlaying():
                time.sleep(0.5)
            log_msg("Finished wait loop.")

    def get_category(self, categoryid):
        category = self.sp.category(categoryid, country=self.user_country, locale=self.user_country)
        playlists = self.sp.category_playlists(
            categoryid, country=self.user_country, limit=50, offset=0
        )
        playlists["category"] = category["name"]
        count = len(playlists["playlists"]["items"])
        while playlists["playlists"]["total"] > count:
            playlists["playlists"]["items"] += self.sp.category_playlists(
                categoryid, country=self.user_country, limit=50, offset=count
            )["playlists"]["items"]
            count += 50
        playlists["playlists"]["items"] = self.prepare_playlist_listitems(
            playlists["playlists"]["items"]
        )

        return playlists

    def browse_category(self):
        xbmcplugin.setContent(self.addon_handle, "files")
        playlists = self.get_category(self.filter)
        self.add_playlist_listitems(playlists["playlists"]["items"])
        xbmcplugin.setProperty(self.addon_handle, "FolderName", playlists["category"])
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_category:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_category})")

    def follow_playlist(self):
        self.sp.current_user_follow_playlist(self.playlist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def add_track_to_playlist(self):
        xbmc.executebuiltin("ActivateWindow(busydialog)")

        if not self.track_id and xbmc.getInfoLabel("MusicPlayer.(1).Property(spotifytrackid)"):
            self.track_id = xbmc.getInfoLabel("MusicPlayer.(1).Property(spotifytrackid)")

        own_playlists, own_playlist_names = utils.get_user_playlists(self.sp, 50)
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
                playlist = self.sp.user_playlist_create(self.userid, name, False)
                self.sp.playlist_add_items(playlist["id"], [self.track_id])
        elif select != -1:
            playlist = own_playlists[select]
            self.sp.playlist_add_items(playlist["id"], [self.track_id])

    def remove_track_from_playlist(self):
        self.sp.playlist_remove_all_occurrences_of_items(self.playlist_id, [self.track_id])
        self.refresh_listing()

    def unfollow_playlist(self):
        self.sp.current_user_unfollow_playlist(self.playlist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def follow_artist(self):
        self.sp.user_follow_artists(self.artist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def unfollow_artist(self):
        self.sp.user_unfollow_artists(self.artist_id)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def save_album(self):
        self.sp.current_user_saved_albums_add([self.album_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def remove_album(self):
        self.sp.current_user_saved_albums_delete([self.album_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def save_track(self):
        self.sp.current_user_saved_tracks_add([self.track_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def remove_track(self):
        self.sp.current_user_saved_tracks_delete([self.track_id])
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def follow_user(self):
        self.sp.user_follow_users(self.userid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def unfollow_user(self):
        self.sp.user_unfollow_users(self.userid)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        self.refresh_listing()

    def get_featured_playlists(self):
        playlists = self.sp.featured_playlists(country=self.user_country, limit=50, offset=0)
        count = len(playlists["playlists"]["items"])
        total = playlists["playlists"]["total"]
        while total > count:
            playlists["playlists"]["items"] += self.sp.featured_playlists(
                country=self.user_country, limit=50, offset=count
            )["playlists"]["items"]
            count += 50
        playlists["playlists"]["items"] = self.prepare_playlist_listitems(
            playlists["playlists"]["items"]
        )

        return playlists

    def get_user_playlists(self, userid):
        playlists = self.sp.user_playlists(userid, limit=1, offset=0)
        count = len(playlists["items"])
        total = playlists["total"]
        cache_str = f"spotify.userplaylists.{userid}"
        checksum = self.cache_checksum(total)

        cache = self.cache.get(cache_str, checksum=checksum)
        if cache:
            playlists = cache
        else:
            while total > count:
                playlists["items"] += self.sp.user_playlists(userid, limit=50, offset=count)[
                    "items"
                ]
                count += 50
            playlists = self.prepare_playlist_listitems(playlists["items"])
            self.cache.set(cache_str, playlists, checksum=checksum)

        return playlists

    def get_curuser_playlistids(self):
        playlists = self.sp.current_user_playlists(limit=1, offset=0)
        count = len(playlists["items"])
        total = playlists["total"]
        cache_str = f"spotify.userplaylistids.{self.userid}"
        playlist_ids = self.cache.get(cache_str, checksum=total)
        if not playlist_ids:
            playlist_ids = []
            while total > count:
                playlists["items"] += self.sp.current_user_playlists(limit=50, offset=count)[
                    "items"
                ]
                count += 50
            for playlist in playlists["items"]:
                playlist_ids.append(playlist["id"])
            self.cache.set(cache_str, playlist_ids, checksum=total)
        return playlist_ids

    def browse_playlists(self):
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
        albums = self.sp.new_releases(country=self.user_country, limit=50, offset=0)
        count = len(albums["albums"]["items"])
        while albums["albums"]["total"] > count:
            albums["albums"]["items"] += self.sp.new_releases(
                country=self.user_country, limit=50, offset=count
            )["albums"]["items"]
            count += 50

        album_ids = []
        for album in albums["albums"]["items"]:
            album_ids.append(album["id"])
        albums = self.prepare_album_listitems(album_ids)

        return albums

    def browse_newreleases(self):
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
    ):
        if tracks is None:
            tracks = []
        if track_ids is None:
            track_ids = []
        new_tracks = []
        # For tracks, we always get the full details unless full tracks already supplied.
        if track_ids and not tracks:
            for chunk in get_chunks(track_ids, 20):
                tracks += self.sp.tracks(chunk, market=self.user_country)["tracks"]

        saved_tracks = self.get_saved_tracks_ids()

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
            track["genre"] = " / ".join(track["album"].get("genres", []))
            # Allow for 'release_date' being empty.
            release_date = "0" if "album" not in track else track["album"].get("release_date", "0")
            track["year"] = (
                1900
                if not release_date
                else int(track["album"].get("release_date", "0").split("-")[0])
            )
            track["rating"] = str(get_track_rating(track["popularity"]))
            if playlist_details:
                track["playlistid"] = playlist_details["id"]
            track["artistid"] = track["artists"][0]["id"]

            # Use original track id for actions when the track was relinked.
            if track.get("linked_from"):
                real_trackid = track["linked_from"]["id"]
                real_trackuri = track["linked_from"]["uri"]
            else:
                real_trackid = track["id"]
                real_trackuri = track["uri"]

            contextitems = []
            if track["id"] in saved_tracks:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(REMOVE_TRACKS_FROM_MY_MUSIC_STR_ID),
                        f"RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=remove_track&trackid={real_trackid})",
                    )
                )
            else:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(SAVE_TRACKS_TO_MY_MUSIC_STR_ID),
                        f"RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=save_track&trackid={real_trackid})",
                    )
                )

            if playlist_details and playlist_details["owner"]["id"] == self.userid:
                contextitems.append(
                    (
                        f"{self.addon.getLocalizedString(REMOVE_FROM_PLAYLIST_STR_ID)}"
                        f" {playlist_details['name']}",
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        "?action=remove_track_from_playlist&trackid="
                        f"{real_trackuri}&playlistid={playlist_details['id']})",
                    )
                )

            contextitems.append(
                (
                    "MyPlay",  # xbmc.getLocalizedString(14098),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=play_track&trackid={real_trackuri})",
                )
            )

            contextitems.append(
                (
                    xbmc.getLocalizedString(526),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=add_track_to_playlist&trackid={real_trackuri})",
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

    def add_track_listitems(self, tracks, append_artist_to_label=False):
        list_items = []
        for count, track in enumerate(tracks):
            if append_artist_to_label:
                label = f"{track['artist']} - {track['name']}"
            else:
                label = track["name"]
            duration = track["duration_ms"] / 1000

            # Local playback by using proxy on this machine.
            url = f"http://localhost:{PROXY_PORT}/track/{track['id']}/{duration}"

            if self.append_artist_to_title:
                title = label
            else:
                title = track["name"]

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
            li.setInfo("video", {})
            list_items.append((url, li, False))

        xbmcplugin.addDirectoryItems(self.addon_handle, list_items, totalItems=len(list_items))

    def prepare_album_listitems(self, album_ids=None, albums=None):
        if albums is None:
            albums = []
        if album_ids is None:
            album_ids = []
        if not albums and album_ids:
            # Get full info in chunks of 20.
            for chunk in get_chunks(album_ids, 20):
                albums += self.sp.albums(chunk, market=self.user_country)["albums"]

        saved_albums = self.get_savedalbumsids()

        # process listing
        for item in albums:
            if item.get("images"):
                item["thumb"] = item["images"][0]["url"]
            else:
                item["thumb"] = "DefaultMusicAlbums.png"

            item["url"] = self.build_url({"action": "browse_album", "albumid": item["id"]})

            artists = []
            for artist in item["artists"]:
                artists.append(artist["name"])
            item["artist"] = " / ".join(artists)
            item["genre"] = " / ".join(item["genres"])
            item["year"] = int(item["release_date"].split("-")[0])
            item["rating"] = str(get_track_rating(item["popularity"]))
            item["artistid"] = item["artists"][0]["id"]

            contextitems = []
            # play
            contextitems.append(
                (
                    xbmc.getLocalizedString(208),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=connect_playback&albumid={item['id']})",
                )
            )
            contextitems.append((xbmc.getLocalizedString(1024), f"RunPlugin({item['url']})"))
            if item["id"] in saved_albums:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(REMOVE_TRACKS_FROM_MY_MUSIC_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=remove_album&albumid={item['id']})",
                    )
                )
            else:
                contextitems.append(
                    (
                        self.addon.getLocalizedString(SAVE_TRACKS_TO_MY_MUSIC_STR_ID),
                        "RunPlugin(plugin://plugin.audio.spotify/"
                        f"?action=save_album&albumid={item['id']})",
                    )
                )
            contextitems.append(
                (
                    self.addon.getLocalizedString(ARTIST_TOP_TRACKS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=artist_toptracks&artistid={item['artistid']})",
                )
            )
            contextitems.append(
                (
                    self.addon.getLocalizedString(RELATED_ARTISTS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=related_artists&artistid={item['artistid']})",
                )
            )
            contextitems.append(
                (
                    self.addon.getLocalizedString(ALL_ALBUMS_FOR_ARTIST_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=browse_artistalbums&artistid={item['artistid']})",
                )
            )
            contextitems.append(
                (
                    self.addon.getLocalizedString(REFRESH_LISTING_STR_ID),
                    "RunPlugin(plugin://plugin.audio.spotify/" "?action=refresh_listing)",
                )
            )
            item["contextitems"] = contextitems
        return albums

    def add_album_listitems(self, albums, append_artist_to_label=False):
        # Process listing.
        for item in albums:
            if append_artist_to_label:
                label = f"{item['artist']} - {item['name']}"
            else:
                label = item["name"]

            li = xbmcgui.ListItem(label, path=item["url"], offscreen=True)
            info_labels = {
                "title": item["name"],
                "genre": item["genre"],
                "year": item["year"],
                "album": item["name"],
                "artist": item["artist"],
                "rating": item["rating"],
            }
            li.setInfo(type="Music", infoLabels=info_labels)
            li.setArt({"thumb": item["thumb"]})
            li.setProperty("do_not_analyze", "true")
            li.setProperty("IsPlayable", "false")
            li.addContextMenuItems(item["contextitems"], True)
            xbmcplugin.addDirectoryItem(
                handle=self.addon_handle, url=item["url"], listitem=li, isFolder=True
            )

    def prepare_artist_listitems(self, artists, is_followed=False):
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
            item["rating"] = str(get_track_rating(item["popularity"]))
            item["followerslabel"] = f"{item['followers']['total']} followers"
            contextitems = []
            # play
            contextitems.append(
                (
                    xbmc.getLocalizedString(208),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=connect_playback&artistid={item['id']})",
                )
            )
            contextitems.append((xbmc.getLocalizedString(132), f"Container.Update({item['url']})"))
            contextitems.append(
                (
                    self.addon.getLocalizedString(ARTIST_TOP_TRACKS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=artist_toptracks&artistid={item['id']})",
                )
            )
            contextitems.append(
                (
                    self.addon.getLocalizedString(RELATED_ARTISTS_STR_ID),
                    "Container.Update(plugin://plugin.audio.spotify/"
                    f"?action=related_artists&artistid={item['id']})",
                )
            )
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

    def add_artist_listitems(self, artists):
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

    def prepare_playlist_listitems(self, playlists):
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

            contextitems = []
            # play
            contextitems.append(
                (
                    xbmc.getLocalizedString(208),
                    "RunPlugin(plugin://plugin.audio.spotify/"
                    f"?action=play_playlist&playlistid={item['id']}&ownerid={item['owner']['id']})",
                )
            )
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

            contextitems.append(
                (
                    self.addon.getLocalizedString(REFRESH_LISTING_STR_ID),
                    "RunPlugin(plugin://plugin.audio.spotify/?action=refresh_listing)",
                )
            )
            item["contextitems"] = contextitems
            playlists2.append(item)
        return playlists2

    def add_playlist_listitems(self, playlists):
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

    def browse_artistalbums(self):
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(132))
        artist_albums = self.sp.artist_albums(
            self.artist_id,
            album_type="album,single,compilation",
            country=self.user_country,
            limit=50,
            offset=0,
        )
        count = len(artist_albums["items"])
        albumids = []
        while artist_albums["total"] > count:
            artist_albums["items"] += self.sp.artist_albums(
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

    def get_savedalbumsids(self):
        albums = self.sp.current_user_saved_albums(limit=1, offset=0)
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
                albums["items"] += self.sp.current_user_saved_albums(limit=50, offset=count)[
                    "items"
                ]
                count += 50
            for album in albums["items"]:
                album_ids.append(album["album"]["id"])
            self.cache.set(cache_str, album_ids, checksum=checksum)

        return album_ids

    def get_savedalbums(self):
        album_ids = self.get_savedalbumsids()
        cache_str = f"spotify.savedalbums.{self.userid}"
        checksum = self.cache_checksum(len(album_ids))
        albums = self.cache.get(cache_str, checksum=checksum)
        if not albums:
            albums = self.prepare_album_listitems(album_ids)
            self.cache.set(cache_str, albums, checksum=checksum)
        return albums

    def browse_savedalbums(self):
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

    def get_saved_tracks_ids(self):
        saved_tracks = self.sp.current_user_saved_tracks(
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
            saved_tracks["items"] += self.sp.current_user_saved_tracks(
                limit=50, offset=count, market=self.user_country
            )["items"]
            count += 50
        for track in saved_tracks["items"]:
            track_ids.append(track["track"]["id"])
        self.cache.set(cache_str, track_ids, checksum=total)

        return track_ids

    def get_saved_tracks(self):
        # Get from cache first.
        track_ids = self.get_saved_tracks_ids()
        cache_str = f"spotify.savedtracks.{self.userid}"

        tracks = self.cache.get(cache_str, checksum=len(track_ids))
        if not tracks:
            # Get from api.
            tracks = self.prepare_track_listitems(track_ids)
            self.cache.set(cache_str, tracks, checksum=len(track_ids))

        return tracks

    def browse_savedtracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(134))
        tracks = self.get_saved_tracks()
        self.add_track_listitems(tracks, True)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_songs:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_songs})")

    def get_savedartists(self):
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
                artists += self.prepare_artist_listitems(self.sp.artists(chunk)["artists"])
            # append artists that are followed
            for artist in followed_artists:
                if not artist["id"] in all_artist_ids:
                    artists.append(artist)
            self.cache.set(cache_str, artists, checksum=checksum)

        return artists

    def browse_savedartists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(133))
        artists = self.get_savedartists()
        self.add_artist_listitems(artists)
        xbmcplugin.addSortMethod(self.addon_handle, xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def get_followedartists(self):
        artists = self.sp.current_user_followed_artists(limit=50)
        cache_str = f"spotify.followedartists.{self.userid}"
        checksum = artists["artists"]["total"]

        cache = self.cache.get(cache_str, checksum=checksum)
        if cache:
            artists = cache
        else:
            count = len(artists["artists"]["items"])
            after = artists["artists"]["cursors"]["after"]
            while artists["artists"]["total"] > count:
                result = self.sp.current_user_followed_artists(limit=50, after=after)
                artists["artists"]["items"] += result["artists"]["items"]
                after = result["artists"]["cursors"]["after"]
                count += 50
            artists = self.prepare_artist_listitems(artists["artists"]["items"], is_followed=True)
            self.cache.set(cache_str, artists, checksum=checksum)

        return artists

    def browse_followedartists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(133))
        artists = self.get_followedartists()
        self.add_artist_listitems(artists)
        xbmcplugin.endOfDirectory(handle=self.addon_handle)
        if self.default_view_artists:
            xbmc.executebuiltin(f"Container.SetViewMode({self.default_view_artists})")

    def search_artists(self):
        xbmcplugin.setContent(self.addon_handle, "artists")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(133))

        result = self.sp.search(
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

    def search_tracks(self):
        xbmcplugin.setContent(self.addon_handle, "songs")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(134))

        result = self.sp.search(
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

    def search_albums(self):
        xbmcplugin.setContent(self.addon_handle, "albums")
        xbmcplugin.setProperty(self.addon_handle, "FolderName", xbmc.getLocalizedString(132))

        result = self.sp.search(
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

    def search_playlists(self):
        xbmcplugin.setContent(self.addon_handle, "files")

        result = self.sp.search(
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

    def search(self):
        xbmcplugin.setContent(self.addon_handle, "files")
        xbmcplugin.setPluginCategory(self.addon_handle, xbmc.getLocalizedString(283))

        kb = xbmc.Keyboard("", xbmc.getLocalizedString(16017))
        kb.doModal()
        if kb.isConfirmed():
            value = kb.getText()
            items = []
            result = self.sp.search(
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

    def add_next_button(self, list_total):
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

    def precache_library(self):
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
