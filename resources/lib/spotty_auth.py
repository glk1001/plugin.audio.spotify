import json
import os
import subprocess
import time
from typing import Dict, Union

import xbmcaddon
from xbmc import LOGDEBUG, LOGERROR, LOGWARNING

import utils
from spotty import Spotty, SPOTTY_CACHE_DIR_NAME, SPOTTY_CREDENTIALS_FILENAME
from string_ids import AUTHENTICATE_FAILED_STR_ID, AUTHENTICATION_PROGRAM_FAILED_STR_ID
from utils import log_msg, log_exception, ADDON_ID

ZEROCONF_PORT = 10001

CLIENT_ID = "2eb96f9b37494be1824999d58028a305"
SPOTTY_SCOPE = [
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-modify-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-follow-modify",
    "user-follow-read",
    "user-library-read",
    "user-library-modify",
    "user-read-private",
    "user-read-email",
    "user-top-read",
]


class SpottyAuth:
    def __init__(self, spotty: Spotty):
        self.__spotty = spotty

    def start_zeroconf_authenticate(self) -> Union[None, subprocess.Popen]:
        try:
            if os.path.exists(self.__spotty.get_spotty_credentials_file()):
                os.replace(
                    self.__spotty.get_spotty_credentials_file(),
                    self.__spotty.get_spotty_credentials_backup_file(),
                )
                log_msg(
                    f"Moved credentials file to"
                    f' "{self.__spotty.get_spotty_credentials_backup_file()}"'
                )

            args = [
                "--zeroconf-port",
                str(ZEROCONF_PORT),
            ]
            return self.__spotty.run_spotty(extra_args=args)

        except Exception as exc:
            log_exception(exc, "Zeroconf authentication error")
            return None

    def zeroconf_authenticated_ok(self) -> bool:
        if os.path.exists(self.__spotty.get_spotty_credentials_file()):
            log_msg(
                f"Successfully authenticated. Credentials file created:"
                f' "{self.__spotty.get_spotty_credentials_file()}"'
            )
            return True

        log_msg(
            self.get_zeroconf_authentication_failed_msg(),
            loglevel=LOGERROR,
        )
        return False

    @staticmethod
    def get_zeroconf_program_failed_msg() -> str:
        return xbmcaddon.Addon(id=ADDON_ID).getLocalizedString(AUTHENTICATION_PROGRAM_FAILED_STR_ID)

    @staticmethod
    def get_zeroconf_authentication_failed_msg() -> str:
        msg = xbmcaddon.Addon(id=ADDON_ID).getLocalizedString(AUTHENTICATE_FAILED_STR_ID)
        cred_file = f"<ADDON_DATA_DIR>/{SPOTTY_CACHE_DIR_NAME}/{SPOTTY_CREDENTIALS_FILENAME}"
        return f'{msg}\n\n"{cred_file}".'

    def renew_token(self) -> None:
        log_msg("Retrieving auth token....", LOGDEBUG)

        auth_token = self.__get_retry_auth_token()
        if not auth_token:
            utils.cache_auth_token("")
            utils.cache_auth_token_expires_at("")
            raise Exception(
                f"Could not get Spotify auth token for" f" user '{utils.get_username()}'."
            )

        log_msg(
            f"Retrieved Spotify auth token."
            f" Expires at {utils.get_time_str(int(auth_token['expires_at']))}."
        )

        # Cache auth token for easy access by the plugin.
        utils.cache_auth_token(str(auth_token["access_token"]))
        utils.cache_auth_token_expires_at(str(auth_token["expires_at"]))

    def __get_retry_auth_token(self) -> Dict[str, str]:
        auth_token = None
        max_retries = 20
        count = 0
        while count < max_retries:
            auth_token = self.__get_token()
            if auth_token:
                break
            time.sleep(1)
            count += 1

        if count > 0:
            log_msg(f"Took {count} retries to get authorization token.", LOGWARNING)

        return auth_token

    def __get_token(self) -> Dict[str, str]:
        token_info = None

        try:
            args = [
                "--client-id",
                CLIENT_ID,
                "--scope",
                ",".join(SPOTTY_SCOPE),
                "--save-token",
                self.__spotty.get_spotty_token_file(),
            ]
            spotty = self.__spotty.run_spotty(extra_args=args)
            # done = Event()
            # watcher = Thread(target=kill_on_timeout, args=(done, 5, spotty))
            # watcher.daemon = True
            # watcher.start()

            stdout, stderr = spotty.communicate()
            # done.set()

            with open(self.__spotty.get_spotty_token_file()) as f:
                json_token = json.load(f)
            log_msg(f"Spotty json token: {json_token}")

            # Transform token info to spotipy compatible format.
            token_info = {
                "access_token": json_token["accessToken"],
                "expires_in": json_token["expiresIn"],
                "expires_at": int(time.time()) + json_token["expiresIn"],
                "refresh_token": json_token["accessToken"],
            }
            log_msg(f"Token: {token_info}", LOGDEBUG)

        except Exception as exc:
            log_exception(exc, "Get Spotify token error")

        return token_info
