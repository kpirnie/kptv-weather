#!/usr/bin/env python3
"""
FFmpeg Streaming Module

Runs the external ffmpeg binary as a long-lived encoder: raw RGBA frames go
in on stdin, mpeg transport stream comes back out on stdout, and a reader
thread pumps that into the fanout broker.

ffmpeg is never bundled with this project. A static binary must be bind
mounted into the container and its path passed in.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import glob
import logging
import os
import platform
import queue
import shutil
import subprocess
import threading
from ctypes.util import find_library
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# how much we read off the encoder at a time
READ_SIZE = 188 * 64

# hardware encoders we will try before falling back to software, in order
HW_ORDER = ("h264_nvenc", "h264_qsv", "h264_vaapi")


class FFMPEGStreamer:
    """
    Long-lived ffmpeg encoder feeding the fanout broker

    Runs whether or not anybody is watching, which is what makes the output
    a continuous live channel rather than something started per client.
    """

    def __init__(self, ffmpeg_path: str, width: int, height: int, fps: int,
                 on_output: Callable, *, music_playlist: Optional[str] = None,
                 music_volume: float = 0.5, vb_kbps: int = 3500,
                 ab_kbps: int = 128, audio_sample_rate: int = 48000,
                 video_encoder: str = "auto", encoder_preset: str = "veryfast",
                 threads: int = 2, gop_seconds: float = 1.0,
                 pat_period: float = 0.5, pcr_period_ms: int = 40,
                 max_queue: int = 8):
        """
        Build the streamer

        @param ffmpeg_path: str Path to the bind mounted ffmpeg binary
        @param width: int Frame width fed in on stdin
        @param height: int Frame height fed in on stdin
        @param fps: int Constant frame rate of the input
        @param on_output: Callable Receives every chunk of encoder output
        @param music_playlist: str|None Concat playlist for the music bed
        @param music_volume: float Music gain from 0.0 to 1.0
        @param vb_kbps: int Target video bitrate
        @param ab_kbps: int Target audio bitrate
        @param audio_sample_rate: int Output sample rate
        @param video_encoder: str Encoder name, or auto to detect one
        @param encoder_preset: str Software encoder preset
        @param threads: int Thread cap for the software encoder
        @param gop_seconds: float Keyframe interval in seconds
        @param pat_period: float How often program tables are emitted
        @param pcr_period_ms: int Program clock reference interval
        @param max_queue: int Frames that may back up before we drop one
        """

        # the binary and the surface it is fed
        self.ffmpeg_path = str(ffmpeg_path)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.on_output = on_output

        # the music bed
        self.music_playlist = music_playlist
        self.music_volume = max(0.0, min(2.0, float(music_volume)))

        # encoding targets
        self.vb_kbps = int(vb_kbps)
        self.ab_kbps = int(ab_kbps)
        self.audio_sample_rate = int(audio_sample_rate)
        self.video_encoder = (video_encoder or "auto").lower()
        self.encoder_preset = encoder_preset
        self.threads = int(threads)

        # mux shaping
        self.gop_seconds = float(gop_seconds)
        self.pat_period = float(pat_period)
        self.pcr_period_ms = int(pcr_period_ms)

        # process state, shared between the writer and the reader threads
        self.proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._proc_dead = False
        self._stop_event = threading.Event()

        # the frame queue and its pump threads
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(max_queue)))
        self._writer_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None

    # ------------------------- encoder selection -------------------------

    def _choose_encoder(self) -> tuple:
        """
        Pick a video encoder and build its arguments

        @return tuple: Encoder name, its pre-input arguments, its output args
        """

        # rate control shared by every encoder we support
        gop = max(1, int(round(self.fps * self.gop_seconds)))
        common = [
            "-g", str(gop),
            "-keyint_min", str(gop),
            "-bf", "0",
            "-b:v", f"{self.vb_kbps}k",
            "-maxrate", f"{self.vb_kbps}k",
            "-bufsize", f"{self.vb_kbps * 2}k",
        ]

        # an explicit choice is honored as long as it is actually usable
        enc = self.video_encoder
        if enc != "auto":
            if enc != "libx264" and not self._encoder_supported(enc):
                logger.warning("encoder %s unavailable, falling back to libx264", enc)
                enc = "libx264"
            return self._enc_args(enc, common)

        # otherwise work down the hardware list and take the first that works
        for candidate in HW_ORDER:
            if self._encoder_supported(candidate):
                logger.info("using hardware encoder %s", candidate)
                return self._enc_args(candidate, common)

        # nothing available, so software it is
        logger.info("no hardware encoder detected, using libx264")
        return self._enc_args("libx264", common)

    def _enc_args(self, enc: str, base: list) -> tuple:
        """
        Build the argument lists for a specific encoder

        @param enc: str The encoder name
        @param base: list Shared rate control arguments
        @return tuple: Encoder name, pre-input arguments, post-input arguments
        """

        # anything that has to appear before the inputs lands here
        pre: list = []
        args: list = []

        # nvidia
        if enc == "h264_nvenc":
            preset_map = {
                "ultrafast": "p1", "veryfast": "p2", "faster": "p3",
                "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p7",
                "veryslow": "p7", "placebo": "p7",
            }
            args = [
                "-c:v", "h264_nvenc",
                "-preset", preset_map.get(self.encoder_preset, "p5"),
                "-tune", "ull",
                "-rc", "cbr",
                "-zerolatency", "1",
                "-delay", "0",
                "-pix_fmt", "yuv420p",
            ]

        # intel quicksync
        elif enc == "h264_qsv":
            args = [
                "-c:v", "h264_qsv",
                "-global_quality", "0",
                "-look_ahead", "0",
                "-pix_fmt", "nv12",
            ]
            device = self._render_node()
            if device:
                args += ["-qsv_device", device]

        # anything else exposed through /dev/dri
        elif enc == "h264_vaapi":
            device = self._render_node()
            if device:
                pre = ["-vaapi_device", device]
            args = [
                "-vf", "format=nv12,hwupload",
                "-c:v", "h264_vaapi",
            ]

        # software
        else:
            enc = "libx264"
            args = [
                "-c:v", "libx264",
                "-tune", "zerolatency",
                "-preset", self.encoder_preset,
                "-threads", str(max(0, self.threads)),
                "-x264-params",
                "nal-hrd=cbr:force-cfr=1:repeat-headers=1:scenecut=0",
                "-pix_fmt", "yuv420p",
            ]

        return enc, pre, args + base

    def _encoder_supported(self, enc: str) -> bool:
        """
        Whether an encoder can actually be used on this host right now

        @param enc: str The encoder name
        @return bool: True when it initializes successfully
        """

        # software always works
        enc = (enc or "").lower()
        if enc == "libx264":
            return True

        # nvidia needs the userspace driver present as well as the encoder
        if enc == "h264_nvenc":
            return self._nvenc_present() and self._encoder_functional(enc, None)

        # both of the /dev/dri paths need a render node passed into the container
        if enc in {"h264_qsv", "h264_vaapi"}:
            device = self._render_node()
            return device is not None and self._encoder_functional(enc, device)

        # anything else we simply do not offer
        return False

    @staticmethod
    @lru_cache(maxsize=None)
    def _render_node() -> Optional[str]:
        """
        Locate a DRM render node passed into the container

        @return str|None: Path to a render node, or None when none exists
        """

        # only ever relevant on linux
        if platform.system().lower() != "linux":
            return None

        # prefer a real render node
        for candidate in sorted(glob.glob("/dev/dri/renderD*")):
            return candidate

        # fall back to the primary node if that is all we were given
        return "/dev/dri/card0" if os.path.exists("/dev/dri/card0") else None

    @lru_cache(maxsize=None)
    def _encoder_functional(self, enc: str, device: Optional[str]) -> bool:
        """
        Prove an encoder works by encoding a throwaway frame with it

        A device file existing says nothing about whether the driver stack
        behind it works, and finding that out at stream time is too late to
        fall back from.

        @param enc: str The encoder name
        @param device: str|None Render node to hand the encoder
        @return bool: True when the test encode succeeded
        """

        # no binary, nothing to test
        if not self._ffmpeg_exists():
            return False

        # build a one frame encode of a solid color
        cmd = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]
        if enc == "h264_vaapi" and device:
            cmd += ["-vaapi_device", device]
        # NVENC rejects anything below 128x128, so the test frame has to clear
        # that or a perfectly good encoder looks broken
        cmd += ["-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                "-frames:v", "1"]
        if enc == "h264_vaapi":
            cmd += ["-vf", "format=nv12,hwupload"]
        cmd += ["-c:v", enc]
        if enc == "h264_qsv" and device:
            cmd += ["-qsv_device", device]
        cmd += ["-f", "null", "-"]

        # run it and see whether it came back clean
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    @lru_cache(maxsize=None)
    def _nvenc_present() -> bool:
        """
        Whether an NVIDIA GPU looks to be reachable from inside the container

        The device nodes and the userspace driver arrive separately: the nodes
        come from the container runtime, the libraries have to be bind mounted
        because NVIDIA ships nothing redistributable. Either one on its own is
        enough to be worth probing, since the probe is what actually decides.

        @return bool: True when NVENC is worth attempting
        """

        # the control node is the reliable signal that a GPU was passed in
        for node in ("/dev/nvidiactl", "/dev/nvidia0"):
            if os.path.exists(node):
                return True

        # the loader knows best about the libraries
        if find_library("cuda") or find_library("nvidia-encode"):
            return True

        # otherwise check the usual places a mount or the toolkit puts them
        for directory in (
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib/aarch64-linux-gnu",
            "/usr/lib64",
            "/usr/lib64/nvidia",
            "/usr/local/cuda/lib64",
            "/usr/lib/wsl/lib",
        ):
            for name in ("libcuda.so.1", "libnvidia-encode.so.1"):
                if os.path.exists(f"{directory}/{name}"):
                    return True

        # last resort
        return shutil.which("nvidia-smi") is not None

    def _ffmpeg_exists(self) -> bool:
        """
        Whether the configured ffmpeg binary is present and executable

        @return bool: True when it can be run
        """

        # an absolute path has to exist and be executable
        candidate = Path(self.ffmpeg_path)
        if candidate.is_absolute():
            return candidate.is_file() and os.access(candidate, os.X_OK)

        # otherwise let PATH resolve it
        return shutil.which(self.ffmpeg_path) is not None

    # ------------------------- command -------------------------

    def _build_command(self) -> list:
        """
        Assemble the full ffmpeg command line

        @return list: The argv for the encoder process
        """

        # work out the encoder before anything else, it may need pre-args
        enc_name, pre_args, v_args = self._choose_encoder()

        # the binary, its pre-input arguments, then the raw video input
        cmd = [self.ffmpeg_path, "-hide_banner", "-loglevel", "warning"]
        cmd += pre_args
        cmd += [
            "-fflags", "+genpts",
            "-thread_queue_size", "8192",
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "-",
        ]

        # the music bed when we have one, silence when we do not
        music_idx = None
        if self.music_playlist and Path(self.music_playlist).exists():
            cmd += [
                "-thread_queue_size", "4096",
                "-stream_loop", "-1",
                "-f", "concat",
                "-safe", "0",
                "-i", self.music_playlist,
            ]
            music_idx = 1
        else:
            cmd += [
                "-f", "lavfi",
                "-i", f"anullsrc=channel_layout=stereo:"
                      f"sample_rate={self.audio_sample_rate}",
            ]

        # music gets its gain applied, silence needs nothing
        if music_idx is not None:
            cmd += ["-filter_complex",
                    f"[{music_idx}:a]volume={self.music_volume:.3f}[aout]"]
            audio_map = "[aout]"
        else:
            audio_map = "1:a"

        # map the two streams through
        cmd += ["-map", "0:v:0", "-map", audio_map]

        # video encoding, then audio
        cmd += v_args
        cmd += [
            "-c:a", "aac",
            "-b:a", f"{self.ab_kbps}k",
            "-ar", str(self.audio_sample_rate),
        ]

        # mux shaping, tuned so a client joining mid-stream sees tables fast
        cmd += [
            "-mpegts_flags", "+resend_headers+initial_discontinuity",
            "-flush_packets", "1",
            "-max_interleave_delta", "0",
            "-muxpreload", "0",
            "-muxdelay", "0",
            "-pat_period", str(self.pat_period),
            "-pcr_period", str(self.pcr_period_ms),
            "-f", "mpegts", "pipe:1",
        ]

        logger.info("encoder: %s", enc_name)
        logger.debug("ffmpeg command: %s", " ".join(cmd))
        return cmd

    # ------------------------- lifecycle -------------------------

    def start(self) -> None:
        """
        Launch the encoder and its pump threads

        @return None
        @throws RuntimeError: When the ffmpeg binary cannot be found
        """

        # already up, nothing to do
        if self.proc and self.proc.poll() is None:
            return

        # this project never ships ffmpeg, so say so plainly when it is absent
        if not self._ffmpeg_exists():
            raise RuntimeError(
                f"ffmpeg not found at '{self.ffmpeg_path}' - a static ffmpeg "
                f"build must be bind mounted into the container and its path "
                f"passed in as KPTVW_FFMPEG_PATH"
            )

        # fire it up
        cmd = self._build_command()
        with self._proc_lock:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                bufsize=0,
            )
            self._proc_dead = False

        # start the thread that feeds it frames
        self._stop_event.clear()
        if not self._writer_thread or not self._writer_thread.is_alive():
            self._writer_thread = threading.Thread(
                target=self._writer_loop, name="ffmpeg-writer", daemon=True,
            )
            self._writer_thread.start()

        # and the one that drains its output into the broker
        if not self._reader_thread or not self._reader_thread.is_alive():
            self._reader_thread = threading.Thread(
                target=self._reader_loop, name="ffmpeg-reader", daemon=True,
            )
            self._reader_thread.start()

    def _reader_loop(self) -> None:
        """
        Pump encoder output into the fanout broker

        @return None
        """

        # keep reading until we are told to stop
        while not self._stop_event.is_set():
            proc = self.proc
            if proc is None or proc.stdout is None:
                break

            # grab whatever is ready
            try:
                data = proc.stdout.read(READ_SIZE)
            except (ValueError, OSError):
                break

            # an empty read means the encoder went away
            if not data:
                self._proc_dead = True
                break

            # hand it off, never letting a consumer fault kill the pump
            try:
                self.on_output(data)
            except Exception:
                logger.exception("fanout rejected a chunk")

    def _writer_loop(self) -> None:
        """
        Feed queued frames into the encoder's stdin

        @return None
        """

        # run until shutdown
        while not self._stop_event.is_set():

            # wait for a frame
            try:
                payload = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            # the sentinel ends us
            if payload is None:
                break

            # grab the handle under the lock, then release it before writing:
            # a full frame is megabytes and the write blocks until ffmpeg
            # drains it, which would otherwise stall every other caller
            with self._proc_lock:
                proc = self.proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                self._proc_dead = True
                continue

            # write it out whole, marking the process dead on any pipe fault
            try:
                self._write_all(proc, payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self._proc_dead = True

    def _write_all(self, proc: subprocess.Popen, payload: bytes) -> None:
        """
        Write a complete frame to the encoder

        @param proc: Popen The encoder process
        @param payload: bytes The raw frame
        @return None
        """

        # loop until every byte is gone, short writes and all
        view = memoryview(payload)
        while view:
            written = os.write(proc.stdin.fileno(), view)
            view = view[written:]

    def send(self, frame) -> bool:
        """
        Queue a rendered frame for encoding

        @param frame: bytes|Image The frame to send
        @return bool: True when it was queued, False when dropped
        """

        # bring the encoder back if it died on us
        if self.proc is None or self.proc.poll() is not None or self._proc_dead:
            logger.warning("encoder is not running, restarting it")
            self._restart()

        # accept raw bytes or anything that can produce them
        if isinstance(frame, (bytes, bytearray, memoryview)):
            payload = frame
        elif hasattr(frame, "tobytes"):
            payload = frame.tobytes()
        else:
            raise TypeError(f"unsupported frame type: {type(frame)!r}")

        # drop rather than block when the encoder is behind
        try:
            self._queue.put_nowait(payload)
            return True
        except queue.Full:
            return False

    def _restart(self) -> None:
        """
        Stop and relaunch the encoder

        @return None
        """

        # tear the old one down, ignoring whatever state it was in
        try:
            self.stop()
        except Exception:
            pass

        # and bring a fresh one up
        self.start()

    def stop(self) -> None:
        """
        Shut the encoder and its threads down

        @return None
        """

        # wake the writer and let it unwind
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._writer_thread and self._writer_thread.is_alive():
            if threading.current_thread() is not self._writer_thread:
                self._writer_thread.join(timeout=2.0)
        self._writer_thread = None

        # then close the process out
        with self._proc_lock:
            proc = self.proc
            self.proc = None
        if proc:
            for closer in (
                lambda: proc.stdin and proc.stdin.close(),
                lambda: proc.stdout and proc.stdout.close(),
                lambda: proc.terminate(),
                lambda: proc.wait(timeout=3),
            ):
                try:
                    closer()
                except Exception:
                    pass

        # and let the reader fall out on its own
        if self._reader_thread and self._reader_thread.is_alive():
            if threading.current_thread() is not self._reader_thread:
                self._reader_thread.join(timeout=2.0)
        self._reader_thread = None
