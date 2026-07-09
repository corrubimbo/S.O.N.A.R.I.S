"""
SONARIS MK5 — Ripple Visualizer  (Raspberry Pi Zero 2 W edition)
================================================================
A lean, single-purpose ripple visualizer:

    • Apple-Music-style background  — heavily blurred, saturated, slowly
      drifting album art (the "lyrics" backdrop).
    • 6 thin concentric frequency rings that pulse with the audio.
    • Cheap diffuse + specular shading and strong light refraction so the
      rings read as ripples on water.

Everything "fancy" from the desktop simulator has been removed: no album
card, no title/timeline text, no per-band crest loop, no valley field,
no np.power().  The expensive Gaussian ring profiles are precomputed once;
each frame is just a handful of vectorised NumPy passes over a small grid,
upscaled to the square by a single smoothscale (which also does the
smoothing for free).

Run (desktop test):   python ripple_pi.py
Run (Pi, headless):   SDL_VIDEODRIVER=kmsdrm python ripple_pi.py
    Pi audio:  set AUDIO_SOURCE = "cava" — see the AUDIO section below.

Performance knob #1 is GRID.  Lower it until you hit your FPS target;
the smoothscale upscale hides the coarser grid.
"""

import os
import sys
import asyncio
import io
import subprocess
import tempfile
import threading
import time
import numpy as np
import pygame
from PIL import Image

# ─── DISPLAY ──────────────────────────────────────────────────────────────────
WIDTH, HEIGHT = 800, 800            # panel resolution
SQ_SIZE = min(WIDTH, HEIGHT)         # 800×800 square render area
SQ_X    = (WIDTH  - SQ_SIZE) // 2    # 140 px black bars left/right
SQ_Y    = (HEIGHT - SQ_SIZE) // 2    # 0
USE_FULLSCREEN = False               # True on the Pi (kmsdrm native res)

# ─── PERFORMANCE ──────────────────────────────────────────────────────────────
# GRID is the resolution the ripple field is computed at, then upscaled to the
# 800 px square.  Cost is ~GRID².  The smoothscale upscale cost is fixed (it
# only depends on the 800×800 output), so SMALLER GRID = FASTER with little
# visual loss — the upscale blurs the grid back to smooth.
#   Pi Zero 2 W target 20–30 FPS:  start at 160, drop to 128 / 112 if needed.
GRID               = 160
TARGET_FPS         = 25
PHYS_FPS           = 90      # physics/audio update rate (Hz), decoupled from render.
                             #   The ring spring is sub-stepped to this rate every
                             #   frame, so fast beats snap in as if rendering at
                             #   PHYS_FPS — even though we still draw at TARGET_FPS.
                             #   Only the tiny per-band spring repeats; render doesn't.
USE_SMOOTH_SCALE   = True     # False = faster nearest-neighbour upscale (blockier)
SMOOTH_HALFRES     = False     # Pi speed-up: smoothscale to SQ_SIZE/2 (400px) then a
                             #   cheap nearest ×2 to 800px — ~4× less smoothscale work
                             #   (it has no SIMD path on ARM), still looks smooth.
                             #   Only applies when USE_SMOOTH_SCALE = True.
BG_UPDATE_INTERVAL = 10      # frames between background-drift recomputes
BG_LERP_ALPHA      = 0.16    # per-frame blend toward the new drift target

# ─── APPLE-MUSIC BACKGROUND ───────────────────────────────────────────────────
ALBUM_PATH    = "Audio Assets/NOBLE.jpg"
BG_SAT_BOOST  = 3.2      # saturation boost — Apple's backdrop is vivid
BG_BRIGHTNESS = 0.72     # 0 = black, 1 = full colour
BG_WARP_AMP   = 0.22     # drift amplitude as a fraction of the grid
VIGNETTE      = 0.40     # gentle edge darkening (0 = none)

# ─── NOW-PLAYING CARD ──────────────────────────────────────────────────────────
ART_SIZE     = 190       # cover-art square size on screen [px]
TRACK_TITLE  = ""        # blank → derived from the audio filename
TRACK_ARTIST = "Unknown Artist"   # WAV has no tags — set your artist here

# Live now-playing from Windows (System Media Transport Controls, via winsdk):
# pulls the album art + title/artist of whatever app is playing and feeds them to
# the visuals.  Audio reactivity stays on CAVA — this drives metadata/art only.
# Needs:  pip install winsdk   (Windows only; ignored elsewhere)
USE_WINSDK_MEDIA = True
MEDIA_POLL_SEC   = 0.3   # how often to poll the now-playing session [seconds].
                         #   ≈ the worst-case delay before a skipped track updates,
                         #   so keep it small for a consistent, snappy change.  Polls
                         #   are cheap (metadata only) — the thumbnail is decoded only
                         #   when the track actually changes.

# ─── RIPPLE RINGS ─────────────────────────────────────────────────────────────
N_BANDS        = 12        # frequency-responsive concentric rings
RING_SIGMA_MAX = 4.20     # half-width of the outermost (bass) ring   [grid cells]
RING_SIGMA_MIN = 1.10     # half-width of the innermost (treble) ring [grid cells]
                          #   → the wide gap makes the thickness track frequency:
                          #     bass rings are fat, treble rings are hairline-thin
RING_HEIGHT      = 2.60   # base peak surface height at full band amplitude
RING_HEIGHT_HI   = 1.85   # treble-ring height multiplier → highs are very visible
                          #   (tall, sharp).  Bass rings stay ×1.0.
RING_BASS_GAIN   = 1.80   # low-band sensitivity  (outermost ring)
RING_TREBLE_GAIN = 1.20   # high-band sensitivity (innermost ring)
RING_SENSITIVITY = 0.65   # gamma on the per-band level.  Nearer 1.0 = LESS
                          #   compression, so a loud band towers over a quiet one
                          #   and every frequency's ripple is visibly different
                          #   (like the bars of a CAVA visualiser).
RING_SENS_MULT   = 1.00   # master gain.  The old 2.5× drove every band to its clip
                          #   ceiling — all rings bulged equally and you couldn't
                          #   tell the frequencies apart.  1.0 keeps head-room so the
                          #   cube curve (a³) can separate loud vs quiet bands.
RING_SPRING      = 0.075  # spring stiffness — higher = snappier / more reactive
RING_DAMP_LOW    = 0.85   # bass bands: low damping → deep concave-DOWN overshoot
RING_DAMP_HIGH   = 0.94   # treble bands: high damping → crisp, no wobble
RING_UNDERSHOOT  = 2.10   # extra depth for downward (negative) displacement on the
                          #   low bands → lows punch "concave down" hard.
RING_SMOOTH      = 0.55   # temporal blend of the height field (1 = none);
                          #   lower = smoother, more fluid motion.
RING_CONTRAST    = 3.50   # exponent applied to each band's amplitude → ring height
                          #   (was a fixed cube = 3).  Higher = MORE dramatic contrast
                          #   between a loud ring and a quiet one.  Sign is preserved.
RING_SPACING_POW     = 1.3  # 1.0 = evenly-spaced rings.  >1 clusters the HIGH-freq
                             #   (inner) rings and spreads the LOW-freq (outer) ones;
                             #   the outermost ring stays put and the innermost clears
                             #   the cover art either way.
RING_INNER_CLEARANCE = 2.00  # grid-cells of gap between the innermost ring and the
                             #   cover-art corner — tiny, so the smallest ripple hugs
                             #   the album corners with only a sliver of space
RING_EDGE_GAP        = 2.00  # grid-cells of clear space between the OUTERMOST ripple's
                             #   visible edge and the square border — small but visible
# One extra thick "echo" ring near the centre (may sit under the album cover).
# It COPIES a mid-frequency band — the mids still drive their own ring too — a big
# slow swell beneath the frequency rings.
RING_CENTER_COUNT    = 0     # how many centre echo rings (0 = no middle ring)
RING_CENTER_SIGMA    = 5.50  # its half-width [grid cells] — VERY thick
RING_CENTER_HEIGHT   = 2.60  # its swell height
RING_CENTER_GAP      = 4.00  # calm gap [cells] kept between it and the inner treble ring

# ─── LIGHTING & REFRACTION ────────────────────────────────────────────────────
DISPLACEMENT_SCALE = 30.0   # ↑ = stronger light refraction (rings bend the bg more)
AMBIENT  = 0.42             # lower ambient + higher diffuse = deeper shadows and
DIFFUSE  = 0.92             #   brighter lit slopes → dramatic ring-to-ring contrast,
                            #   and even a tiny ripple casts a visible bright/dark edge
LIGHT    = np.array([0.70, -0.70, 0.85], dtype=np.float32)   # oblique key light
SPEC_INTENSITY = 0.85       # wet glint strength (0 disables; computed cheaply)
SPEC_COLOR     = np.array([1.00, 0.97, 0.90], dtype=np.float32)
SPEC_THIN_BOOST = 6.0       # brightness of the tight high-peak glint — compensates
                            # for its narrower area so tall rings still read bright
SPEC_PEAK_GAIN  = 2.20      # extra glint brightness scaled by peak height — the
                            # taller the ripple, the brighter (and thinner) its crest

# ─── AUDIO ────────────────────────────────────────────────────────────────────
# AUDIO_SOURCE picks where the ring data comes from:
#   "file" → decode + FFT an audio file   (desktop testing; needs `soundfile`)
#   "cava" → live system audio via CAVA   (Pi / Linux — reacts to whatever plays)
#   "sim"  → no audio, synthetic beat     (fallback / screensaver)
# Any source that fails to initialise falls back to "sim" automatically.
AUDIO_SOURCE = "cava"

# ── "file" source ──
AUDIO_FILE  = "Audio Assets/NOBLE.wav"
AUDIO_LOOP  = True
FFT_WINDOW  = 4096          # larger window → finer frequency bins & steadier
                            #   band energy (esp. cleaner bass separation).
                            #   Must stay a power of 2.  ~93 ms @ 44.1 kHz.
NORM_DECAY  = 0.996         # per-band running-max decay — lower = AGC recovers
                            #   faster in quiet passages → more sensitive

# ── "cava" source ──
# CAVA turns whatever the system is playing into CAVA_BARS frequency bars.  A
# background thread consumes it so it never blocks the render loop, and it works
# on any OS (falls back to "sim" if the cava binary / FIFO isn't present).
#   CAVA_AUTOSTART = True  → this script launches `cava` and reads its raw output
#                            (turnkey; just needs the `cava` binary on PATH).
#   CAVA_AUTOSTART = False → you run CAVA yourself, writing raw binary to CAVA_FIFO:
#       sudo apt install cava ; mkfifo /tmp/cava_fifo
#       ~/.config/cava/config →  [output] method=raw  raw_target=/tmp/cava_fifo
#                                data_format=binary  bit_format=16bit  channels=mono
#       (the `bars` in that config must equal CAVA_BARS)
CAVA_AUTOSTART = True
CAVA_BARS      = 32
CAVA_FIFO      = "/tmp/cava_fifo"   # only used when CAVA_AUTOSTART = False


# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO READER
# ══════════════════════════════════════════════════════════════════════════════
_audio_data = _audio_sr = _audio_hann = None
_ring_masks = None
_ring_amp_max = np.ones(N_BANDS, dtype=np.float32)
_band_amps = np.zeros(N_BANDS, dtype=np.float32)   # current ring amplitudes
_band_vels = np.zeros(N_BANDS, dtype=np.float32)   # spring-damper velocities
_last_bass   = 0.0
# CAVA: a daemon thread keeps _cava_bars (newest) and _cava_peak (max since the last
# render read) so the loop never blocks and no between-frame transient is lost.
_cava_bars   = None
_cava_peak   = None
_cava_stream = None
_cava_proc   = None
_cava_alive  = False

# Spring is stepped this many times per rendered frame → physics runs at ≈PHYS_FPS.
_PHYS_SUBSTEPS = max(1, round(PHYS_FPS / TARGET_FPS))

# Per-band curves (band 0 = bass/outer … band N-1 = treble/inner).
_ring_gain  = np.linspace(RING_BASS_GAIN, RING_TREBLE_GAIN, N_BANDS, dtype=np.float32) * RING_SENS_MULT
_ring_damp  = np.linspace(RING_DAMP_LOW,  RING_DAMP_HIGH,   N_BANDS, dtype=np.float32)
# _band_H and _ring_under are render-side (they include the centre echo rings), so
# they're built together with the ring geometry further down.


def _init_audio_file() -> bool:
    """Load the audio file, build per-ring FFT masks, start playback."""
    global _audio_data, _audio_sr, _audio_hann, _ring_masks
    try:
        import soundfile as sf
    except ImportError:
        print("[SONARIS] soundfile not installed → pip install soundfile")
        return False
    if not os.path.exists(AUDIO_FILE):
        print(f"[SONARIS] {AUDIO_FILE!r} not found — falling back to simulation.")
        return False
    try:
        data, sr = sf.read(AUDIO_FILE, dtype="float32", always_2d=False)
    except Exception as e:
        print(f"[SONARIS] cannot read {AUDIO_FILE!r}: {e}")
        return False

    _audio_data = data.mean(axis=1) if data.ndim == 2 else data
    _audio_sr   = int(sr)
    _audio_hann = np.hanning(FFT_WINDOW).astype(np.float32)

    freqs = np.fft.rfftfreq(FFT_WINDOW, 1.0 / _audio_sr)
    edges = np.logspace(np.log10(30.0), np.log10(16000.0), N_BANDS + 1)
    _ring_masks = [(freqs >= edges[i]) & (freqs < edges[i + 1]) for i in range(N_BANDS)]

    try:
        pygame.mixer.music.load(AUDIO_FILE)
        pygame.mixer.music.play(loops=-1 if AUDIO_LOOP else 0)
    except pygame.error as e:
        print(f"[SONARIS] no audio output ({e}); analysing silently by clock.")
    print(f"[SONARIS] audio: {AUDIO_FILE!r}  ({_audio_sr} Hz)")
    return True


# ─── CAVA source (live system audio, consumed on a background thread) ──────────
_CAVA_CFG = """\
[general]
bars = {bars}
[output]
method = raw
raw_target = /dev/stdout
data_format = binary
bit_format = 16bit
channels = mono
"""


def _read_exact(stream, n: int):
    """Block until exactly n bytes are read; return them, or None on EOF/error."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = stream.read(n - len(buf))
        except (OSError, ValueError):
            return None
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def _cava_loop(stream) -> None:
    """Reader thread: keep _cava_bars (newest) and _cava_peak (max since last read).
    The peak-hold means a transient that spikes BETWEEN two render frames is not
    lost — the render still sees its peak."""
    global _cava_bars, _cava_peak, _cava_alive
    nbytes = CAVA_BARS * 2                       # 16-bit little-endian, one per bar
    while _cava_alive:
        buf = _read_exact(stream, nbytes)
        if buf is None:                          # cava exited / pipe closed
            break
        frame = np.frombuffer(buf, "<u2").astype(np.float32) / 65535.0
        _cava_bars = frame
        pk = _cava_peak
        _cava_peak = frame if pk is None else np.maximum(pk, frame)
    _cava_alive = False


def _consume_cava_peak():
    """Return the peak CAVA frame since the last call, then reset the window."""
    global _cava_peak
    pk = _cava_peak
    _cava_peak = None
    return pk


def _init_cava() -> bool:
    """Launch CAVA (or open its FIFO) + start the reader thread.  False if absent."""
    global _cava_stream, _cava_proc, _cava_alive
    try:
        if CAVA_AUTOSTART:
            cfg = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
            cfg.write(_CAVA_CFG.format(bars=CAVA_BARS)); cfg.close()
            _cava_proc   = subprocess.Popen(["cava", "-p", cfg.name],
                                            stdout=subprocess.PIPE)
            _cava_stream = _cava_proc.stdout
        else:
            _cava_stream = open(CAVA_FIFO, "rb", buffering=0)
    except OSError as e:                         # cava binary / FIFO missing, etc.
        print(f"[SONARIS] CAVA unavailable ({e}); falling back to simulation.")
        return False
    _cava_alive = True
    threading.Thread(target=_cava_loop, args=(_cava_stream,), daemon=True).start()
    print(f"[SONARIS] audio: CAVA  ({CAVA_BARS} bars, "
          f"{'autostart' if CAVA_AUTOSTART else CAVA_FIFO})")
    return True


def _spring_to(target: np.ndarray) -> None:
    """Reactive spring toward `target`, with per-band damping.
    A sensitivity gamma (<1) lifts quiet detail; low bands under-damp so they
    overshoot into the negative (concave-down pop)."""
    global _band_amps, _band_vels
    tgt = np.clip(target, 0.0, 1.0) ** RING_SENSITIVITY
    _band_vels[:] = _band_vels * _ring_damp + (tgt - _band_amps) * RING_SPRING
    _band_amps[:] = np.clip(_band_amps + _band_vels, -1.0, 1.0)


def _audio_target(t: float):
    """Per-band target level ∈ [0,1] for time t, or None if no data yet."""
    global _ring_amp_max

    # 1 ── file FFT ────────────────────────────────────────────────────────────
    if AUDIO_SOURCE == "file" and _audio_data is not None:
        pos_ms = pygame.mixer.music.get_pos()
        pos_t  = t if pos_ms < 0 else pos_ms / 1000.0      # clock fallback
        total  = len(_audio_data) / _audio_sr
        pos    = int((pos_t % total) * _audio_sr)
        start  = max(0, pos - FFT_WINDOW // 2)
        chunk  = _audio_data[start:start + FFT_WINDOW]
        if len(chunk) < FFT_WINDOW:
            chunk = np.pad(chunk, (0, FFT_WINDOW - len(chunk)))
        mag = np.abs(np.fft.rfft(chunk * _audio_hann))
        raw = np.array([mag[m].mean() if m.any() else 0.0 for m in _ring_masks],
                       dtype=np.float32)
        _ring_amp_max = np.maximum(_ring_amp_max * NORM_DECAY, np.maximum(raw, 1e-6))
        return np.clip(raw / _ring_amp_max * _ring_gain, 0.0, 1.0)

    # 2 ── CAVA (peak since the last read → never miss a between-frame transient) ─
    if AUDIO_SOURCE == "cava":
        bars = _consume_cava_peak()
        if bars is None or len(bars) != CAVA_BARS:
            return None
        src = np.linspace(0, CAVA_BARS - 1, N_BANDS)
        tgt = np.interp(src, np.arange(CAVA_BARS), bars).astype(np.float32)
        return np.clip(tgt * _ring_gain, 0.0, 1.0)

    # 3 ── simulation (no audio) ────────────────────────────────────────────────
    beat = (t % 0.6) / 0.6
    bass = float(np.clip(np.exp(-7.0 * beat) * 0.9, 0, 1))
    ti   = np.linspace(0.0, 1.0, N_BANDS, dtype=np.float32)
    base = (1 - ti) * bass + ti * (0.18 + 0.12 * np.abs(np.sin(t * 5.0 + ti * 6.0)))
    return np.clip(base, 0.0, 1.0)


def read_audio(t: float) -> float:
    """Sample the audio once, then sub-step the ring spring _PHYS_SUBSTEPS times so
    the physics advances at ≈PHYS_FPS.  This is what makes 30 FPS react to fast beats
    as if it were running at PHYS_FPS.  Returns the bass level (for the glint)."""
    global _last_bass
    target = _audio_target(t)
    if target is not None:
        for _ in range(_PHYS_SUBSTEPS):
            _spring_to(target)
    _last_bass = float(max(_band_amps[0], 0.0))
    return _last_bass


# ══════════════════════════════════════════════════════════════════════════════
#  INIT
# ══════════════════════════════════════════════════════════════════════════════
pygame.init()
try:
    pygame.mixer.init()
except pygame.error:
    pass   # headless Pi without an audio device — simulation/CAVA still work

flags  = (pygame.FULLSCREEN if USE_FULLSCREEN else 0)
screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
pygame.display.set_caption("SONARIS — Ripple")
pygame.mouse.set_visible(False)
clock  = pygame.time.Clock()

if AUDIO_SOURCE == "file":
    if not _init_audio_file():
        AUDIO_SOURCE = "sim"
elif AUDIO_SOURCE == "cava":
    if not _init_cava():
        AUDIO_SOURCE = "sim"

# Internal flag: is a decoded file playing through the mixer?  Drives the pause
# toggle, the progress bar and the duration read-out further below.
AUDIO_ENABLED = (AUDIO_SOURCE == "file" and _audio_data is not None)


# ─── Apple-Music background art (blurred + saturated) ─────────────────────────
def _default_pil() -> Image.Image:
    """Album art from ALBUM_PATH, or a procedural gradient if it's missing."""
    if os.path.exists(ALBUM_PATH):
        return Image.open(ALBUM_PATH).convert("RGB")
    gy, gx = np.mgrid[0:64, 0:64]
    return Image.fromarray(np.uint8(np.clip(np.stack(
        [40 + gx * 1.5, 30 + gy * 2.0, 120 + gx * 1.2 + gy * 0.8], -1), 0, 255)))


def _bg_from_pil(pil: Image.Image) -> np.ndarray:
    """A (GRID,GRID,3) float32 backdrop: heavily blurred, saturated, darkened."""
    small = pil.resize((GRID // 6 or 1, GRID // 6 or 1), Image.BILINEAR)   # hard blur
    arr   = np.asarray(small.resize((GRID, GRID), Image.BILINEAR), dtype=np.float32)
    mean  = arr.mean(axis=2, keepdims=True)
    arr   = np.clip(mean + (arr - mean) * BG_SAT_BOOST, 0, 255)            # saturate
    return arr * BG_BRIGHTNESS


_bg_art = _bg_from_pil(_default_pil())

# ─── Coordinate + ring precompute (once) ──────────────────────────────────────
X, Y = np.meshgrid(np.arange(GRID, dtype=np.float32),
                   np.arange(GRID, dtype=np.float32))
cx = cy = GRID * 0.5
R  = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2).astype(np.float32)

# Ring radii: band 0 (bass) outermost → band N-1 (treble) innermost (water order).
# Cover art is a square; a circle of radius = half-diagonal reaches its corners.
_px_to_cell   = GRID / SQ_SIZE
_art_corner_g = (ART_SIZE * 0.5) * 1.41421356 * _px_to_cell        # corner in cells
# Furthest ripple: pulled in by ~2σ (its own visible half-width) plus a small gap
# so the outermost ring clears the border instead of bleeding into it.
r_outer = GRID * 0.5 - 2.0 * RING_SIGMA_MAX - RING_EDGE_GAP
# Innermost (highest-freq) ring is pushed out so it + its width clears the art corner.
r_inner = _art_corner_g + 2.0 * RING_SIGMA_MIN + RING_INNER_CLEARANCE
# Non-uniform spacing: (1-t)^p places band 0 exactly at r_outer and band N-1 at
# r_inner, with the gaps shrinking toward the inside → high-freq rings bunched,
# low-freq rings spread out.  Bigger RING_SPACING_POW = stronger effect.
_t      = np.linspace(0.0, 1.0, N_BANDS, dtype=np.float32)
band_r  = (r_inner + (r_outer - r_inner) * (1.0 - _t) ** RING_SPACING_POW).astype(np.float32)
band_s  = np.linspace(RING_SIGMA_MAX, RING_SIGMA_MIN, N_BANDS, dtype=np.float32)

# ── Centre "mid echo" ring: thick, near the middle (may sit under the cover) ────
# Placed inside r_inner with a clear RING_CENTER_GAP between its visible edge and
# the innermost treble ring.  It COPIES a mid band (that band still drives its own
# frequency ring — this is an extra ring, not a takeover).
_center_band = N_BANDS // 2                                             # a mid-freq band
_rc_top  = r_inner - RING_CENTER_GAP - 1.5 * RING_CENTER_SIGMA
center_r = np.linspace(_rc_top, _rc_top * 0.30, RING_CENTER_COUNT).astype(np.float32)
center_s = np.full(RING_CENTER_COUNT, RING_CENTER_SIGMA, dtype=np.float32)

# Combined render rings = N_BANDS frequency rings + the centre echo.
ring_r = np.concatenate([band_r, center_r]).astype(np.float32)
ring_s = np.concatenate([band_s, center_s]).astype(np.float32)
# Which audio band drives each render ring: the frequency rings map to themselves;
# the echo copies the mid band (a copy — the mid still drives its own ring).
_ring_src = np.concatenate([np.arange(N_BANDS),
                            np.full(RING_CENTER_COUNT, _center_band)]).astype(np.intp)

# Per render-ring height + concave-down depth.  The echo uses its own swell height
# but inherits its source band's dip depth so it behaves like the band it copies.
_band_under_full = np.linspace(RING_UNDERSHOOT, 1.0, N_BANDS).astype(np.float32)
_band_H = np.concatenate([
    np.linspace(RING_HEIGHT, RING_HEIGHT * RING_HEIGHT_HI, N_BANDS),
    np.full(RING_CENTER_COUNT, RING_CENTER_HEIGHT),
]).astype(np.float32)
_ring_under = np.concatenate([
    _band_under_full,
    _band_under_full[_ring_src[N_BANDS:]],
]).astype(np.float32)

# Gaussian profile per ring — the only exp() calls in the whole program.
ring_profiles = np.exp(
    -((R[None] - ring_r[:, None, None]) / ring_s[:, None, None]) ** 2
).astype(np.float32)

L = LIGHT / np.linalg.norm(LIGHT)

# Vignette (precomputed, applied to the bg each frame — cheap multiply).
vr = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
vignette = np.clip(1.0 - VIGNETTE * vr ** 1.5, 0.06, 1.0).astype(np.float32)[..., None]

# Pre-allocated per-frame scratch (no heap churn at 30 Hz).
_Z    = np.zeros((GRID, GRID), dtype=np.float32)   # smoothed height (persists)
_Zt   = np.zeros((GRID, GRID), dtype=np.float32)   # instantaneous height target
_Zp   = np.zeros((GRID + 2, GRID + 2), dtype=np.float32)
_dzdx = np.zeros((GRID, GRID), dtype=np.float32)
_dzdy = np.zeros((GRID, GRID), dtype=np.float32)

grid_surf = pygame.Surface((GRID, GRID))
sq_surf   = pygame.Surface((SQ_SIZE, SQ_SIZE))
screen.fill((0, 0, 0))

# Upscale strategy: grid → SQ_SIZE square.  The half-res path smoothscales to 400px
# (¼ the output pixels) then nearest ×2 to 800 — big Pi win, since smoothscale has
# no SIMD fast path on ARM while the nearest step is nearly free.
if USE_SMOOTH_SCALE and SMOOTH_HALFRES:
    _half     = SQ_SIZE // 2
    half_surf = pygame.Surface((_half, _half))
    def upscale_square():
        pygame.transform.smoothscale(grid_surf, (_half, _half), half_surf)
        pygame.transform.scale(half_surf, (SQ_SIZE, SQ_SIZE), sq_surf)
elif USE_SMOOTH_SCALE:
    def upscale_square():
        pygame.transform.smoothscale(grid_surf, (SQ_SIZE, SQ_SIZE), sq_surf)
else:
    def upscale_square():
        pygame.transform.scale(grid_surf, (SQ_SIZE, SQ_SIZE), sq_surf)


# ─── Now-playing card (sharp cover art + metadata + progress bar) ──────────────
def _cover_from_pil(pil: Image.Image, size: int) -> pygame.Surface:
    """Sharp album cover for the centre card (distinct from the blurred backdrop)."""
    surf = pygame.image.frombytes(pil.tobytes(), pil.size, "RGB").convert()
    return pygame.transform.smoothscale(surf, (size, size))


cover_art = _cover_from_pil(_default_pil(), ART_SIZE)

font_title  = pygame.font.SysFont("Arial", 30, bold=True)
font_artist = pygame.font.SysFont("Arial", 20)
font_time   = pygame.font.SysFont("Arial", 14)
font_dbg    = pygame.font.SysFont("Consolas", 14)

# Card + text stack, centred on the square (= the ripple centre).
CX, CY   = WIDTH // 2, HEIGHT // 2
CARD_X   = CX - ART_SIZE // 2
CARD_Y   = CY - ART_SIZE // 2
TITLE_Y  = CARD_Y + ART_SIZE + 20
ARTIST_Y = TITLE_Y + 34
BAR_W, BAR_H = 440, 5
BAR_X    = CX - BAR_W // 2
BAR_Y    = ARTIST_Y + 40

if not TRACK_TITLE:
    TRACK_TITLE = (os.path.splitext(os.path.basename(AUDIO_FILE))[0]
                   if AUDIO_SOURCE == "file" else "Live Audio")
DURATION_TOTAL = 213
if AUDIO_ENABLED and _audio_data is not None:
    DURATION_TOTAL = int(len(_audio_data) / _audio_sr)


def _fmt(sec: float) -> str:
    m, s = divmod(int(max(sec, 0.0)), 60)
    return f"{m}:{s:02d}"


# Static text — title, artist and total-duration never change, so render them once
# instead of every frame (font.render is comparatively costly on the Pi).
title_surf  = font_title.render(TRACK_TITLE, True, (255, 255, 255))
title_pos   = (CX - title_surf.get_width() // 2, TITLE_Y)
artist_surf = font_artist.render(TRACK_ARTIST, True, (200, 200, 212)) if TRACK_ARTIST else None
artist_pos  = (CX - artist_surf.get_width() // 2, ARTIST_Y) if artist_surf else (0, 0)
# Time labels: current + total, each re-rendered only when its second changes.
# The total refreshes automatically when a new track's duration comes in.
_cur_sec  = -1
_cur_surf = font_time.render("0:00", True, (170, 170, 185))
_tot_sec  = -1
_tot_surf = font_time.render("0:00", True, (140, 140, 155))
_tot_pos  = (BAR_X + BAR_W - _tot_surf.get_width(), BAR_Y + 10)


def compute_background(t: float) -> np.ndarray:
    """Drift the blurred album art with a slow sinusoidal UV warp (Apple-like)."""
    Xn, Yn = X / GRID, Y / GRID
    wx = (np.sin(Xn * 6.0 + t * 0.20) + np.cos(Yn * 8.0 + t * 0.13)) * GRID * BG_WARP_AMP * 0.5
    wy = (np.cos(Yn * 7.0 + t * 0.17) + np.sin(Xn * 5.0 + t * 0.15)) * GRID * BG_WARP_AMP * 0.5
    sx = np.clip((X + wx).astype(np.int32), 0, GRID - 1)
    sy = np.clip((Y + wy).astype(np.int32), 0, GRID - 1)
    return _bg_art[sy, sx] * vignette


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE NOW-PLAYING  (Windows SMTC via winsdk — metadata + art only)
# ══════════════════════════════════════════════════════════════════════════════
# A background thread polls the "now playing" session; when the track changes it
# publishes (title, artist, PIL art) and bumps _media_ver.  The render loop picks
# it up and rebuilds the blurred backdrop, the cover card and the text.
_media_pending = None       # (title, artist, PIL.Image|None) awaiting apply
_media_ver     = 0          # bumped by the watcher on every track change
_media_applied = 0          # last version the render loop applied
# Live timeline for the progress bar (updated every poll; 0 duration = fall back).
_media_pos      = 0.0       # last sampled playback position [s]
_media_dur      = 0.0       # current track duration [s]
_media_playing  = False
_media_pos_wall = 0.0       # time.monotonic() when _media_pos was sampled

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SMTC)
    from winsdk.windows.storage.streams import DataReader as _DataReader
    _WINSDK_OK = True
except Exception:            # not Windows, or winsdk not installed
    _WINSDK_OK = False


async def _fetch_media(want_art: bool):
    """Query the current SMTC session →
    (title, artist, PIL|None, pos_sec, dur_sec, playing) or None.
    The thumbnail is only opened/decoded when want_art, so routine polls are cheap."""
    mgr  = await _SMTC.request_async()
    sess = mgr.get_current_session()
    if sess is None:
        return None
    props  = await sess.try_get_media_properties_async()
    title  = (props.title or "").strip()
    artist = (props.artist or "").strip()

    # Timeline + play state — synchronous getters (no await), cheap enough per poll.
    pos = dur = 0.0
    playing = True
    try:
        tl  = sess.get_timeline_properties()
        dur = (tl.end_time - tl.start_time).total_seconds()
        pos = (tl.position - tl.start_time).total_seconds()
        playing = int(sess.get_playback_info().playback_status) == 4   # 4 = Playing
    except Exception:
        pass

    pil = None
    if want_art and props.thumbnail is not None:
        try:
            stream = await props.thumbnail.open_read_async()
            n = int(stream.size)
            if n > 0:
                reader = _DataReader(stream)
                await reader.load_async(n)
                data = bytearray(n)
                reader.read_bytes(data)
                pil = Image.open(io.BytesIO(bytes(data))).convert("RGB")
        except Exception:
            pil = None
    return title, artist, pil, pos, dur, playing


def _media_loop():
    """Poll the now-playing session quickly.  On a track change, publish the text
    right away, then the art as soon as it's available — some apps fill the
    thumbnail a moment after the title.  Fast polling keeps the change latency
    small AND consistent (the old 2 s poll made it feel random)."""
    global _media_pending, _media_ver
    global _media_pos, _media_dur, _media_playing, _media_pos_wall
    text_key = None      # (title, artist) we've already shown text for
    art_key  = None      # (title, artist) we've already shown art  for
    while True:
        try:
            meta = asyncio.run(_fetch_media(False))     # cheap: metadata only
        except Exception:
            meta = None
        if meta is not None:
            title, artist, _, pos, dur, playing = meta
            _media_pos, _media_dur = pos, dur           # progress bar, every poll
            _media_playing, _media_pos_wall = playing, time.monotonic()
            key = (title, artist)
            if title or artist:
                if key != text_key:                     # new track → text immediately
                    text_key = key
                    _media_pending = (title, artist, None)
                    _media_ver += 1
                if key != art_key:                      # (re)fetch art until we have it
                    try:
                        got = asyncio.run(_fetch_media(True))
                    except Exception:
                        got = None
                    if got is not None and got[2] is not None:
                        art_key = key
                        _media_pending = (title, artist, got[2])
                        _media_ver += 1
        time.sleep(MEDIA_POLL_SEC)


def _apply_media(title, artist, pil):
    """Swap in live art + metadata (runs on the main thread)."""
    global _bg_art, cover_art, title_surf, title_pos, artist_surf, artist_pos
    if pil is not None:
        _bg_art   = _bg_from_pil(pil)
        cover_art = _cover_from_pil(pil, ART_SIZE)
    if title:
        title_surf = font_title.render(title, True, (255, 255, 255))
        title_pos  = (CX - title_surf.get_width() // 2, TITLE_Y)
    if artist:
        artist_surf = font_artist.render(artist, True, (200, 200, 212))
        artist_pos  = (CX - artist_surf.get_width() // 2, ARTIST_Y)
    else:
        artist_surf = None


if USE_WINSDK_MEDIA and _WINSDK_OK:
    threading.Thread(target=_media_loop, daemon=True).start()
    print("[SONARIS] now-playing: Windows SMTC (winsdk)")
elif USE_WINSDK_MEDIA:
    print("[SONARIS] winsdk unavailable → pip install winsdk  (using ALBUM_PATH art)")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════
current_bg = compute_background(0.0)
target_bg  = current_bg.copy()
frame = 0
show_dbg = True
paused = False
running = True

while running:
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False
        elif e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
            elif e.key == pygame.K_f:
                show_dbg = not show_dbg
            elif e.key == pygame.K_SPACE:
                paused = not paused
                if AUDIO_ENABLED:
                    (pygame.mixer.music.pause if paused else pygame.mixer.music.unpause)()

    if paused:
        clock.tick(TARGET_FPS)
        continue

    t = frame / TARGET_FPS
    bass = read_audio(t)

    # ── Live now-playing changed → rebuild art / cover / text (main thread) ────
    if _media_ver != _media_applied:
        _media_applied = _media_ver
        _pend = _media_pending
        if _pend is not None:
            _apply_media(*_pend)

    # ── Drifting background (recompute occasionally, lerp every frame) ──────────
    if frame % BG_UPDATE_INTERVAL == 0:
        target_bg = compute_background(t)
    current_bg += (target_bg - current_bg) * BG_LERP_ALPHA

    # ── Ripple height field  Z = Σ wᵢ·profileᵢ  (one einsum) ───────────────────
    # amps gathers each render ring's driving band (echoes reuse the bass bands).
    # wᵢ = sign(aᵢ)·|aᵢ|^RING_CONTRAST · Hᵢ.  The exponent sets how dramatically a
    # loud ring towers over a quiet one; downward pops on the lows are deepened.
    amps = _band_amps[_ring_src]
    w = np.copysign(np.abs(amps) ** RING_CONTRAST, amps) * _band_H
    np.multiply(w, _ring_under, out=w, where=amps < 0)         # deepen dips (lows)
    np.einsum('i,ihw->hw', w, ring_profiles, out=_Zt)
    _Z += (_Zt - _Z) * RING_SMOOTH                             # temporal smoothing

    # ── Surface gradients ∂Z/∂x, ∂Z/∂y (central difference, edge-replicated) ───
    _Zp[1:-1, 1:-1] = _Z
    _Zp[0, 1:-1] = _Z[0];   _Zp[-1, 1:-1] = _Z[-1]
    _Zp[1:-1, 0] = _Z[:, 0]; _Zp[1:-1, -1] = _Z[:, -1]
    np.subtract(_Zp[1:-1, 2:], _Zp[1:-1, :-2], out=_dzdx); _dzdx *= 0.5
    np.subtract(_Zp[2:, 1:-1], _Zp[:-2, 1:-1], out=_dzdy); _dzdy *= 0.5

    # ── Refraction: the ripple slope bends the background beneath it ───────────
    mx = np.clip((X + _dzdx * DISPLACEMENT_SCALE).astype(np.int32), 0, GRID - 1)
    my = np.clip((Y + _dzdy * DISPLACEMENT_SCALE).astype(np.int32), 0, GRID - 1)
    warped = current_bg[my, mx]

    # ── Shading: normals → Lambert diffuse (+ cheap specular glint) ────────────
    inv = 1.0 / np.sqrt(_dzdx * _dzdx + _dzdy * _dzdy + 1.0)
    dot = np.clip((-_dzdx * L[0] - _dzdy * L[1] + L[2]) * inv, 0.0, 1.0)
    shade = (AMBIENT + DIFFUSE * dot)[..., None]

    lit = warped * shade
    if SPEC_INTENSITY > 0.0:
        # Height-driven glint: a broad dot⁸ on low ripples morphs into a very thin
        # dot⁶⁴ line on tall ones, AND scales brighter with peak height — so the
        # taller the crest, the brighter and thinner the light along its top.
        d2 = dot * dot; d4 = d2 * d2; d8 = d4 * d4        # dot⁸  (broad) — no pow()
        d16 = d8 * d8; d32 = d16 * d16; d64 = d32 * d32   # dot⁶⁴ (very thin)
        peak  = np.clip(_Z * (1.0 / RING_HEIGHT), 0.0, 1.0)   # 0…1 height at pixel
        tight = peak * peak                               # thin-in faster with height
        spec  = d8 * (1.0 - tight) + d64 * (tight * SPEC_THIN_BOOST)
        spec *= (SPEC_INTENSITY * (0.35 + 0.65 * bass)
                 * (1.0 + SPEC_PEAK_GAIN * peak) * 255.0)  # brighter with height
        lit += spec[..., None] * SPEC_COLOR
    lit = np.clip(lit, 0, 255).astype(np.uint8)

    # ── Blit grid → smoothscale into the centred square ────────────────────────
    pygame.surfarray.blit_array(grid_surf, np.transpose(lit, (1, 0, 2)))
    upscale_square()
    screen.blit(sq_surf, (SQ_X, SQ_Y))

    # ── Now-playing card: cover art, title, artist, progress bar ───────────────
    pygame.draw.rect(screen, (10, 10, 14),
                     (CARD_X - 3, CARD_Y - 3, ART_SIZE + 6, ART_SIZE + 6))
    screen.blit(cover_art, (CARD_X, CARD_Y))

    screen.blit(title_surf, title_pos)
    if artist_surf is not None:
        screen.blit(artist_surf, artist_pos)

    # Progress: prefer the live SMTC timeline (accurate per song, refreshes on a new
    # track); else the file clock; else a free-running clock.  Extrapolate between
    # polls while playing so the bar moves smoothly.
    if _media_dur > 0.0:
        cur = _media_pos + (time.monotonic() - _media_pos_wall if _media_playing else 0.0)
        cur = min(max(cur, 0.0), _media_dur)
        dur_total = _media_dur
    elif AUDIO_ENABLED and _audio_data is not None:
        pos_ms = pygame.mixer.music.get_pos()
        cur = t if pos_ms < 0 else (pos_ms / 1000.0) % max(DURATION_TOTAL, 1)
        dur_total = DURATION_TOTAL
    else:
        cur = t % DURATION_TOTAL
        dur_total = DURATION_TOTAL
    fill_w = int(BAR_W * min(cur / max(dur_total, 1.0), 1.0))
    pygame.draw.rect(screen, (70, 70, 84),  (BAR_X, BAR_Y, BAR_W, BAR_H), border_radius=2)
    pygame.draw.rect(screen, (240, 240, 250), (BAR_X, BAR_Y, fill_w, BAR_H), border_radius=2)
    cur_sec = int(cur)
    if cur_sec != _cur_sec:
        _cur_sec  = cur_sec
        _cur_surf = font_time.render(_fmt(cur), True, (170, 170, 185))
    screen.blit(_cur_surf, (BAR_X, BAR_Y + 10))
    tot_sec = int(dur_total)
    if tot_sec != _tot_sec:                            # refresh total when the song changes
        _tot_sec  = tot_sec
        _tot_surf = font_time.render(_fmt(dur_total), True, (140, 140, 155))
        _tot_pos  = (BAR_X + BAR_W - _tot_surf.get_width(), BAR_Y + 10)
    screen.blit(_tot_surf, _tot_pos)

    if show_dbg:
        screen.fill((0, 0, 0), (0, 0, SQ_X, 22))
        screen.blit(font_dbg.render(f"{clock.get_fps():4.1f} FPS  {GRID}px  [F/SPC/Q]",
                                    True, (90, 90, 110)), (8, 4))

    pygame.display.flip()
    frame += 1
    clock.tick(TARGET_FPS)

pygame.quit()
if _cava_proc is not None:
    _cava_proc.terminate()
sys.exit()
