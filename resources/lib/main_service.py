"""
    plugin.audio.spotify
    Spotify player for Kodi
    main_service.py
    Background service which launches the spotty binary and monitors the player.
"""

import time
from typing import Dict

import xbmc
import xbmcaddon
from xbmc import LOGDEBUG

import bottle_manager
import utils
from http_spotty_audio_streamer import HTTPSpottyAudioStreamer
from save_recently_played import SaveRecentlyPlayed
from spotty import Spotty
from spotty_auth import SpottyAuth
from spotty_helper import SpottyHelper
from utils import PROXY_PORT, log_msg, ADDON_ID

SAVE_TO_RECENTLY_PLAYED_FILE = True


def abort_app(timeout_in_secs: int) -> bool:
    return xbmc.Monitor().waitForAbort(timeout_in_secs)


class MainService:
    def __init__(self):
        log_msg(f"Spotify plugin version: {xbmcaddon.Addon(id=ADDON_ID).getAddonInfo('version')}.")

        self.__spotty_helper: SpottyHelper = SpottyHelper()

        spotty = Spotty()
        spotty.set_spotty_paths(
            self.__spotty_helper.spotty_binary_path, self.__spotty_helper.spotty_cache_path
        )
        spotty.set_spotify_user(
            self.__spotty_helper.spotify_username, self.__spotty_helper.spotify_password
        )

        self.__spotty_auth: SpottyAuth = SpottyAuth(spotty)
        self.__auth_token: Dict[str, str] = dict()

        addon = xbmcaddon.Addon(id=ADDON_ID)
        gap_between_tracks = int(addon.getSetting("gap_between_playlist_tracks"))
        self.__http_spotty_streamer: HTTPSpottyAudioStreamer = HTTPSpottyAudioStreamer(
            spotty, gap_between_tracks
        )
        self.__save_recently_played: SaveRecentlyPlayed = SaveRecentlyPlayed()
        self.__http_spotty_streamer.set_notify_track_finished(self.__save_track_to_recently_played)

        bottle_manager.route_all(self.__http_spotty_streamer)

    def __save_track_to_recently_played(self, track_id: str) -> None:
        if SAVE_TO_RECENTLY_PLAYED_FILE:
            self.__save_recently_played.save_track(track_id)

    def run(self) -> None:
        log_msg("Starting main service loop.")

        bottle_manager.start_thread(PROXY_PORT)
        log_msg(f"Started bottle with port {PROXY_PORT}.")

        self.__renew_token()

        loop_counter = 0
        loop_wait_in_secs = 6
        while True:
            loop_counter += 1
            if (loop_counter % 10) == 0:
                log_msg(f"Main loop continuing. Loop counter: {loop_counter}.")

            # Monitor authorization.
            if (int(self.__auth_token["expires_at"]) - 60) <= (int(time.time())):
                expire_time = self.__auth_token["expires_at"]
                time_now = int(time.time())
                log_msg(f"Spotify token expired. Expire time: {expire_time}; time now: {time_now}.")
                log_msg("Refreshing auth token now.")
                self.__renew_token()

            if abort_app(loop_wait_in_secs):
                break

        self.__close()

    def __close(self) -> None:
        log_msg("Shutdown requested.")
        self.__http_spotty_streamer.stop()
        self.__spotty_helper.kill_all_spotties()
        bottle_manager.stop_thread()
        log_msg("Main service stopped.")

    def __renew_token(self) -> None:
        log_msg("Retrieving auth token....", LOGDEBUG)
        auth_token = self.__spotty_auth.get_token()
        if not auth_token:
            utils.cache_auth_token("")
            raise Exception("Could not get Spotify auth token.")

        self.__auth_token = auth_token
        expire_time = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(float(self.__auth_token["expires_at"]))
        )
        log_msg(f"Retrieved Spotify auth token. Expires at {expire_time}.")

        # Cache auth token for easy access by the plugin.
        utils.cache_auth_token(self.__auth_token["access_token"])
