import os
import subprocess

import xbmc
from xbmc import LOGERROR

from utils import log_msg, log_exception

SPOTTY_PLAYER_NAME = "temp-spotty"
SPOTTY_DEFAULT_ARGS = [
    "--verbose",
    "--enable-audio-cache",
    "--name",
    SPOTTY_PLAYER_NAME,
]


class Spotty(object):
    """
    Spotty is wrapped into a separate class to store common properties.
    This is done to prevent hitting a kodi issue where calling one of the
    infolabel methods at playback time causes a crash of the playback.
    """

    def __init__(self):
        self.spotty_binary = None
        self.spotty_cache = None
        self.spotify_username = ""
        self.spotify_password = ""

        self.playback_supported = True

    def set_spotty_paths(self, spotty_binary: str, spotty_cache: str) -> None:
        self.spotty_binary = spotty_binary
        self.spotty_cache = spotty_cache

        if self.spotty_binary:
            self.playback_supported = True
            xbmc.executebuiltin("SetProperty(spotify.supportsplayback, true, Home)")
        else:
            self.playback_supported = False
            log_msg("Error while verifying spotty. Local playback is disabled.", loglevel=LOGERROR)

    def set_spotify_user(self, username: str, password: str) -> None:
        self.spotify_username = username
        self.spotify_password = password

    def run_spotty(self, extra_args=None, use_creds=False, ap_port="54443"):
        """on supported platforms we include the spotty binary"""
        try:
            # os.environ["RUST_LOG"] = "debug"
            args = [
                self.spotty_binary,
                "--cache",
                self.spotty_cache,
                "--ap-port",
                ap_port,
            ] + SPOTTY_DEFAULT_ARGS

            if extra_args:
                args += extra_args

            loggable_args = args.copy()

            if use_creds:
                args += ["-u", self.spotify_username, "-p", self.spotify_password]
                loggable_args += ["-u", self.spotify_username, "-p", "****"]

            log_msg("run_spotty args: %s" % " ".join(loggable_args))

            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            return subprocess.Popen(
                args, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        except Exception:
            log_exception("Run spotty error")

        return None

    def kill_spotty(self):
        """make sure we don't have any (remaining) spotty processes running before we start one"""
        if xbmc.getCondVisibility("System.Platform.Windows"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(["taskkill", "/IM", "spotty.exe"], startupinfo=startupinfo, shell=True)
        else:
            if self.spotty_binary is not None:
                sp_binary_file = os.path.basename(self.spotty_binary)
                os.system("killall " + sp_binary_file)
