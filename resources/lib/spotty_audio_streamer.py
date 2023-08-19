# -*- coding: utf-8 -*-
import struct
from io import BytesIO

import xbmc

from spotty import Spotty
from utils import log_msg, log_exception

SPOTIFY_TRACK_PREFIX = "spotify:track:"
# SPOTTY_AUDIO_CHUNK_SIZE = 20*1024
SPOTTY_AUDIO_CHUNK_SIZE = 524288

SPOTIFY_BITRATE = "320"
SPOTTY_INITIAL_VOLUME = "50"
SPOTTY_GAIN_TYPE = "track"
SPOTTY_STREAMING_DEFAULT_ARGS = [
    "--bitrate",
    SPOTIFY_BITRATE,
    "--enable-volume-normalisation",
    "--normalisation-gain-type",
    SPOTTY_GAIN_TYPE,
    "--initial-volume",
    SPOTTY_INITIAL_VOLUME,
]


class SpottyAudioStreamer:
    def __init__(self, spotty: Spotty):
        self.spotty = spotty

        self.track_id: str = ""
        self.track_duration: int = 0
        self.wav_header: bytes = bytes()
        self.track_length = 0

    def set_track(self, track_id: str, track_duration: float) -> None:
        self.track_id = track_id
        self.track_duration = int(track_duration)
        self.wav_header, self.track_length = self.__create_wav_header()

    def send_audio_stream(self, range_len: int, range_l: int):
        """Chunked transfer of audio data from spotty binary"""
        self.kill_spotty()
        spotty_process = None

        bytes_sent = 0
        try:
            log_msg(f"Start transfer for track {self.track_id} - range: {range_l}", xbmc.LOGDEBUG)

            # Send the wav header.
            if range_l == 0:
                bytes_sent = len(self.wav_header)
                yield self.wav_header

            track_id_uri = SPOTIFY_TRACK_PREFIX + self.track_id

            # Execute the spotty process, then collect stdout.
            args = SPOTTY_STREAMING_DEFAULT_ARGS + [
                "--single-track",
                track_id_uri,
            ]
            spotty_process = self.spotty.run_spotty(args, use_creds=True)
            if not spotty_process.returncode:
                log_msg(f"returncode: {spotty_process.returncode}", xbmc.LOGERROR)

            log_msg(f"Reading track uri: {track_id_uri}, length = {range_len}", xbmc.LOGDEBUG)

            # Ignore the first x bytes to match the range request.
            if range_l != 0:
                spotty_process.stdout.read(range_l)

            # Loop as long as there's something to output.
            while bytes_sent < range_len:
                frame = spotty_process.stdout.read(SPOTTY_AUDIO_CHUNK_SIZE)
                if not frame:
                    log_msg("Nothing read from stdout.", xbmc.LOGERROR)
                    break

                bytes_sent += len(frame)
                log_msg(
                    f"Continuing transfer for track {self.track_id} - bytes written = {bytes_sent}",
                    xbmc.LOGDEBUG,
                )
                yield frame

            # All done.
            log_msg(
                f"FINISHED transfer for track {self.track_id}"
                f" - range {range_l} - bytes written {bytes_sent}.",
                xbmc.LOGDEBUG,
            )
        except Exception:
            log_msg(
                "EXCEPTION FINISH transfer for track {track_id}"
                f" - range {range_l} - bytes written {bytes_sent}.",
                xbmc.LOGERROR,
            )
            log_exception("Error with track transfer")
        finally:
            # Make sure spotty always gets terminated.
            if spotty_process:
                spotty_process.terminate()
                spotty_process.communicate()
            self.kill_spotty()

    def kill_spotty(self):
        self.spotty.kill_spotty()

    def __create_wav_header(self):
        """generate a wav header for the stream"""
        try:
            log_msg(f"Start getting wav header. Duration = {self.track_duration}", xbmc.LOGDEBUG)
            file = BytesIO()
            num_samples = 44100 * self.track_duration
            channels = 2
            sample_rate = 44100
            bits_per_sample = 16

            # Generate format chunk.
            format_chunk_spec = "<4sLHHLLHH"
            format_chunk = struct.pack(
                format_chunk_spec,
                "fmt ".encode(encoding="UTF-8"),  # Chunk id
                16,  # Size of this chunk (excluding chunk id and this field)
                1,  # Audio format, 1 for PCM
                channels,  # Number of channels
                sample_rate,  # Samplerate, 44100, 48000, etc.
                sample_rate * channels * (bits_per_sample // 8),  # Byterate
                channels * (bits_per_sample // 8),  # Blockalign
                bits_per_sample,  # 16 bits for two byte samples, etc.
            )

            # Generate data chunk.
            data_chunk_spec = "<4sL"
            data_size = num_samples * channels * (bits_per_sample / 8)
            data_chunk = struct.pack(
                data_chunk_spec,
                "data".encode(encoding="UTF-8"),  # Chunk id
                int(data_size),  # Chunk size (excluding chunk id and this field)
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

        except Exception:
            log_exception("Failed to create wave header.")
