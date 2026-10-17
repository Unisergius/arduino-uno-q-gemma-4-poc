"""Grab one photo from the Seeed reCamera's video stream (RTSP).

On the board we use App Lab's own camera helper (OpenCV underneath).
On a laptop we fall back to the `ffmpeg` command, if it is installed.
"""

import base64
import subprocess
import time


def grab_jpeg_b64(url, timeout_s=15):
    """Return one frame as base64 JPEG text, or raise RuntimeError."""
    if not url:
        raise RuntimeError("no camera configured (set RECAMERA_URL in config.py) - use the phone upload")
    try:
        from arduino.app_peripherals.camera import Camera
        from arduino.app_utils.image import compress_to_jpeg
    except ImportError:
        return _grab_with_ffmpeg(url, timeout_s)

    camera = Camera(url, resolution=(640, 480))  # VERIFY: reCamera RTSP path and that OpenCV can open it
    camera.start()
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            frame = camera.capture()
            if frame is not None:
                jpeg = compress_to_jpeg(frame, quality=85)
                if jpeg is not None:
                    return base64.b64encode(jpeg.tobytes()).decode()
            time.sleep(0.2)
    finally:
        camera.stop()
    raise RuntimeError(f"no frame from {url} within {timeout_s} s")


def _grab_with_ffmpeg(url, timeout_s):
    command = ["ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url,
               "-frames:v", "1", "-vf", "scale=640:-2", "-f", "image2", "-c:v", "mjpeg", "-"]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout_s, check=True)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg is not installed - use the phone upload") from None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"could not read {url}: {error}") from None
    return base64.b64encode(result.stdout).decode()
