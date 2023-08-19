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
from deps import spotipy
from httpproxy import ProxyRunner
from spotty import Spotty
from spotty_audio_streamer import SpottyAudioStreamer
from spotty_helper import SpottyHelper
from utils import log_msg, ADDON_ID, get_token


class MainService:
    """our main background service running the various threads"""

    def __init__(self):
        log_msg(f"Spotify plugin version: {xbmcaddon.Addon(id=ADDON_ID).getAddonInfo('version')}.")

        self.current_user = None
        self.auth_token = None
        self.addon = xbmcaddon.Addon(id=ADDON_ID)
        self.win = xbmcgui.Window(10000)
        self.kodimonitor = xbmc.Monitor()

        self.spotty_helper = SpottyHelper()
        self.spotty = Spotty()
        self.spotty.set_spotty_paths(
            self.spotty_helper.spotty_binary_path, self.spotty_helper.spotty_cache_path
        )
        # Use username/password login for spotty.
        addon = xbmcaddon.Addon(id=ADDON_ID)
        self.spotty.set_spotify_user(addon.getSetting("username"), addon.getSetting("password"))
        del addon
        self.spotty_streamer = SpottyAudioStreamer(self.spotty)

        # Spotipy and the webservice are always pre-started in the background.
        # The auth key for spotipy will be set afterward.
        # The webserver is also used for the authentication callbacks from the Spotify api.
        self.spotipy = spotipy.Spotify()

        self.proxy_runner = ProxyRunner(self.spotty_streamer)
        self.proxy_runner.start()
        log_msg(f"Started web proxy at port {self.proxy_runner.get_port()}.")

        # Authenticate at startup.
        self.__renew_token()

        # Start mainloop.
        self.__main_loop()

    def __main_loop(self):
        """main loop which keeps our threads alive and refreshes the token"""
        log_msg("Starting main loop.")
        loop_counter = 0
        loop_timer_in_secs = 6
        while not self.kodimonitor.waitForAbort(loop_timer_in_secs):
            loop_counter += 1
            if (loop_counter % 10) == 0:
                log_msg(f"Main loop continuing. Loop counter: {loop_counter}.")

            # Monitor authorization.
            if not self.auth_token:
                # We do not yet have a token.
                log_msg("Retrieving first token...")
                if self.__renew_token():
                    xbmc.executebuiltin("Container.Refresh")
            elif self.auth_token and (self.auth_token["expires_at"] - 60) <= (int(time.time())):
                expire_time = self.auth_token["expires_at"]
                time_now = int(time.time())
                log_msg(f"Token expire time: {expire_time}; time now: {time_now}.")
                log_msg("Refreshing token now.")
                self.__renew_token()

        # End of loop: we should exit.
        self.__close()

    def __close(self):
        """shutdown, perform cleanup"""
        log_msg("Shutdown requested!", xbmc.LOGINFO)
        self.spotty.kill_spotty()
        self.proxy_runner.stop()
        del self.addon
        del self.kodimonitor
        del self.win
        log_msg("Stopped.", xbmc.LOGINFO)

    def __renew_token(self):
        """refresh/retrieve the token"""

        result = False

        log_msg("Retrieving auth token....")
        auth_token = get_token(self.spotty)

        if auth_token:
            self.auth_token = auth_token
            expire_time = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.auth_token["expires_at"])
            )
            log_msg(f"Retrieved auth token. Expires at {expire_time}.")
            # Only update token info in spotipy object.
            self.spotipy._auth = auth_token["access_token"]
            self.current_user = self.spotipy.me()["id"]
            log_msg(f"Logged into Spotify - Username: {self.current_user}", xbmc.LOGINFO)
            # Store auth_token and username as a window property for easy access by plugin entry.
            self.win.setProperty(utils.KODI_PROPERTY_SPOTIFY_TOKEN, auth_token["access_token"])
            self.win.setProperty(utils.KODI_PROPERTY_SPOTIFY_USERNAME, self.current_user)
            self.win.setProperty(utils.KODI_PROPERTY_SPOTIFY_COUNTRY, self.spotipy.me()["country"])
            result = True

        return result
