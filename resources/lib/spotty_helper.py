import os
import platform
import stat
import subprocess

import xbmc
import xbmcvfs
from xbmc import LOGERROR

from utils import log_msg, log_exception, ADDON_DATA_PATH


class SpottyHelper:
    def __init__(self):
        self.spotty_binary_path = self.__get_spotty_path()
        self.spotty_cache_path = f"{ADDON_DATA_PATH}/spotty-cache"

    @staticmethod
    def __get_spotty_path():
        """find the correct spotty binary belonging to the platform"""
        spotty_path = None
        if xbmc.getCondVisibility("System.Platform.Windows"):
            spotty_path = os.path.join(
                os.path.dirname(__file__), "deps/spotty", "windows", "spotty.exe"
            )
        elif xbmc.getCondVisibility("System.Platform.OSX"):
            spotty_path = os.path.join(os.path.dirname(__file__), "deps/spotty", "macos", "spotty")
        elif xbmc.getCondVisibility("System.Platform.Linux + !System.Platform.Android"):
            architecture = platform.machine()
            log_msg(f"Reported architecture: '{architecture}'.")
            if architecture.startswith("AMD64") or architecture.startswith("x86_64"):
                # Generic linux x86_64 binary.
                spotty_path = os.path.join(
                    os.path.dirname(__file__), "deps/spotty", "x86-linux", "spotty-x86_64"
                )
            else:
                # When we're unsure about the platform/cpu, try by testing to get
                # the correct binary path.
                paths = [
                    os.path.join(
                        os.path.dirname(__file__), "deps/spotty", "arm-linux", "spotty-hf"
                    ),
                    os.path.join(os.path.dirname(__file__), "deps/spotty", "x86-linux", "spotty"),
                ]
                for binary_path in paths:
                    if SpottyHelper.__test_spotty(binary_path):
                        spotty_path = binary_path
                        break

        if not spotty_path:
            log_msg(
                "Spotty: failed to detect architecture or platform not supported!"
                " Local playback will not be available.",
                loglevel=LOGERROR,
            )
            return None

        st = os.stat(spotty_path)
        os.chmod(spotty_path, st.st_mode | stat.S_IEXEC)
        log_msg(f"Spotty architecture detected. Using spotty binary '{spotty_path}'.")

        return spotty_path

    @classmethod
    def __test_spotty(cls, binary_path):
        """self-test spotty binary"""
        try:
            st = os.stat(binary_path)
            os.chmod(binary_path, st.st_mode | stat.S_IEXEC)
            args = [binary_path, "--name", "selftest", "--disable-discovery", "-x", "-v"]
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            spotty = subprocess.Popen(
                args,
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )

            stdout, stderr = spotty.communicate()

            log_msg(stdout)

            if "ok spotty".encode(encoding="UTF-8") in stdout:
                return True

            if xbmc.getCondVisibility("System.Platform.Windows"):
                log_msg(
                    "Unable to initialize spotty binary for playback."
                    "Make sure you have the VC++ 2015 runtime installed.",
                    LOGERROR,
                )

        except Exception:
            log_exception("Test spotty binary error")

        return False

    @staticmethod
    def get_username():
        username = ""

        cred_file = xbmcvfs.translatePath(f"{ADDON_DATA_PATH}/credentials.json")

        if xbmcvfs.exists(cred_file):
            with open(cred_file) as cred_file:
                data = cred_file.read()
                data = eval(data)
                username = data["username"]

        return username
