# SONARIS MK5 — `ripple_pi_windows.py` Reference (AI GENERATED AND VERIFIED)

A plain-language guide to the ripple music visualizer: what it does, how it works, and
what every setting ("knob") near the top of the file changes.

> **The 30-second version:** Your album cover fills the screen, blown up big, blurry,
> and gently swaying. On top of it, glowing rings spread outward like ripples when you
> drop a stone in a pond — and they bounce in time with the music (bass, mids, and
> treble each move different rings). Lighting and a "looking through wavy glass" effect
> make them look like real water. It's built to run smoothly on a tiny, cheap computer
> (a Raspberry Pi), so it does the heavy work once at the start and only a little quick
> work each frame.
>
> Every section starts with an **"In plain terms"** box (no jargon), then gives the
> precise details for anyone who wants them.

> **Sibling file:** [`ripple_pi_linux.py`](ripple_pi_linux.py) is the deployment build —
> the **same visualizer** but with a **file-only** audio path (no CAVA, no Windows
> now-playing). Change the visuals here, mirror them there.

---

## 1. What it is

> **In plain terms:** One program that shows ripples-on-water dancing to music, over a
> big blurry version of the album art. "Concentric" just means the rings share one
> center, like a bullseye. It's designed to stay smooth on a Raspberry Pi, which is why
> so much care goes into keeping it fast.

It draws **concentric, audio-reactive ripple rings** floating on a blurred, colorful,
slowly drifting album-art background. The rings are lit and bend the background like
real water.

The whole design follows one rule so it runs at **20–30 FPS on a Raspberry Pi Zero 2 W**:
**do the slow work once at startup, then keep each frame cheap.** Everything is computed
on a small `GRID × GRID` grid (160×160 by default) and enlarged to the full 800-px square
in one step — which also smooths it for free.

---

## 2. Quick start

> **In plain terms:** Type one line to run it. Install the few free helper programs in
> the table first. Your cover + song live in the `Audio Assets` folder; pick which song
> with the `TRACK` setting. If a file is missing it invents a placeholder so it still runs.

```bash
# Desktop test (windowed):
python ripple_pi_windows.py

# Raspberry Pi, headless (straight to the display, no desktop):
SDL_VIDEODRIVER=kmsdrm python ripple_pi_windows.py
```

**Helper programs it needs:**

| Package | What it's for | Needed? |
|---|---|---|
| `pygame` | opens the window, draws, plays audio | yes |
| `numpy` | does all the fast number-crunching | yes |
| `Pillow` (`PIL`) | loads and blurs the album art | yes |
| `soundfile` | reads a song file (the `"file"` source) | only for file audio |
| `cava` | listens to live system audio (the `"cava"` source) | only for live audio |
| `winsdk` | reads Windows "now playing" title/art | optional, Windows only |

**Assets:** art + audio live together in the **`Audio Assets/`** folder, one `.jpg`+`.wav`
pair per song. Pick a song by setting **`TRACK`** (e.g. `"NOBLE"`, `"ACAI"`,
`"HEART_ATTACK"`) — that one word switches both the cover and the audio.

## 3. Controls

| Key | What it does |
|---|---|
| `Space` | Pause/unpause. The rings settle flat and hold still; the background keeps drifting. |
| `F` | Show/hide the little FPS counter. |
| `Q` or `Esc` | Quit. |

---

## 4. How the visualizer is built (the big picture)

> **In plain terms:** Like a cook who chops everything before turning on the stove, the
> program does all the slow work once at startup — mainly pre-drawing the ring shapes.
> After that, each frame only does a little quick work, so it never stutters. ("A frame"
> = one still picture; it draws about 30 per second.)

**Done once, at startup:**
- Load, blur, and boost the color of the album art into the background.
- Work out where each ring sits, how thick and tall it is, and which sound drives it.
- **Pre-draw one ring shape per ring** and keep them in memory. This is the expensive
  part, and it never runs again — the trick that keeps every frame cheap.

**Every frame (fast):**
1. **Listen to the music** → get a loudness level for each frequency band → move the ring
   "springs" toward those levels.
2. **Drift the background** a little.
3. **Build the water surface** by adding up the pre-drawn ring shapes, each scaled by how
   loud its sound is right now.
4. **Measure the slope** of that surface everywhere.
5. **Bend the background** using the slope (the wavy-glass look).
6. **Light it** — add shadow, brightness, and a wet sparkle on the crests.
7. **Enlarge** the small picture to full screen and draw the song card on top.

No heavy math (no new shape-drawing, no big memory allocations) happens inside the loop —
that's what keeps it fast.

---

## 5. Each frame, step by step

> **In plain terms:** The recipe it repeats every frame: (1) hear the music and nudge each
> ring up/down, (2) shape those nudges into a bumpy water surface, (3) measure how steep
> it is, (4) bend the background with that steepness, (5) add light and sparkle, (6)
> enlarge and draw the song info. The subsections detail each step.

### 5.1 Build the water surface (`Z`)

> **In plain terms:** Decides how tall each ring is *right now* — louder sound makes a
> taller ring. It stacks all the ring shapes into one bumpy surface, easing toward it
> smoothly so nothing jitters.

Each ring's height = how loud its sound is (raised to a power for drama, times the ring's
base height). Those weights multiply the pre-drawn ring shapes and get summed into the
surface `Z`. `Z` eases toward the new target each frame (controlled by `RING_SMOOTH`) so
motion stays fluid. A tiny idle wobble is added so silence isn't frozen.

### 5.2 Measure the slope

> **In plain terms:** Figures out how steep the water is at every point — which way it
> tilts and how sharply. Steepness is what makes the lighting and glass-bending possible.

It compares each pixel's height to its neighbors' to get the slope in x and y.

### 5.3 Bend the background (refraction)

> **In plain terms:** "Refraction" is how things look bent through water or wavy glass.
> Where a ripple is steep, the background behind it gets shoved sideways; where the water
> is flat, the background stays clear. The steeper the slope, the more it bends.

The bend grows with the **square** of the slope, so flat water stays glassy and only steep
crests smear the background hard. `DISPLACEMENT_SCALE_NL` sets how strong this is.

### 5.4 Light it

> **In plain terms:** Adds shadow and brightness so ripples look 3D, as if lit from one
> side, plus a bright "sparkle" on the crests like sun on wet water — tight and sharp on
> tall crests, soft and wide on gentle ones.

A simple lighting formula brightens slopes facing the light and darkens those facing away
(`AMBIENT` = base light, `DIFFUSE` = how strong the shading is). The sparkle is done with
cheap repeated multiplication (no slow math), getting thinner and brighter on taller rings.

### 5.5 Draw it

> **In plain terms:** The small picture is stretched up to full size (which also smooths
> it), then the cover, title, and progress bar are drawn on top.

---

## 6. All the settings (knobs)

> **In plain terms:** These are the values near the top of the file. Change a number,
> restart, and the look or behavior changes — nothing else to touch. Each group below is
> one set of related knobs.

### Display — the window size

| Setting | Default | What it does |
|---|---|---|
| `WIDTH, HEIGHT` | `800, 800` | Window size in pixels. The ripple fills a square this tall. |
| `USE_FULLSCREEN` | `False` | Fill the whole screen (turn on for the Pi). |

### Performance — speed vs. quality

> If it runs slow or choppy, this is the group to adjust — mainly `GRID`.

| Setting | Default | What it does |
|---|---|---|
| `GRID` | `160` | **The #1 speed knob.** The internal working resolution. Lower it (128, 112) if it's slow — the final enlarge hides the coarseness. Cost roughly quadruples if you double it. |
| `TARGET_FPS` | `30` | How many frames per second it aims to draw. |
| `PHYS_FPS` | `120` | How often the ring "springs" update. Done a few times per frame so fast beats still land on time. Raising it tightens the beat-sync and costs almost nothing. |
| `USE_SMOOTH_SCALE` | `True` | Enlarge the small picture smoothly (off = blocky but faster). |
| `SMOOTH_HALFRES` | `True` | Pi speed trick: enlarge to half-size smoothly, then double it cheaply — ~4× faster on the Pi, looks the same. |
| `BG_UPDATE_INTERVAL` | `10` | How many frames between recalculating the background's drift. |
| `BG_LERP_ALPHA` | `0.1` | How fast the background eases toward its new drifted position (small = slow, smooth). |

### Background — the blurred album art

> How the backdrop looks — how colorful, how bright, how much it drifts, how dark the edges.

| Setting | Default | What it does |
|---|---|---|
| `ASSET_DIR` | `"Audio Assets"` | The folder your art + music live in. |
| `TRACK` | `"NOBLE"` | Which song to load — one word switches both the cover and the audio. |
| `ALBUM_PATH` | *(built from `ASSET_DIR`+`TRACK`)* | The cover image. Built automatically; also used as the fallback cover. |
| `BG_SAT_BOOST` | `2.2` | How vivid/colorful the blurred background is (higher = more saturated). |
| `BG_BRIGHTNESS` | `0.82` | How bright the background is (0 = black, 1 = full). |
| `BG_WARP_AMP` | `0.32` | How far the background slowly sways. |
| `VIGNETTE` | `0.50` | How much the edges darken (0 = none). |

### Now-playing card — the info panel in the middle

| Setting | Default | What it does |
|---|---|---|
| `ART_SIZE` | `160` | Size of the sharp cover square in the middle [px]. |
| `TRACK_TITLE` | `""` | Song title. Blank = use the filename. |
| `TRACK_ARTIST` | `"Unknown Artist"` | Artist name under the title. |
| `TITLE_MAX_W` | `400` | How wide the title area is. Longer titles scroll; shorter ones stay centered. |
| `TITLE_SCROLL_SPEED` | `40` | How fast a long title scrolls [px/sec]. |
| `TITLE_SCROLL_GAP` | `60` | The blank gap before a scrolling title loops back around. |
| `TITLE_LOOP_PAUSE` | `20.0` | How long it pauses on the start after each scroll loop [sec]. |
| `USE_WINSDK_MEDIA` | `True` | Grab the song's title/art from Windows' "now playing" (Spotify, etc.). |
| `MEDIA_POLL_SEC` | `0.3` | How often it checks for a song change. |

### Lighting & refraction — how the rings look

| Setting | Default | What it does |
|---|---|---|
| `DISPLACEMENT_SCALE` | `30.0` | A reference number the real bend strength is based on (not used directly). |
| `DISPLACEMENT_SCALE_NL` | *(= ×2.5)* | How strongly ripples bend the background. Higher = more distortion. |
| `AMBIENT` | `0.32` | Base flat light everywhere. Lower = darker shadows. |
| `DIFFUSE` | `1.10` | How bright the lit sides get. Higher = punchier light/shadow. |
| `LIGHT` | `[0.70, -0.70, 0.85]` | The direction the "sun" shines from. |
| `SPEC_INTENSITY` | `1.00` | How bright the wet sparkle on crests is (0 = off). |
| `SPEC_COLOR` | warm white | The tint of that sparkle. |
| `SPEC_THIN_BOOST` | `6.0` | Extra brightness for the thin sparkle line on tall crests. |
| `SPEC_PEAK_GAIN` | `3.20` | Makes taller ripples sparkle more — helps a louder ring stand out. |

### Audio — where the sound comes from

| Setting | Default | What it does |
|---|---|---|
| `AUDIO_SOURCE` | `"cava"` | Where sound comes from: `"file"` (a song file), `"cava"` (whatever your system is playing), or `"sim"` (a fake beat). Falls back to `"sim"` if a source fails. |
| `BAND_EDGES` | *(7 edges, see §8)* | The cutoff frequencies [Hz] that split the sound into the bands. One shared split for all sources. |
| `AUDIO_FILE` | *(built from `ASSET_DIR`+`TRACK`)* | The song to analyze (for the `"file"` source). |
| `AUDIO_LOOP` | `True` | Repeat the song when it ends. |
| `FFT_WINDOW` | `4096` | How big a chunk of audio it analyzes at once. Bigger = cleaner bass, a touch more lag. |
| `NORM_DECAY` | `0.996` | Auto-volume: how fast it re-sensitizes in quiet parts (lower = faster). |
| `AUDIO_LATENCY_MS` | `60` | Beat-sync nudge for the file source: look this many ms ahead so ripples land on the beat. (No effect on CAVA.) |
| `CAVA_AUTOSTART` | `True` | Launch CAVA automatically vs. read one you started yourself. |
| `CAVA_BARS` | `32` | How many frequency bars CAVA sends, which then get grouped into the bands. |
| `CAVA_FIFO` | `/tmp/cava_fifo` | The pipe path when you run CAVA yourself. |

> **CAVA sync note:** with `CAVA_AUTOSTART=True`, CAVA is launched with the script's own
> settings, which **override** your `~/.config/cava/config`. So the smoothing that controls
> beat-sync (`noise_reduction`, default `40`: lower = snappier, higher = laggier) must be
> changed inside the script's `_CAVA_CFG`, not your user config.

### Ripple rings — the rings themselves

> The biggest group, because the rings are the whole point. Each ring has three
> **independent** settings — where it sits, how thick it is, and which sound moves it — so
> you can change one without disturbing the others (explained in §7). "σ" (sigma) just
> means a ring's thickness.

| Setting | Default | What it does |
|---|---|---|
| `N_BANDS` | `7` | How many frequency rings. Fewer rings = more space between them. |
| `RING_SIGMA_BASE` | `1.60` | The "1×" reference thickness the two multipliers below scale from. |
| `RING_SIGMA_BASS_MULT` | `2.50` | Outermost (bass) ring thickness = this × base → fat. |
| `RING_SIGMA_TREBLE_MULT` | `0.80` | Innermost (treble) ring thickness = this × base (under 1× → thin). |
| `RING_SIGMA_CURVE` | `2.0` | How thickness ramps from thin-inner to fat-outer. >1 = stays thin longer then fattens fast; 1 = even steps. |
| `RING_HEIGHT` | `4.25` | How tall a ring gets at full volume. Taller = steeper = more dramatic light and bending. |
| `RING_HEIGHT_HI` | `1.85` | Extra height for the treble rings so highs really pop. |
| `RING_BASS_GAIN` | `1.80` | How sensitive the low (bass) sounds are. |
| `RING_TREBLE_GAIN` | `1.20` | How sensitive the high (treble) sounds are. |
| `RING_SENSITIVITY` | `0.65` | Lifts quiet detail (below 1 makes soft sounds more visible). |
| `RING_SENS_MULT` | `1.00` | Overall input volume, kept at 1 so bands don't all max out. |
| `RING_SPRING` | `0.095` | How stiff the ring springs are — higher = snappier, tighter to the beat. |
| `RING_DAMP_LOW` | `0.85` | How loose the bass springs are — low = they overshoot and "punch" downward. |
| `RING_DAMP_HIGH` | `0.94` | How tight the treble springs are — high = crisp, no wobble. |
| `RING_UNDERSHOOT` | `2.10` | How deep the bass dips below the surface on the downbeat. |
| `RING_SMOOTH` | `0.65` | How much motion is smoothed over time. Lower = more fluid but slightly laggy; higher = snappier. |
| `RING_CONTRAST` | `2.60` | How dramatically loud rings tower over quiet ones (higher = more drama, but tiny differences vanish). |
| `RING_SPACING_POW` | `1.0` | Ring spacing. Keep at 1.0 for even gaps (higher bunches the outer rings together). |
| `RING_INNER_CLEARANCE` | `2.00` | Gap between the innermost ring and the cover art [cells]. |
| `RING_EDGE_GAP` | `1.00` | Gap between the outermost ring and the screen edge [cells]. |

**The center "bump"** — one big, wide, slow ring under the cover that swells with the bass,
like a heartbeat behind everything:

| Setting | Default | What it does |
|---|---|---|
| `RING_CENTER_COUNT` | `1` | How many center bumps (0 = off). |
| `RING_CENTER_SIGMA` | `6.50` | How wide the center bump is — very wide, a broad swell. |
| `RING_CENTER_HEIGHT_MULT` | `1.3` | Bump height = this × the outermost bass ring, so they rise and fall together. |
| `RING_CENTER_GAP` | `4.50` | Gap kept between the bump and the innermost ring so they don't touch. |

**Motion / realism** — how the rings *move* to feel like water:

| Setting | Default | What it does |
|---|---|---|
| `RADIAL_DECAY` | `0.8` | Ripples fade as they spread outward, like real waves (0 = off, 1 = full). |
| `ATTACK_MULT` | `0.92` | How fast rings jump UP on a hit (lower = snappier). |
| `RELEASE_MULT` | `1.03` | How slowly rings settle back DOWN (higher = lazier). |
| `IDLE_AMP` | `0.05` | A gentle always-on swell so it's never dead-still during silence (off while paused). |
| `IDLE_SPEED` | `1.6` | How fast that idle swell moves. |

---

## 7. How the rings are laid out (details)

> **In plain terms:** Each ring is described by three things kept separate: **where it
> sits**, **how thick it is**, and **which sound moves it**. Keeping them separate means
> you can change one without touching the others.

All three are indexed by **position** (index `0` = outermost, last = innermost).

### 7.1 Where each ring sits

> **In plain terms:** The rings are spread evenly from just outside the cover to just
> inside the screen edge, with small margins so none gets cut off or covers the art.

The outermost ring is placed near the edge (pulled in by its own fat width so it doesn't
bleed off), the innermost just outside the cover, and the rest spread evenly between
(`RING_SPACING_POW = 1.0` = even spacing).

### 7.2 How thick each ring is

> **In plain terms:** The innermost ring is thinnest and rings get fatter toward the
> outside — not evenly, but speeding up, so the outermost (bass) ring is much fatter than
> the rest. Thickness depends only on position, never on which sound drives the ring.

Thickness runs from the innermost value (`RING_SIGMA_BASE × RING_SIGMA_TREBLE_MULT`, thin)
to the outermost (`RING_SIGMA_BASE × RING_SIGMA_BASS_MULT`, fat) along a curve set by
`RING_SIGMA_CURVE`. With the current 7-ring defaults the thickness runs, inner → outer:

| | inner … outer |
|---|---|
| **σ (cells)** | 1.28 → 1.36 → 1.58 → 1.96 → 2.49 → 3.17 → **4.00** |

Because `RING_SIGMA_CURVE = 2.0`, the inner (treble) rings stay thin and distinct while the
outer (bass) rings fatten fast — treble under 1× base, bass at 2.5×.

### 7.3 Which sound drives which ring (`_freq_src`)

> **In plain terms:** Normally you'd expect low sounds on the outer rings and highs on the
> inner ones, but this one list lets you shuffle it freely. Changing it only changes *what
> each ring listens to* — not its size or position.

`_freq_src = [0, 1, 3, 2, 5, 4, 6]` lists the audio band for each ring, outermost → innermost.
Reading it **inner → outer** gives the current custom order (bars `7,5,6,3,4,2,1`):

| ring | innermost | | | | | | outermost |
|---|---|---|---|---|---|---|---|
| **band** | 6 Air | 4 Upper-Mid | 5 Treble | 2 Low-Mid | 3 Midrange | 1 Bass | 0 Sub-Bass |

So bass/sub-bass sit on the fat outer rings and treble on the thin inner ones. This is the
**only** place a sound is tied to a position — the volume/spring math all happens per-band
first, so reordering here changes nothing else. (If `N_BANDS` isn't 7 it falls back to a
plain low→high order.)

### 7.4 How tall each ring is (and fading + the bump)

> **In plain terms:** Treble rings are made taller so highs pop. Ripples also fade as they
> travel outward, like real waves. The center bump is tied to always be 1.3× as tall as
> the outermost bass ring, so the two move together.

Heights ramp from the outer rings up to the taller inner (treble) rings, then get scaled
down with distance (`RADIAL_DECAY`) to mimic waves losing energy. The center bump's height
is pinned to `RING_CENTER_HEIGHT_MULT` × the outermost bass ring.

### 7.5 The pre-drawn ring shapes

> **In plain terms:** The actual ring shapes are drawn once at startup and reused every
> frame. This "draw once, reuse forever" is the main reason the app stays fast.

One smooth, soft-edged bump shape per ring is stored in memory. Building the water surface
each frame is then just adding these up, scaled by loudness — no shape-drawing in the loop.

---

## 8. How sound becomes movement

> **In plain terms:** It splits the music into a handful of loudness levels (bass, mids,
> treble) and each ring follows its level. Instead of snapping instantly, rings ride on
> "springs" so they bob and settle naturally, like water.

**The 7 frequency bands (`BAND_EDGES`).** Both real sources split the sound the same way —
an octave (musical) split across 20 Hz–20 kHz:

| band | name | range | what it captures |
|---|---|---|---|
| 0 | Sub-Bass | 20–100 Hz | deep kick "thump" and sub-bass drops |
| 1 | Bass | 100–250 Hz | bassline fundamentals, lower rhythm |
| 2 | Low-Mid | 250–630 Hz | body/warmth of vocals, guitars, keys |
| 3 | Midrange | 630–1600 Hz | heart of melodies, leads, voice clarity |
| 4 | Upper-Mid | 1600–4000 Hz | "attack": snare snap, guitar/vocal bite |
| 5 | Treble | 4000–10000 Hz | brilliance/presence, hi-hats, cymbals |
| 6 | Air | 10000–20000 Hz | highest-end harmonics and sparkle |

(Which *ring* each band drives is in §7.3.)

**The three sources:**
- **`"file"`** — reads the song, looks at a short slice (nudged ahead by `AUDIO_LATENCY_MS`
  for sync), measures how much energy is in each band, and auto-adjusts the volume so quiet
  parts still show.
- **`"cava"`** — a background helper listens to whatever your system is playing and sends
  frequency bars; the script groups those bars into the same 7 bands. It keeps the loudest
  reading between frames so quick beats are never missed.
- **`"sim"`** — a fake beat (decaying bass + shimmering highs) used when there's no audio.

### The springs (why it feels like water)

> **In plain terms:** Each ring is on a spring: it shoots up fast when the music hits, then
> sinks back slowly. Bass rings are extra loose, so they can overshoot and briefly dip
> *below* the surface for a satisfying "punch."

Rising sounds pull a ring up quickly (`ATTACK_MULT`); falling sounds let it settle slowly
(`RELEASE_MULT`). `RING_SPRING` sets overall snappiness; the bass rings are loosely damped
so they overshoot into a downward dip.

**Beat-sync is about lag, not FPS** — nothing here touches the render speed. To tighten it:
lower CAVA's `noise_reduction`, raise `RING_SMOOTH` / `RING_SPRING` / `PHYS_FPS`, or set
`AUDIO_LATENCY_MS` (file source only).

---

## 9. Now-playing (Windows only)

> **In plain terms:** On Windows it can read whatever song is currently playing (Spotify,
> a browser, etc.) and show its title, artist, cover, and progress. This only fills in the
> text and picture — the ring bouncing still comes from the audio. Off Windows (or without
> the helper), it just uses your cover image.

A background check polls the "now playing" info every `MEDIA_POLL_SEC` and, on a song
change, swaps in the new title, artist, and cover.

### 9.1 The scrolling title

> **In plain terms:** If a title is too long to fit, it slides sideways like a news ticker
> to show the whole thing, then rests on the start for a bit before going again. Short
> titles just sit centered.

A too-long title scrolls smoothly in one direction and loops seamlessly (a second copy
follows behind so there's no jump), pausing `TITLE_LOOP_PAUSE` seconds on the start after
each loop.

---

## 10. Making it faster / changing the look

> **In plain terms:** If it's slow, lower `GRID` first — the final enlarge hides the
> difference. Below that is a cheat-sheet for common "I want it to look like X" tweaks.

**If it's running slow,** in order of impact:
1. **Lower `GRID`** (160 → 128 → 112). Biggest win.
2. Keep **`SMOOTH_HALFRES = True`** on the Pi.
3. Fewer rings (`N_BANDS`) — but that changes the look.
4. Turn off the sparkle: `SPEC_INTENSITY = 0`.

**Memory:** the pre-drawn ring shapes take about `n_rings × GRID² × 4 bytes` (~0.8 MB at
the defaults: 8 shapes × 160² × 4). This grows fast with `GRID`, so re-check before raising it.

**Common look tweaks:**
- Bigger loud-vs-quiet drama: `RING_CONTRAST`.
- Fatter/thinner rings: `RING_SIGMA_BASS_MULT` / `RING_SIGMA_TREBLE_MULT` (and
  `RING_SIGMA_CURVE` for how fast they fatten).
- More space between rings: fewer bands, or widen `RING_INNER_CLEARANCE` / `RING_EDGE_GAP`.
- Calmer/wilder background bending: `DISPLACEMENT_SCALE_NL`.
- Deeper shadows / brighter sparkle: `AMBIENT` / `DIFFUSE` / `SPEC_*`.
- Bigger/smaller center bump: `RING_CENTER_HEIGHT_MULT`, `RING_CENTER_SIGMA`.
- Tighter beat sync (all free): lower CAVA `noise_reduction`, raise `RING_SMOOTH` /
  `RING_SPRING` / `PHYS_FPS`, or set `AUDIO_LATENCY_MS` (file source). See §8.

---

## 11. Things that look like bugs but aren't

- **The docstring is out of date:** it says "no album card / no title text," but the current
  build *does* draw a now-playing card.
- **The fattest outer ring blends into its neighbor** — intended (a bold bass band), not a bug.
- **`RING_SPACING_POW > 1`** bunches the fat outer rings into one blob — keep it at `1.0`.
- **The ring order (`_freq_src`) is written for 7 bands.** Change `N_BANDS` and it reverts to a
  plain low→high order; `BAND_EDGES` must always have exactly `N_BANDS + 1` values.
- **CAVA's autostart config wins.** Editing `~/.config/cava/config` does nothing while
  autostart is on — change the script's `_CAVA_CFG` instead.
- **A failed audio source silently becomes `"sim"`** — check the startup line in the console
  to see which source is actually live.
