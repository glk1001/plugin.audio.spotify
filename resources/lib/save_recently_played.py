import os
import time

import xbmc
import xbmcaddon
import xbmcgui

import spotipy
import utils
from utils import log_msg, ADDON_ID, ADDON_DATA_PATH

ADDON_OUTPUT_PATH = f"{ADDON_DATA_PATH}/output"


class SaveRecentlyPlayed:
    def __init__(self):
        self.spotipy = None
        self.win = xbmcgui.Window(10000)
        self.my_recently_played_playlist_name = self.__get_my_recently_played_playlist_name()
        self.my_recently_played_playlist_id = None

        os.makedirs(ADDON_OUTPUT_PATH, exist_ok=True)
        timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
        self.recently_played_file = f"{ADDON_OUTPUT_PATH}/recently_played_{timestamp}.txt"

    def save_currently_playing_track(self, track_id):
        if not xbmc.Player().isPlaying():
            log_msg(f"Player not active. Not saving track to recently played.", xbmc.LOGWARNING)
            return

        if self.my_recently_played_playlist_name:
            if not self.my_recently_played_playlist_id:
                self.__set_my_recently_played_playlist_id()
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
    def __get_my_recently_played_playlist_name():
        return xbmcaddon.Addon(id=ADDON_ID).getSetting("my_recently_played_playlist_name")

    def __set_my_recently_played_playlist_id(self):
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
