"""Compute the visual verdict from a downsampled video frame in RGBA order."""

import json
import sys


def pixel_stats(rgba):
    if not rgba or len(rgba) % 4:
        raise ValueError("expected whole RGBA pixels")
    red = bright = sampled = 0
    total_luma = peak = 0.0
    for offset in range(0, len(rgba), 4):
        r, g, b = rgba[offset:offset + 3]
        if r > 120 and r > 2.2 * g and r > 2.2 * b:
            red += 1
        if offset % 28 == 0:  # One luma sample per seven pixels.
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            sampled += 1
            total_luma += luma
            peak = max(peak, luma)
            bright += luma > 16
    return dict(meanLuma=total_luma / sampled, maxLuma=peak,
                brightFraction=bright / sampled, redFraction=red / (len(rgba) // 4))


def frame_passes(stats, *, connected, tracks, video_width):
    return (connected and tracks > 0 and video_width > 0
            and stats["meanLuma"] >= 8 and stats["maxLuma"] >= 32
            and stats["brightFraction"] >= 0.05 and stats["redFraction"] >= 0.01)


if __name__ == "__main__":
    rtc = json.loads(sys.argv[1])
    stats = pixel_stats(sys.stdin.buffer.read())
    print(json.dumps({"stats": stats, "pass": frame_passes(stats, **rtc)}))
