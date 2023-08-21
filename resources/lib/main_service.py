#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
    plugin.audio.spotify
    Spotify player for Kodi
    main_service.py
    Background service which launches the spotty binary and monitors the player.
"""

import time

import xbmc
import xbmcaddon
import xbmcgui

import utils
from httpproxy import ProxyRunner
from spotty import Spotty
from spotty_audio_streamer import SpottyAudioStreamer
from spotty_helper import SpottyHelper
from utils import log_msg, ADDON_ID, get_token


class MainService:
    """our main background service running the various threads"""

    def __init__(self):
        log_msg(f"Spotify plugin version: {xbmcaddon.Addon(id=ADDON_ID).getAddonInfo('version')}.")

        self.__spotty_helper = SpottyHelper()
        self.__spotty = Spotty()
        self.__spotty.set_spotty_paths(
            self.__spotty_helper.spotty_binary_path, self.__spotty_helper.spotty_cache_path
        )
        # Use username/password login for spotty.
        addon = xbmcaddon.Addon(id=ADDON_ID)
        self.__spotty.set_spotify_user(addon.getSetting("username"), addon.getSetting("password"))
        self.__spotty_streamer = SpottyAudioStreamer(self.__spotty)

        self.__proxy_runner = ProxyRunner(self.__spotty_streamer)
        self.__proxy_runner.start()
        log_msg(f"Started web proxy at port {self.__proxy_runner.get_port()}.")

        self.__auth_token = None
        self.__win = xbmcgui.Window(10000)
        self.__kodimonitor = xbmc.Monitor()

    def run(self):
        """main loop which keeps our threads alive and refreshes the token"""
        log_msg("Starting main loop.")

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
                log_msg(f"Token expire time: {expire_time}; time now: {time_now}.")
                log_msg("Refreshing token now.")
                self.__renew_token()
                xbmc.executebuiltin("Container.Refresh")  # ???????????

            if self.__kodimonitor.waitForAbort(loop_wait_in_secs):
                break

        self.__close()

    def __close(self):
        log_msg("Shutdown requested!", xbmc.LOGINFO)
        self.__spotty.kill_spotty()
        self.__proxy_runner.stop()
        log_msg("Stopped.", xbmc.LOGINFO)

    def __renew_token(self):
        result = False

        log_msg("Retrieving auth token....")
        auth_token = get_token(self.__spotty)

        if auth_token:
            self.__auth_token = auth_token
            expire_time = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.__auth_token["expires_at"])
            )
            log_msg(f"Retrieved Spotify auth token. Expires at {expire_time}.")
            # Store auth token as a window property for easy access by plugin entry.
            self.__win.setProperty(utils.KODI_PROPERTY_SPOTIFY_TOKEN, auth_token["access_token"])
            result = True

        return result
