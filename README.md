# Dodger

A single-player arcade shoot-em-up, styled as a retro CRT cabinet. Dodge falling asteroids, shoot them for points, and survive as your ship refits itself through four hulls.

## Play it

No build step, no dependencies. Either:

- **Open directly**: double-click `index.html` and it'll load in your browser.
- **Serve on localhost** (recommended, avoids browser file:// restrictions on some systems):
  ```
  python3 -m http.server 8000
  ```
  then visit `http://localhost:8000`.

## Controls

- **Arrows / WASD** — move
- **Space** — fire (press, don't hold — each press fires one shot)
- **R** — restart after game over

## Mechanics

- Shoot asteroids for points. Gold asteroids pay 3x.
- Catch a falling capsule for a temporary weapon upgrade: **Twin** (parallel shots), **Spread** (3-way fan), or **Rapid** (fast cooldown).
- Score enough and your ship upgrades itself: **Interceptor** → **Interceptor II** (faster) → **Vanguard** (adds a recharging force field) → **Dreadnought** (fastest, permanent twin cannon).
- New hazards unlock as your score climbs: **splitters** that fragment into two shards when shot, **weavers** that drift in a sine wave, and a tanky 3-hit **juggernaut** worth a big bonus.

High score is saved locally in your browser (`localStorage`).

---

# CashoM Ecosystem Map

`cashom-ecosystem-map.html` is an interactive, editable mind map of the CashoM Cannabis Ecosystem whiteboard. It is one self-contained HTML file with no dependencies.

- Click any text to edit it. Hover a box for ⠿ move, ✕ delete and 🎨 color.
- **+ Add box** and **🔗 Add line** (click source, then target; Esc cancels).
- Click a line for color, dash, label and delete. Drag its dot to bend it.
- Autosaves to `localStorage`. **Download JSON** / **Load JSON** to back up or move the board. **Reset to original** restores the whiteboard layout.
- Ctrl/Cmd+Z undoes the last 30 changes (Ctrl/Cmd+Shift+Z redoes).
- Dotted-underlined words are handwriting to double-check.
