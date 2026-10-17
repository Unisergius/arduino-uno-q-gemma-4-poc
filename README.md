# arduino-uno-q-gemma-4-poc
just a test poc to use arduino uno q and gemma 4

**Garden Steward**: a solar-powered, fully offline garden assistant. Gemma 4 E2B runs on an
Arduino UNO Q, decides when to water and explains why. The first demo is a "Paper Garden" simulation.

- [Design: how it works and how Gemma 4 is used](docs/design.md)
- [Brainstorm: the ideas we considered](docs/brainstorm.md)
- [The app: `app/garden-steward/`](app/garden-steward/README.md) (wiring, run on the board, demo script)
- [Test environment: no board, no camera](app/garden-steward/README.md#4-test-environment-a-laptop-no-board-no-camera) (`python3 app/garden-steward/python/laptop.py --no-llm`)
- [Phase 0 speed test: `spike/`](spike/README.md) (run this on the board first)
