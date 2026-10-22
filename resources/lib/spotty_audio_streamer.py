import struct
import subprocess
import threading
from io import BytesIO
from typing import Callable, Iterator, Union

import xbmc
from xbmc import LOGDEBUG, LOGWARNING, LOGERROR

from spotty import Spotty
from utils import ADDON_ID, bytes_to_megabytes, log_msg, log_exception

SPOTIFY_TRACK_PREFIX = "spotify:track:"
# Small chunks so data (and the HTTP headers) reach Kodi quickly.
SPOTTY_AUDIO_CHUNK_SIZE = 64 * 1024

SPOTIFY_BITRATE = "320"
SPOTTY_INITIAL_VOLUME = "50"
SPOTTY_GAIN_TYPE = "track"
SPOTTY_STREAMING_DEFAULT_ARGS = [
    "--disable-audio-cache",
    "--disable-discovery",
    "--bitrate",
    SPOTIFY_BITRATE,
    "--initial-volume",
    SPOTTY_INITIAL_VOLUME,
]
SPOTTY_STREAMING_NORMALIZATION_ARGS = [
    "--enable-volume-normalisation",
    "--normalisation-gain-type",
    SPOTTY_GAIN_TYPE,
]

SAMPLE_RATE = 44100
NUM_CHANNELS = 2
BITS_PER_SAMPLE = 16
BLOCK_ALIGN = NUM_CHANNELS * (BITS_PER_SAMPLE // 8)
BYTES_PER_SECOND = SAMPLE_RATE * BLOCK_ALIGN

# If spotty dies before the track is complete, restart it at the current position.
MAX_SPOTTY_RESTARTS = 3
# If spotty finishes only slightly short of the length announced in the wav header
# (Spotify's duration metadata is not sample exact), pad with silence instead of
# closing the connection early. An early close makes Kodi reconnect or skip the track.
MAX_SILENCE_PADDING_BYTES = 5 * BYTES_PER_SECOND


class SpottyAudioStreamer:
    """Streams one track, or a byte range of it, as a wav file.
    Use one instance per HTTP request so concurrent requests can't corrupt each other."""

    def __init__(self, spotty: Spotty, track_id: str, track_duration: float, use_normalization):
        self.__spotty = spotty
        self.__track_id = track_id
        self.__track_duration = track_duration
        self.__use_normalization = use_normalization

        self.__wav_header, self.__track_length = self.__create_wav_header()

        self.__lock = threading.Lock()
        self.__spotty_process: Union[subprocess.Popen, None] = None
        self.__terminated = False

    def get_track_id(self) -> str:
        return self.__track_id

    def get_track_length(self) -> int:
        return self.__track_length

    def terminate_stream(self) -> bool:
        with self.__lock:
            self.__terminated = True
            spotty_process = self.__spotty_process
        if not spotty_process:
            return False
        self.__stop_spotty(spotty_process)
        return True

    def send_part_audio_stream(
        self,
        range_begin: int,
        range_len: int,
        notify_track_finished: Callable[[str], None] = lambda x: None,
    ) -> Iterator[bytes]:
        """Chunked transfer of audio data from spotty binary"""

        bytes_sent = 0
        try:
            self.__log_start_transfer(range_begin)

            # Send the (rest of the) wav header.
            header_len = len(self.__wav_header)
            if range_begin < header_len:
                header_part = self.__wav_header[range_begin : range_begin + range_len]
                bytes_sent = len(header_part)
                self.__log_send_wav_header()
                yield header_part

            # Position in the raw PCM data (after the wav header).
            audio_pos = max(0, range_begin - header_len)
            num_restarts = 0

            while (bytes_sent < range_len) and not self.__terminated:
                spotty_process = self.__start_spotty(audio_pos)
                if not spotty_process:
                    return
                try:
                    # Seek by whole seconds with spotty, discard the remainder.
                    self.__discard(spotty_process, audio_pos % BYTES_PER_SECOND)

                    while bytes_sent < range_len:
                        frame = spotty_process.stdout.read(
                            min(SPOTTY_AUDIO_CHUNK_SIZE, range_len - bytes_sent)
                        )
                        if self.__terminated:
                            return
                        if not frame:
                            break

                        bytes_sent += len(frame)
                        audio_pos += len(frame)
                        self.__log_continue_sending(bytes_sent, len(frame), range_len)
                        yield frame
                finally:
                    self.__stop_spotty(spotty_process)

                if (bytes_sent >= range_len) or self.__terminated:
                    break

                bytes_left = range_len - bytes_sent
                if bytes_left <= MAX_SILENCE_PADDING_BYTES:
                    log_msg(
                        f"Spotty finished {bytes_left} bytes short for track"
                        f" '{self.__track_id}'. Padding with silence.",
                        LOGDEBUG,
                    )
                    while bytes_left > 0:
                        silence = bytes(min(SPOTTY_AUDIO_CHUNK_SIZE, bytes_left))
                        bytes_left -= len(silence)
                        bytes_sent += len(silence)
                        yield silence
                    break

                num_restarts += 1
                if num_restarts > MAX_SPOTTY_RESTARTS:
                    log_msg(
                        f"Spotty stopped early for track '{self.__track_id}'"
                        f" at {self.__get_mb_str(bytes_sent)} and could not be restarted.",
                        LOGERROR,
                    )
                    break
                log_msg(
                    f"Spotty stopped early for track '{self.__track_id}'"
                    f" at audio position {audio_pos / BYTES_PER_SECOND:.1f}s."
                    f" Restarting spotty (attempt {num_restarts}).",
                    LOGWARNING,
                )

            self.__log_finished_sending(range_begin, bytes_sent)

        except Exception as ex:
            self.__log_exception_sending(ex, range_begin, bytes_sent)
            return

        if (bytes_sent >= range_len) and not self.__terminated:
            try:
                notify_track_finished(self.__track_id)
            except Exception as ex:
                log_exception(ex, f"Track finished notification failed for '{self.__track_id}'")

    def __start_spotty(self, audio_pos: int) -> Union[subprocess.Popen, None]:
        track_id_uri = SPOTIFY_TRACK_PREFIX + self.__track_id
        start_secs = audio_pos // BYTES_PER_SECOND
        self.__log_start_reading_audio(track_id_uri, start_secs)

        args = SPOTTY_STREAMING_DEFAULT_ARGS.copy()
        if self.__use_normalization:
            args += SPOTTY_STREAMING_NORMALIZATION_ARGS
        if start_secs > 0:
            args += ["--start-position", str(start_secs)]
        args += ["--single-track", track_id_uri]

        with self.__lock:
            if self.__terminated:
                return None
            spotty_process = self.__spotty.run_spotty(args, stderr=subprocess.PIPE)
            self.__spotty_process = spotty_process

        threading.Thread(
            target=self.__log_spotty_output, args=(spotty_process,), daemon=True
        ).start()

        return spotty_process

    def __stop_spotty(self, spotty_process: subprocess.Popen) -> None:
        with self.__lock:
            if self.__spotty_process is spotty_process:
                self.__spotty_process = None
        try:
            if spotty_process.poll() is None:
                spotty_process.kill()
            spotty_process.wait(timeout=5)
        except Exception as ex:
            log_msg(f"Error stopping spotty: {ex}", LOGWARNING)

    @staticmethod
    def __discard(spotty_process: subprocess.Popen, num_bytes: int) -> None:
        while num_bytes > 0:
            data = spotty_process.stdout.read(min(SPOTTY_AUDIO_CHUNK_SIZE, num_bytes))
            if not data:
                return
            num_bytes -= len(data)

    def __log_spotty_output(self, spotty_process: subprocess.Popen) -> None:
        # Drain stderr so spotty can never block on a full pipe, and so its messages
        # (e.g., why a track stopped early) end up in the Kodi log.
        try:
            for line in spotty_process.stderr:
                line = line.decode(encoding="UTF-8", errors="replace").rstrip()
                if not line:
                    continue
                is_problem = (" ERROR " in line) or (" WARN " in line)
                xbmc.log(
                    f"{ADDON_ID}:spotty[{self.__track_id}]: {line}",
                    level=LOGWARNING if is_problem else LOGDEBUG,
                )
        except Exception:
            pass

    def __log_start_transfer(self, range_begin: int) -> None:
        log_msg(
            f"Start transfer for track '{self.__track_id}' - range begin: {range_begin}",
            LOGDEBUG,
        )
        log_msg(f"Use Spotify normalization: {self.__use_normalization}.", LOGDEBUG)

    def __log_send_wav_header(self) -> None:
        log_msg(
            f"Sending wav header for track '{self.__track_id}'.",
            LOGDEBUG,
        )

    def __log_start_reading_audio(self, track_id_uri: str, start_secs: int) -> None:
        log_msg(
            f"Start reading audio data for track: '{track_id_uri}' at {start_secs}s,"
            f" length = {self.__track_length} ({self.__get_mb_str(self.__track_length)}).",
            LOGDEBUG,
        )

    def __log_continue_sending(self, bytes_sent: int, frame_len: int, range_len: int) -> None:
        # Only log about every 10MB, otherwise the Kodi log gets flooded.
        log_every = 10 * 1024 * 1024
        if (bytes_sent // log_every) == ((bytes_sent - frame_len) // log_every):
            return
        log_msg(
            f"Continue sending track '{self.__track_id}'"
            f" - {self.__get_data_sent_str(bytes_sent, range_len)}.",
            LOGDEBUG,
        )

    def __log_finished_sending(self, range_begin: int, bytes_sent: int) -> None:
        log_msg(
            f"Finished sending track '{self.__track_id}'"
            f" - range begin {range_begin}"
            f" - bytes sent {bytes_sent} - {self.__get_mb_str(bytes_sent)}"
            f" - terminated: {self.__terminated}.",
            LOGDEBUG,
        )

    def __log_exception_sending(self, ex: Exception, range_begin: int, bytes_sent: int) -> None:
        log_msg(
            f"EXCEPTION sending track '{self.__track_id}'"
            f" - range begin {range_begin}"
            f" - bytes sent {bytes_sent} - {self.__get_mb_str(bytes_sent)}.",
            LOGERROR,
        )
        log_msg(f"Exception: {ex}")

    @staticmethod
    def __get_mb_str(data_bytes: int) -> str:
        data_mb = bytes_to_megabytes(data_bytes)
        return f"{data_mb:.1f}MB"

    @staticmethod
    def __get_data_sent_str(data_bytes: int, total_len: int) -> str:
        data_mb = bytes_to_megabytes(data_bytes)
        percent = int(100.0 * float(data_bytes) / float(max(1, total_len)))
        return f"sent so far: {data_mb:>5.1f}MB ({percent:>3}%)"

    def __create_wav_header(self):
        """generate a wav header for the stream"""
        log_msg(f"Start getting wav header. Duration = {self.__track_duration}", LOGDEBUG)
        file = BytesIO()
        # Don't truncate to whole seconds, otherwise up to a second at the end is lost.
        num_samples = int(round(SAMPLE_RATE * self.__track_duration))

        # Generate format chunk.
        format_chunk_spec = "<4sLHHLLHH"
        format_chunk = struct.pack(
            format_chunk_spec,
            "fmt ".encode(encoding="UTF-8"),  # Chunk id
            16,  # Size of this chunk (excluding chunk id and this field)
            1,  # Audio format, 1 for PCM
            NUM_CHANNELS,  # Number of channels
            SAMPLE_RATE,  # Samplerate, 44100, 48000, etc.
            BYTES_PER_SECOND,  # Byterate
            BLOCK_ALIGN,  # Blockalign
            BITS_PER_SAMPLE,  # 16 bits for two byte samples, etc.
        )

        # Generate data chunk.
        data_chunk_spec = "<4sL"
        data_size = num_samples * BLOCK_ALIGN
        data_chunk = struct.pack(
            data_chunk_spec,
            "data".encode(encoding="UTF-8"),  # Chunk id
            data_size,  # Chunk size (excluding chunk id and this field)
        )
        sum_items = [
            # "WAVE" string following size field
            4,
            # "fmt " + chunk size field + chunk size
            struct.calcsize(format_chunk_spec),
            # Size of data chunk spec + data size
            struct.calcsize(data_chunk_spec) + data_size,
        ]

        # Generate main header.
        all_chunks_size = int(sum(sum_items))
        main_header_spec = "<4sL4s"
        main_header = struct.pack(
            main_header_spec,
            "RIFF".encode(encoding="UTF-8"),
            all_chunks_size,
            "WAVE".encode(encoding="UTF-8"),
        )

        # Write all the contents in.
        file.write(main_header)
        file.write(format_chunk)
        file.write(data_chunk)

        return file.getvalue(), all_chunks_size + 8
