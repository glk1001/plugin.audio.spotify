import xbmc
import xbmcaddon

import spotipy
import utils
from utils import log_msg, ADDON_ID

ADDON_SETTING_MY_RECENTLY_PLAYED_PLAYLIST_NAME = "my_recently_played_playlist_name"


class SaveRecentlyPlayed:
    def __init__(self):
        self.__spotipy = None
        self.__my_recently_played_playlist_id = None

    def save_track(self, track_id: str) -> None:
        my_recently_played_playlist_name = self.__get_my_recently_played_playlist_name()
        if not my_recently_played_playlist_name:
            return

        if not self.__my_recently_played_playlist_id:
            self.__set_my_recently_played_playlist_id()

        self.__spotipy.playlist_add_items(self.__my_recently_played_playlist_id, [track_id])
        log_msg(
            f"Saved track '{track_id}' to '{my_recently_played_playlist_name}' playlist.",
            xbmc.LOGINFO,
        )

    @staticmethod
    def __get_my_recently_played_playlist_name() -> str:
        setting = xbmcaddon.Addon(id=ADDON_ID).getSetting(
            ADDON_SETTING_MY_RECENTLY_PLAYED_PLAYLIST_NAME
        )
        if setting.upper() == "NONE":
            setting = ""
        return setting

    def __set_my_recently_played_playlist_id(self) -> None:
        my_recently_played_playlist_name = self.__get_my_recently_played_playlist_name()

        self.__spotipy = spotipy.Spotify(auth=utils.get_cached_auth_token())
        log_msg(f"Getting id for '{my_recently_played_playlist_name}' playlist.", xbmc.LOGDEBUG)
        self.__my_recently_played_playlist_id = utils.get_user_playlist_id(
            self.__spotipy, my_recently_played_playlist_name
        )

        if not self.__my_recently_played_playlist_id:
            log_msg(
                f"Did not find a '{my_recently_played_playlist_name}' playlist."
                " Creating one now.",
                xbmc.LOGINFO,
            )
            userid = self.__spotipy.me()["id"]
            playlist = self.__spotipy.user_playlist_create(
                userid, my_recently_played_playlist_name, False
            )
            self.__my_recently_played_playlist_id = playlist["id"]

            if not self.__my_recently_played_playlist_id:
                raise Exception(
                    f"Could not create a '{my_recently_played_playlist_name}' playlist."
                )
