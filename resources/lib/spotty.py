import os
import subprocess
from typing import Dict, List

import xbmc
from xbmc import LOGDEBUG, LOGERROR

from spotty_helper import SpottyHelper
from utils import log_msg, ADDON_DATA_PATH

SPOTTY_PLAYER_NAME = "Kodi-Spotty"
SPOTTY_DEFAULT_ARGS = [
    "--verbose",
    "--name",
    SPOTTY_PLAYER_NAME,
]
SPOTTY_TOKEN_FILE = "spotty-token"
SPOTTY_CACHE_DIR_NAME = "spotty-cache"
SPOTTY_CACHE_DIR = os.path.join(ADDON_DATA_PATH, SPOTTY_CACHE_DIR_NAME)
SPOTTY_CREDENTIALS_FILENAME = "credentials.json"
SPOTTY_CREDENTIALS_BACKUP_FILENAME = "credentials.json.bak"


class Spotty:
    def __init__(self):
        self.__spotty_binary = ""
        self.__spotty_cache = SPOTTY_CACHE_DIR
        self.__spotify_username = ""
        self.__spotify_password = ""
        self.__spotty_rust_env = None

        self.__playback_supported = True

    def set_spotty_path(self, spotty_binary: str) -> None:
        self.__spotty_binary = spotty_binary

        if self.__spotty_binary:
            self.__playback_supported = True
            xbmc.executebuiltin("SetProperty(spotify.supportsplayback, true, Home)")
        else:
            self.__playback_supported = False
            log_msg("Error while verifying spotty. Local playback is disabled.", loglevel=LOGERROR)

    def set_spotty_env(self, env: Dict[str, str]):
        self.__spotty_rust_env = env

    def get_spotty_token_file(self) -> str:
        return os.path.join(self.__spotty_cache, SPOTTY_TOKEN_FILE)

    def get_spotty_credentials_file(self) -> str:
        return os.path.join(self.__spotty_cache, SPOTTY_CREDENTIALS_FILENAME)

    def get_spotty_credentials_backup_file(self) -> str:
        return os.path.join(self.__spotty_cache, SPOTTY_CREDENTIALS_BACKUP_FILENAME)

    def run_spotty(self, extra_args: List[str] = None) -> subprocess.Popen:
        log_msg("Running spotty...", LOGDEBUG)

        try:
            # os.environ["RUST_LOG"] = "debug"
            args = [
                self.__spotty_binary,
                "--cache",
                self.__spotty_cache,
            ] + SPOTTY_DEFAULT_ARGS

            if extra_args:
                args += extra_args

            loggable_args = args.copy()

            log_msg(f"Spotty args: {' '.join(loggable_args)}", LOGDEBUG)

            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            return subprocess.Popen(
                args,
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self.__spotty_rust_env,
            )
        except Exception as ex:
            raise Exception(f"Run spotty error: {ex}")


def get_spotty(spotty_helper: SpottyHelper) -> Spotty:
    spotty = Spotty()
    spotty.set_spotty_path(spotty_helper.spotty_binary_path)
    spotty.set_spotty_env(spotty_helper.spotty_rust_env)

    return spotty
