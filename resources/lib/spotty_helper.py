import os
import platform
import shutil
import stat
import subprocess
from typing import Union

import xbmc
from xbmc import LOGERROR

from utils import log_msg, log_exception

# IMPORTANT: To allow 'spotty' to run on Android, we need to run it from the
#            kodi package's internal writeable directory. Same with temp files
#            - they need to be written to the same directory.
KODI_ANDROID_INTERNAL_WRITABLE_DIR = "/data/data/org.xbmc.kodi"
SPOTTY_SUBDIR = "deps/spotty"


class SpottyHelper:
    def __init__(self):
        self.spotty_binary_path = self.__get_spotty_path()

        self.spotty_rust_env = os.environ.copy()
        if xbmc.getCondVisibility("System.Platform.Android"):
            self.spotty_rust_env["TMPDIR"] = KODI_ANDROID_INTERNAL_WRITABLE_DIR

    def kill_all_spotties(self) -> None:
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(["taskkill", "/IM", "spotty.exe"], startupinfo=startupinfo, shell=True)
        else:
            sp_binary_file = os.path.basename(self.spotty_binary_path)
            os.system("killall --quiet " + sp_binary_file)

    @staticmethod
    def __get_spotty_path() -> Union[str, None]:
        """find the correct spotty binary belonging to the platform"""
        spotty_path = None
        if xbmc.getCondVisibility("System.Platform.Windows"):
            spotty_path = os.path.join(
                os.path.dirname(__file__), SPOTTY_SUBDIR, "windows", "spotty.exe"
            )
        elif xbmc.getCondVisibility("System.Platform.OSX"):
            spotty_path = os.path.join(os.path.dirname(__file__), SPOTTY_SUBDIR, "macos", "spotty")
        elif xbmc.getCondVisibility("System.Platform.Android"):
            spotty_path = SpottyHelper.__get_android_spotty_path()
        elif xbmc.getCondVisibility("System.Platform.Linux"):
            spotty_path = SpottyHelper.__get_linux_spotty_path()

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

    @staticmethod
    def __get_android_spotty_path() -> Union[str, None]:
        spotty_path = None

        # Try by testing to get the correct binary path.
        candidate_paths = [
            ("arm-android", "spotty"),
            ("arm-android", "spotty-aarch64"),
            ("x86-android", "spotty"),
            ("x86-android", "spotty-x86_64"),
        ]
        for path in candidate_paths:
            binary = os.path.join(os.path.dirname(__file__), SPOTTY_SUBDIR, path[0], path[1])
            test_binary = os.path.join(KODI_ANDROID_INTERNAL_WRITABLE_DIR, "spotty")
            shutil.copyfile(binary, test_binary)
            os.chmod(test_binary, stat.S_IRWXU + stat.S_IRWXG + stat.S_IRWXO)
            if SpottyHelper.__test_spotty(test_binary):
                spotty_path = test_binary
                log_msg(f"Found candidate spotty path: '{binary}'.")
                break
            os.remove(test_binary)

        return spotty_path

    @staticmethod
    def __get_linux_spotty_path() -> Union[str, None]:
        spotty_path = None

        architecture = platform.machine()
        log_msg(f"Reported architecture: '{architecture}'.")
        if architecture.startswith("AMD64") or architecture.startswith("x86_64"):
            # Generic linux x86_64 binary.
            spotty_path = os.path.join(
                os.path.dirname(__file__), SPOTTY_SUBDIR, "x86-linux", "spotty-x86_64"
            )
        else:
            # When we're unsure about the platform/cpu, try by testing to get
            # the correct binary path.
            candidate_paths = [
                ("arm-linux", "spotty-muslhf"),
                ("arm-linux", "spotty"),
                ("x86-linux", "spotty"),
            ]
            for path in candidate_paths:
                binary = os.path.join(os.path.dirname(__file__), SPOTTY_SUBDIR, path[0], path[1])
                if SpottyHelper.__test_spotty(binary):
                    spotty_path = binary
                    break

        return spotty_path

    @classmethod
    def __test_spotty(cls, binary_path: str) -> bool:
        """self-test spotty binary"""
        try:
            st = os.stat(binary_path)
            os.chmod(binary_path, st.st_mode | stat.S_IEXEC)
            args = [binary_path, "--name", "selftest", "--disable-discovery", "-x", "-v"]
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            test_spotty = subprocess.Popen(
                args,
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )

            stdout, stderr = test_spotty.communicate()

            log_msg(stdout.decode(encoding="UTF-8"))

            if "ok spotty".encode(encoding="UTF-8") in stdout:
                return True

            if xbmc.getCondVisibility("System.Platform.Windows"):
                log_msg(
                    "Unable to initialize spotty binary for playback."
                    "Make sure you have the VC++ 2015 runtime installed.",
                    LOGERROR,
                )

        except Exception as exc:
            log_exception(exc, "Test spotty binary error")

        return False
