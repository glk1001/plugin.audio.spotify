import time
from typing import Dict

from spotty import Spotty
from utils import log_msg, log_exception, LOGDEBUG

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
    "user-read-birthdate",
    "user-top-read",
]


class SpottyAuth:
    def __init__(self, spotty: Spotty):
        self.__spotty = spotty

    def get_token(self) -> Dict[str, str]:
        token_info = None

        try:
            args = [
                "--get-token",
                "--client-id",
                CLIENT_ID,
                "--scope",
                ",".join(SPOTTY_SCOPE),
            ]
            spotty = self.__spotty.run_spotty(extra_args=args, use_creds=True)

            # done = Event()
            # watcher = Thread(target=kill_on_timeout, args=(done, 5, spotty))
            # watcher.daemon = True
            # watcher.start()

            stdout, stderr = spotty.communicate()
            #            done.set()

            log_msg(f"Spotty stdout: {stdout}")
            result = None
            for line in stdout.decode("utf-8").split():
                line = line.strip()
                if line.startswith('{"accessToken"'):
                    result = eval(line)

            # Transform token info to spotipy compatible format.
            if result:
                token_info = {
                    "access_token": result["accessToken"],
                    "expires_in": result["expiresIn"],
                    "expires_at": int(time.time()) + result["expiresIn"],
                    "refresh_token": result["accessToken"],
                }
                log_msg(f"Token: {token_info}", LOGDEBUG)
        except Exception as exc:
            log_exception(exc, "Get Spotify token error")

        return token_info
