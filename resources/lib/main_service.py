"""
    plugin.audio.spotify
    Spotify player for Kodi
    main_service.py
    Background service which launches the spotty binary and monitors the player.
"""

import time

import xbmc
import xbmcaddon

import utils
from httpproxy import ProxyRunner
from spotty import Spotty
from spotty_audio_streamer import SpottyAudioStreamer
from spotty_auth import SpottyAuth
from spotty_helper import SpottyHelper
from utils import log_msg, ADDON_ID


class MainService:
    def __init__(self):
        log_msg(f"Spotify plugin version: {xbmcaddon.Addon(id=ADDON_ID).getAddonInfo('version')}.")

        self.__spotty_helper = SpottyHelper()

        spotty = Spotty()
        spotty.set_spotty_paths(
            self.__spotty_helper.spotty_binary_path, self.__spotty_helper.spotty_cache_path
        )
        spotty.set_spotify_user(
            self.__spotty_helper.spotify_username, self.__spotty_helper.spotify_password
        )

        self.__spotty_streamer = SpottyAudioStreamer(spotty)

        self.__spotty_auth = SpottyAuth(spotty)
        self.__auth_token = None

        self.__proxy_runner = ProxyRunner(self.__spotty_streamer)

        self.__kodimonitor = xbmc.Monitor()

    def run(self):
        log_msg("Starting main service loop.")

        self.__proxy_runner.start()
        log_msg(f"Started web proxy at port {self.__proxy_runner.get_port()}.")

        self.__renew_token()

        loop_counter = 0
        loop_wait_in_secs = 6
        while True:
            loop_counter += 1
            if (loop_counter % 10) == 0:
                log_msg(f"Main loop continuing. Loop counter: {loop_counter}.")

            # Monitor authorization.
            if (self.__auth_token["expires_at"] - 60) <= (int(time.time())):
                expire_time = self.__auth_token["expires_at"]
                time_now = int(time.time())
                log_msg(f"Spotify token expired. Expire time: {expire_time}; time now: {time_now}.")
                log_msg("Refreshing auth token now.")
                self.__renew_token()
                xbmc.executebuiltin("Container.Refresh")  # ???????????

            if self.__kodimonitor.waitForAbort(loop_wait_in_secs):
                break

        self.__close()

    def __close(self):
        log_msg("Shutdown requested!")
        self.__spotty_helper.kill_all_spotties()
        self.__proxy_runner.stop()
        log_msg("Main service stopped.")

    def __renew_token(self):
        log_msg("Retrieving auth token....", xbmc.LOGDEBUG)
        auth_token = self.__spotty_auth.get_token()
        if not auth_token:
            raise Exception("Could not get Spotify auth token.")

        self.__auth_token = auth_token
        expire_time = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(float(self.__auth_token["expires_at"]))
        )
        log_msg(f"Retrieved Spotify auth token. Expires at {expire_time}.")

        # Cache auth token for easy access by the plugin.
        utils.cache_auth_token(self.__auth_token["access_token"])
