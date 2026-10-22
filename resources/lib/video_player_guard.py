"""
    plugin.audio.spotify
    Spotify player for Kodi
    video_player_guard.py
    Restarts a track that Kodi opened in a running video player.
"""

import sys
from typing import Callable, Optional, Tuple

import xbmc

from utils import ADDON_ID, PROXY_PORT, log_msg

TRACK_URL_PREFIX = f"http://localhost:{PROXY_PORT}/track/"
RESTART_TRACK_ACTION = "restart_track"
# Kodi drops a play request while the stopped player is still closing
PLAY_DELAY_SECS = 0.5


class VideoPlayerGuard(xbmc.Player):
    """
    Tracks are played by the VideoPlayer (see http_video_player_setter.py). If a
    track is started while a video is playing, e.g. from the menu or a remote
    app, Kodi opens it in the running video player, which keeps behaving as if a
    video was playing (fullscreen video window, video OSD, refresh rate of the
    video). Playing a playlist stops the video beforehand, every other way of
    starting a track is caught here: the track is restarted in a new player.

    The order matters: Kodi does not open a track again while its stream is
    still sent to the old player, and the old player reconnects if the stream is
    stopped first. So the player is stopped, then the stream, and then the track
    is played again by a script, as this service has to keep serving streams
    while Kodi opens the track.
    """

    def __init__(self, stop_streaming: Callable[[], None]):
        super().__init__()
        self.__stop_streaming = stop_streaming
        self.__pending: Optional[Tuple[str, int]] = None

    def onAVStarted(self):
        if self.__pending or not xbmc.getCondVisibility("Player.HasVideo"):
            return
        try:
            path = self.getPlayingFile()
        except RuntimeError:
            return
        if not path.startswith(TRACK_URL_PREFIX):
            return
        log_msg(f"Track '{path}' was opened in the video player, restarting it.")
        playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        position = playlist.getposition()
        if not (0 <= position < playlist.size() and playlist[position].getPath() == path):
            position = -1
        self.__pending = (path, position)
        xbmc.executebuiltin("PlayerControl(Stop)")

    def onPlayBackStopped(self):
        self.__restart()

    def onPlayBackEnded(self):
        self.__restart()

    def onPlayBackError(self):
        self.__restart()

    def __restart(self) -> None:
        if not self.__pending:
            return
        path, position = self.__pending
        self.__pending = None
        self.__stop_streaming()
        xbmc.executebuiltin(f"RunScript({ADDON_ID},{RESTART_TRACK_ACTION},{position},{path})")


def restart_track() -> None:
    """Called by RunScript(plugin.audio.spotify,restart_track,<position>,<path>)"""
    try:
        position = int(sys.argv[2])
        path = sys.argv[3]
    except (IndexError, ValueError):
        return
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(PLAY_DELAY_SECS) or xbmc.getCondVisibility("Player.HasMedia"):
        # the user started something else meanwhile
        return
    playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
    if 0 <= position < playlist.size() and playlist[position].getPath() == path:
        xbmc.Player().play(playlist, startpos=position)
    else:
        xbmc.Player().play(path)
