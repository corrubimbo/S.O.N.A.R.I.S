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

This is the FILE-AUDIO build: it decodes + FFTs an audio file (no CAVA, no
Windows now-playing).  The visualizer itself is identical to ripple_pi_windows.py.

Run (desktop test):   python ripple_pi.py
Run (Pi, headless):   SDL_VIDEODRIVER=kmsdrm python ripple_pi.py
    Audio:  set AUDIO_FILE to a WAV/FLAC/OGG next to this script.

Performance knob #1 is GRID.  Lower it until you hit your FPS target;
the smoothscale upscale hides the coarser grid.
"""

import os
import sys
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
TARGET_FPS         = 30
PHYS_FPS           = 120      # physics/audio update rate (Hz), decoupled from render.
                             #   The ring spring is sub-stepped to this rate every
                             #   frame, so fast beats snap in as if rendering at
                             #   PHYS_FPS — even though we still draw at TARGET_FPS.
                             #   Only the tiny per-band spring repeats; render doesn't.
USE_SMOOTH_SCALE   = True     # False = faster nearest-neighbour upscale (blockier)
SMOOTH_HALFRES     = True     # Pi speed-up: smoothscale to SQ_SIZE/2 (400px) then a
                             #   cheap nearest ×2 to 800px — ~4× less smoothscale work
                             #   (it has no SIMD path on ARM), still looks smooth.
                             #   Only applies when USE_SMOOTH_SCALE = True.
BG_UPDATE_INTERVAL = 10      # frames between background-drift recomputes
BG_LERP_ALPHA      = 0.16    # per-frame blend toward the new drift target

# ─── ASSETS ───────────────────────────────────────────────────────────────────
# Album art + audio live together in the Audio Assets folder, one pair per track
# (NOBLE.jpg + NOBLE.wav, ACAI.*, HEART_ATTACK.*).  Switch tracks by changing TRACK.
ASSET_DIR = "Audio Assets"
TRACK     = "NOBLE"        # base name of the .jpg/.wav pair to load

# ─── APPLE-MUSIC BACKGROUND ───────────────────────────────────────────────────
ALBUM_PATH    = os.path.join(ASSET_DIR, TRACK + ".jpg")   # album art (in ASSET_DIR)
BG_SAT_BOOST  = 2.2      # saturation boost — Apple's backdrop is vivid
BG_BRIGHTNESS = 0.82     # 0 = black, 1 = full colour
BG_WARP_AMP   = 0.32     # drift amplitude as a fraction of the grid
VIGNETTE      = 0.50     # gentle edge darkening (0 = none)

# ─── NOW-PLAYING CARD ──────────────────────────────────────────────────────────
ART_SIZE     = 190       # cover-art square size on screen [px]
TRACK_TITLE  = ""        # blank → derived from the audio filename
TRACK_ARTIST = "Unknown Artist"   # WAV has no tags — set your artist here

# ─── RIPPLE RINGS ─────────────────────────────────────────────────────────────
N_BANDS        = 6        # frequency-responsive concentric rings — fewer rings =
                          #   wider gaps between them (spacing is derived from the
                          #   count), so each ripple reads clearly on its own
RING_SIGMA_MIN = 1.60     # half-width of the INNERMOST (thinnest) ring        [cells]
                          #   → thickness is POSITIONAL (independent of the pitch that
                          #     drives a ring — see the _freq_src remap below).  Rings
                          #     grow from this thinnest inner ring outward along an
                          #     exponential-ish (power) curve, set by the two below:
RING_SIGMA_LAST_MULT = 3.25 # OUTERMOST ("last") ring σ = this × the thinnest ring
RING_SIGMA_CURVE     = 2.0  # >1 = convex/exponential-like: outer rings thicken in ever
                            #   bigger steps (grow FASTER than linear — so the 5th/outer
                            #   rings outrun a straight ramp); 1.0 = plain linear
RING_HEIGHT      = 4.25   # base peak surface height at full band amplitude —
                          #   taller = steeper slopes, so stronger shading relief
                          #   AND harder crest refraction (warp grows with slope²).
                          #   Bumped from 3.40 to offset the ~0.8× that the centre
                          #   bass ring's small radius applies to every ring via the
                          #   RADIAL_DECAY reference (see below) — keeps the freq rings
                          #   at their previous height now that the echo is enabled.
RING_HEIGHT_HI   = 1.85   # treble-ring height multiplier → highs are very visible
                          #   (tall, sharp).  Bass rings stay ×1.0.
RING_BASS_GAIN   = 1.80   # low-band (bass) sensitivity — applied per pitch, so it
RING_TREBLE_GAIN = 1.20   # high-band (treble) sensitivity — follows the pitch to
                          #   whichever ring the _freq_src remap assigns it to
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
RING_SMOOTH      = 0.48   # temporal blend of the height field (1 = none);
                          #   lower = smoother, more fluid motion.
RING_CONTRAST    = 2.60   # exponent applied to each band's amplitude → ring height.
                          #   Higher = MORE loud-vs-quiet drama, but it crushes the
                          #   subtle band-to-band differences — 2.6 keeps moderate
                          #   bands visible instead of only the loudest towering.
                          #   Sign is preserved.
RING_SPACING_POW     = 1.0  # 1.0 = evenly-spaced rings (uniform gap → the diameter
                             #   grows by a constant step per ring, matching the linear
                             #   thickness ramp).  >1 would bunch the fat LOW-freq
                             #   (outer) rings together so they merge into one thick
                             #   blob — keep at 1.0 for a readable ring-by-ring ramp.
RING_INNER_CLEARANCE = 2.00  # grid-cells of gap between the innermost ring and the
                             #   cover-art corner (1 cell ≈ 5 px on screen).  Trimmed to
                             #   widen the ring band → more spacing between rings, while
                             #   the thin inner ring still clears the cover (~2.8 cells).
RING_EDGE_GAP        = 1.00  # grid-cells of clear space between the OUTERMOST ripple's
                             #   visible edge and the square border.  Trimmed to push the
                             #   outer ring out → more spacing (still clears the border).
# One extra thick "echo" ring near the centre (may sit under the album cover).
# It COPIES the bass band — the bass still drives its own outer ring too — giving a
# big slow bass swell beneath the frequency rings, hugging the cover.
RING_CENTER_COUNT    = 1     # how many centre echo rings (0 = no middle ring)
RING_CENTER_SIGMA    = 6.50  # its half-width [grid cells] — VERY thick (a broad swell,
                             #   ~1.8× the fattest frequency ring)
RING_CENTER_HEIGHT_MULT = 1.3  # middle bump height = this × the OUTERMOST ("last")
                               #   bass ring's height (both post-decay), so it tracks
                               #   that ring at a fixed ratio.  Governs BOTH the bump's
                               #   bass reactivity (swing) and its background warp.
RING_CENTER_GAP      = 4.50  # calm gap [cells] kept between its outer edge and the
                             #   innermost ring — enough that the swell never touches
                             #   it (~2 cells clear), but kept close, not distant
RADIAL_DECAY = 0.8    # ripples weaken as they spread: ring height falls off with
                      #   radius — 0 = off, 1 = full 1/√r physical spreading loss.
                      #   Baked into _band_H once at startup (zero per-frame cost).
ATTACK_MULT  = 0.92   # damping multiplier while a band is RISING — lower bites
                      #   harder, so hits snap in fast like a real splash
RELEASE_MULT = 1.03   # damping multiplier while FALLING (capped at 0.985) —
                      #   higher = slower relax; water rises fast, settles lazily
IDLE_AMP     = 0.05   # gentle swell weight so quiet passages aren't a frozen pond.
                      #   Suspended while PAUSED (space) — pause is completely still,
                      #   bar the background.
IDLE_SPEED   = 1.6    # idle swell phase speed [rad/s]

# ─── LIGHTING & REFRACTION ────────────────────────────────────────────────────
DISPLACEMENT_SCALE = 30.0   # base refraction strength — kept as the reference the
                            #   nonlinear scale below is tuned against (not applied
                            #   directly any more)
DISPLACEMENT_SCALE_NL = DISPLACEMENT_SCALE * 2.5   # slope-weighted refraction: warp
                            #   ∝ slope² (sign kept).  ×2.5 retunes so peak warp
                            #   roughly matches the old linear look — flat areas now
                            #   stay calmer, steep crests smear harder
AMBIENT  = 0.32             # lower ambient + higher diffuse = deeper shadows and
DIFFUSE  = 1.10             #   brighter lit slopes → dramatic ring-to-ring contrast,
                            #   and even a tiny ripple casts a visible bright/dark edge
LIGHT    = np.array([0.70, -0.70, 0.85], dtype=np.float32)   # oblique key light
SPEC_INTENSITY = 1.00       # wet glint strength (0 disables; computed cheaply)
SPEC_COLOR     = np.array([1.00, 0.97, 0.90], dtype=np.float32)
SPEC_THIN_BOOST = 6.0       # brightness of the tight high-peak glint — compensates
                            # for its narrower area so tall rings still read bright
SPEC_PEAK_GAIN  = 3.20      # extra glint brightness scaled by peak height — the
                            # taller the ripple, the brighter (and thinner) its crest.
                            # This is the per-RING glint differentiator: a slightly
                            # louder band reads clearly shinier than its neighbours

# ─── AUDIO ────────────────────────────────────────────────────────────────────
# Analyse an audio file (WAV/FLAC/OGG) with a per-ring FFT.  If it can't be
# loaded, the visualiser falls back to a synthetic beat so it still runs.
AUDIO_ENABLED = True            # play + analyse an audio file
AUDIO_FILE    = os.path.join(ASSET_DIR, TRACK + ".wav")   # analysed audio (pairs with ALBUM_PATH)
AUDIO_LOOP    = True
FFT_WINDOW    = 4096         # larger window → finer frequency bins & steadier
                             #   band energy (esp. cleaner bass separation).
                             #   Must stay a power of 2.  ~93 ms @ 44.1 kHz.
NORM_DECAY    = 0.996        # per-band running-max decay — lower = AGC recovers
                             #   faster in quiet passages → more sensitive


# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO READER
# ══════════════════════════════════════════════════════════════════════════════
_audio_data = _audio_sr = _audio_hann = None
_ring_masks = None
_ring_amp_max = np.ones(N_BANDS, dtype=np.float32)
_band_amps = np.zeros(N_BANDS, dtype=np.float32)   # current ring amplitudes
_band_vels = np.zeros(N_BANDS, dtype=np.float32)   # spring-damper velocities
_last_bass = 0.0

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


def _spring_to(target: np.ndarray) -> None:
    """Reactive spring toward `target`, with per-band damping.
    A sensitivity gamma (<1) lifts quiet detail; low bands under-damp so they
    overshoot into the negative (concave-down pop).  Damping is asymmetric:
    rising bands damp less (fast attack), falling bands damp more (slow release)."""
    global _band_amps, _band_vels
    tgt = np.clip(target, 0.0, 1.0) ** RING_SENSITIVITY
    rising = (tgt - _band_amps) > 0
    damp = np.where(rising, _ring_damp * ATTACK_MULT,
                    np.minimum(_ring_damp * RELEASE_MULT, 0.985))
    _band_vels[:] = _band_vels * damp + (tgt - _band_amps) * RING_SPRING
    _band_amps[:] = np.clip(_band_amps + _band_vels, -1.0, 1.0)


def _audio_target(t: float) -> np.ndarray:
    """Per-band target level ∈ [0,1] for time t (file FFT, else a synthetic beat)."""
    global _ring_amp_max

    # ── file FFT ────────────────────────────────────────────────────────────────
    if AUDIO_ENABLED and _audio_data is not None:
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

    # ── simulation (no / failed audio file) ─────────────────────────────────────
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
    pass   # headless Pi without an audio device — silent FFT-by-clock still works

flags  = (pygame.FULLSCREEN if USE_FULLSCREEN else 0)
screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
pygame.display.set_caption("SONARIS — Ripple")
pygame.mouse.set_visible(False)
clock  = pygame.time.Clock()

if AUDIO_ENABLED and not _init_audio_file():
    AUDIO_ENABLED = False


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

# Ring radii: band 0 (bass) OUTERMOST → band N-1 (treble) innermost — the higher
# the frequency, the closer to the centre.
# Cover art is a square; a circle of radius = half-diagonal reaches its corners.
_px_to_cell   = GRID / SQ_SIZE
_art_corner_g = (ART_SIZE * 0.5) * 1.41421356 * _px_to_cell        # corner in cells
# Furthest ripple: pulled in by ~2σ (its own visible half-width) plus a small gap so
# it clears the border.  The outermost ring is extra-fat (RING_SIGMA_LAST_MULT×), so
# clear it by ITS σ, not the ramp anchor, or it would bleed past the edge.
_sigma_last = RING_SIGMA_MIN * RING_SIGMA_LAST_MULT
r_outer = GRID * 0.5 - 2.0 * _sigma_last - RING_EDGE_GAP
# Innermost (treble, thin) ring is pushed out so it + its width clears the art corner.
r_inner = _art_corner_g + 2.0 * RING_SIGMA_MIN + RING_INNER_CLEARANCE
# Non-uniform spacing: 1-t^p places band 0 (bass) exactly at r_outer and band N-1
# (treble) at r_inner, with the gaps WIDENING toward the centre → the higher a
# ring's frequency, the more clear water between it and its neighbour; the bass
# rings sit closer together near the edge.  Bigger RING_SPACING_POW = stronger.
_t      = np.linspace(0.0, 1.0, N_BANDS, dtype=np.float32)
band_r  = (r_inner + (r_outer - r_inner) * (1.0 - _t ** RING_SPACING_POW)).astype(np.float32)
# Thickness curve: an exponential-ish (power) ramp from the thinnest INNERMOST ring out
# to RING_SIGMA_LAST_MULT× at the OUTERMOST.  RING_SIGMA_CURVE>1 makes it convex, so the
# outer rings grow in progressively bigger steps (faster than linear) while the inner
# rings stay thin and distinct.  band_s[0] lands exactly on RING_SIGMA_MIN×LAST_MULT,
# matching the r_outer border-clearance above.
_u_out  = 1.0 - _t                                             # 1 at outermost … 0 at innermost
band_s  = (RING_SIGMA_MIN * (1.0 + (RING_SIGMA_LAST_MULT - 1.0)
                             * _u_out ** RING_SIGMA_CURVE)).astype(np.float32)

# ── Centre "mid echo" ring: thick, near the middle (may sit under the cover) ────
# Placed inside r_inner with a clear RING_CENTER_GAP between its visible edge and
# the innermost (treble) ring.  It COPIES the bass band (that band still drives its
# own frequency ring — this is an extra ring, not a takeover).
_center_band = 0                                                        # bass band (drives the centre swell)
_rc_top  = r_inner - RING_CENTER_GAP - 1.5 * RING_CENTER_SIGMA
center_r = np.linspace(_rc_top, _rc_top * 0.30, RING_CENTER_COUNT).astype(np.float32)
center_s = np.full(RING_CENTER_COUNT, RING_CENTER_SIGMA, dtype=np.float32)

# Combined render rings = N_BANDS frequency rings + the centre echo.
ring_r = np.concatenate([band_r, center_r]).astype(np.float32)
ring_s = np.concatenate([band_s, center_s]).astype(np.float32)
# Custom pitch→radius layout (user-specified, for N_BANDS = 6).  _freq_src[i] is the
# audio band that drives ring i, where ring 0 is OUTERMOST … ring N-1 INNERMOST.
# Read inner→outer it spells: treble, mids, treble, bass, mids, bass  (of the 6 bands,
# 0-1 = bass, 2-3 = mids, 4-5 = treble).  Pitch is thus decoupled from radius — the
# ring THICKNESS stays positional (band_s: thin inner → thick outer) and is unchanged
# by this remap.  The spring/gain/damping all run per-band upstream; only this final
# gather places a pitch at a radius, so reordering here is all that's needed.
_freq_src = np.array([0, 2, 1, 4, 3, 5], dtype=np.intp)         # outer→inner audio bands
if _freq_src.size != N_BANDS:                                   # N_BANDS changed → plain low→high
    _freq_src = np.arange(N_BANDS, dtype=np.intp)
# The echo copies the bass band (a copy — the bass still drives its own outer ring).
_ring_src = np.concatenate([_freq_src,
                            np.full(RING_CENTER_COUNT, _center_band)]).astype(np.intp)

# Per render-ring height + concave-down depth.  The echo uses its own swell height
# but inherits its source band's dip depth so it behaves like the band it copies.
_band_under_full = np.linspace(RING_UNDERSHOOT, 1.0, N_BANDS).astype(np.float32)
_band_H = np.concatenate([
    np.linspace(RING_HEIGHT, RING_HEIGHT * RING_HEIGHT_HI, N_BANDS),
    np.zeros(RING_CENTER_COUNT),          # centre bump height set below (relative to last bass ring)
]).astype(np.float32)
_ring_under = np.concatenate([
    _band_under_full,
    _band_under_full[_ring_src[N_BANDS:]],
]).astype(np.float32)
# Radial spreading loss: scale each ring's height by (r_min/r)^(0.5·RADIAL_DECAY)
# (echo rings included via their own ring_r entries).  One-time reshape.
_band_H *= ((ring_r.min() / ring_r) ** (0.5 * RADIAL_DECAY)).astype(np.float32)
# Centre bump height = fixed multiple of the OUTERMOST ("last") bass ring — _band_H[0]
# is that ring (band 0 drives it), both post-decay, so the bump tracks it at 1.3×.
_band_H[N_BANDS:] = RING_CENTER_HEIGHT_MULT * _band_H[0]

# Gaussian profile per ring — the only exp() calls in the whole program.
ring_profiles = np.exp(
    -((R[None] - ring_r[:, None, None]) / ring_s[:, None, None]) ** 2
).astype(np.float32)

# Idle-swell phase per render ring (radius-keyed so the swell travels outward).
ring_phase = (ring_r * 0.35).astype(np.float32)

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
    TRACK_TITLE = os.path.splitext(os.path.basename(AUDIO_FILE))[0]
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
#  MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════
current_bg = compute_background(0.0)
target_bg  = current_bg.copy()
_PAUSE_TARGET = np.zeros(N_BANDS, dtype=np.float32)   # paused: spring relaxes to flat
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

    t = frame / TARGET_FPS
    if paused:
        # Paused: keep rendering so the background can keep drifting, but the
        # rings relax to flat and hold completely still (idle swell suspended).
        for _ in range(_PHYS_SUBSTEPS):
            _spring_to(_PAUSE_TARGET)
        bass = 0.0
    else:
        bass = read_audio(t)

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
    # Idle swell only while running — PAUSE (space) must be completely still, so it
    # is suspended and the rings settle flat.
    if not paused:
        w += IDLE_AMP * np.sin(ring_phase - t * IDLE_SPEED).astype(np.float32)
    np.einsum('i,ihw->hw', w, ring_profiles, out=_Zt)
    _Z += (_Zt - _Z) * RING_SMOOTH                             # temporal smoothing

    # ── Surface gradients ∂Z/∂x, ∂Z/∂y (central difference, edge-replicated) ───
    _Zp[1:-1, 1:-1] = _Z
    _Zp[0, 1:-1] = _Z[0];   _Zp[-1, 1:-1] = _Z[-1]
    _Zp[1:-1, 0] = _Z[:, 0]; _Zp[1:-1, -1] = _Z[:, -1]
    np.subtract(_Zp[1:-1, 2:], _Zp[1:-1, :-2], out=_dzdx); _dzdx *= 0.5
    np.subtract(_Zp[2:, 1:-1], _Zp[:-2, 1:-1], out=_dzdy); _dzdy *= 0.5

    # ── Refraction: the ripple slope bends the background beneath it ───────────
    # Slope-weighted (∝ slope², sign kept): calm water stays glassy, steep crests
    # smear hard.  Cost: one extra |slope| multiply per axis.
    mx = np.clip((X + _dzdx * np.abs(_dzdx) * DISPLACEMENT_SCALE_NL).astype(np.int32), 0, GRID - 1)
    my = np.clip((Y + _dzdy * np.abs(_dzdy) * DISPLACEMENT_SCALE_NL).astype(np.int32), 0, GRID - 1)
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
        spec *= (SPEC_INTENSITY * (0.60 + 0.40 * bass)
                 * (1.0 + SPEC_PEAK_GAIN * peak) * 255.0)  # brighter with height.
                 # Gate mostly constant (was 0.35+0.65·bass): each ring's glint now
                 # tracks its OWN height via `peak`, not the global bass — so per-
                 # frequency differences stay visible even between bass hits.
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

    # Playback position (wraps for looped audio) → progress bar + m:ss labels.
    if AUDIO_ENABLED and _audio_data is not None:
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
sys.exit()
