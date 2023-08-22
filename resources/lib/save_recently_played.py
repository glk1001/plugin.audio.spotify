import xbmc
import xbmcaddon

import spotipy
import utils
from utils import log_msg, ADDON_ID

ADDON_SETTING_MY_RECENTLY_PLAYED_PLAYLIST_NAME = "my_recently_played_playlist_name"


class SaveRecentlyPlayed:
    def __init__(self):
        self.__spotipy = None
        self.__my_recently_played_playlist_name = self.__get_my_recently_played_playlist_name()
        self.__my_recently_played_playlist_id = None

    def save_track(self, track_id):
        if not self.__my_recently_played_playlist_name:
            return

        if not self.__my_recently_played_playlist_id:
            self.__set_my_recently_played_playlist_id()

        self.__spotipy.playlist_add_items(self.__my_recently_played_playlist_id, [track_id])
        log_msg(
            f"Saved track '{track_id}' to '{self.__my_recently_played_playlist_name}' playlist.",
            xbmc.LOGINFO,
        )

    @staticmethod
    def __get_my_recently_played_playlist_name():
        return xbmcaddon.Addon(id=ADDON_ID).getSetting(
            ADDON_SETTING_MY_RECENTLY_PLAYED_PLAYLIST_NAME
        )

    def __set_my_recently_played_playlist_id(self):
        self.__spotipy = spotipy.Spotify(auth=utils.get_cached_auth_token())
        log_msg(
            f"Getting id for '{self.__my_recently_played_playlist_name}' playlist.", xbmc.LOGDEBUG
        )
        self.__my_recently_played_playlist_id = utils.get_user_playlist_id(
            self.__spotipy, self.__my_recently_played_playlist_name
        )

        if not self.__my_recently_played_playlist_id:
            log_msg(
                f"Did not find a '{self.__my_recently_played_playlist_name}' playlist."
                " Creating one now.",
                xbmc.LOGINFO,
            )
            userid = self.__spotipy.me()["id"]
            playlist = self.__spotipy.user_playlist_create(
                userid, self.__my_recently_played_playlist_name, False
            )
            self.__my_recently_played_playlist_id = playlist["id"]

            if not self.__my_recently_played_playlist_id:
                raise Exception(
                    f"Could not create a '{self.__my_recently_played_playlist_name}' playlist."
                )
