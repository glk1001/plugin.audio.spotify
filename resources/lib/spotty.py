import os
import subprocess
from typing import List

import xbmc
from xbmc import LOGDEBUG, LOGERROR

from utils import log_msg

SPOTTY_PORT = 54443
SPOTTY_PLAYER_NAME = "temp-spotty"
SPOTTY_DEFAULT_ARGS = [
    "--verbose",
    "--enable-audio-cache",
    "--name",
    SPOTTY_PLAYER_NAME,
]


class Spotty:
    def __init__(self):
        self.spotty_binary = ""
        self.spotty_cache = ""
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

    def run_spotty(
        self, extra_args: List[str] = None, use_creds: bool = False, ap_port: str = SPOTTY_PORT
    ) -> subprocess.Popen:
        log_msg("Running spotty...", LOGDEBUG)

        try:
            # os.environ["RUST_LOG"] = "debug"
            args = [
                self.spotty_binary,
                "--cache",
                self.spotty_cache,
                "--ap-port",
                str(ap_port),
            ] + SPOTTY_DEFAULT_ARGS

            if extra_args:
                args += extra_args

            loggable_args = args.copy()

            if use_creds:
                args += ["-u", self.spotify_username, "-p", self.spotify_password]
                loggable_args += ["-u", self.spotify_username, "-p", "****"]

            log_msg(f"Spotty args: {' '.join(loggable_args)}", LOGDEBUG)

            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            return subprocess.Popen(
                args, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        except Exception as ex:
            raise Exception(f"Run spotty error: {ex}")
