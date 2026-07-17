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
