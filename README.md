# Scrapwise

Revise a sample cutting order in plain English, then download the SVG checked for that exact revision. Scrapwise is a text-based Alexa+ simulation: change whole-set quantities or existing-sheet availability, and see the resulting order and cutting layout together.

## Run locally

Use Python 3.12 or newer. The setup installs Pyclipper 1.4.0, Shapely 2.1.2 and NumPy 2.5.3 into this folder's `.venv`:

```sh
python3 setup.py
```

Install [Ollama](https://ollama.com/download) separately. Start its local service if one is not already running, and obtain the model if it is absent:

```sh
ollama serve
ollama pull qwen2.5:7b
```

The app connects to `http://127.0.0.1:11434`. Its model check requires manifest SHA-256 `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`; a changed manifest produces an error rather than silently substituting a model. Model weights and Ollama binaries are supplied separately.

```sh
.venv/bin/python run.py --port 8767
```

Open `http://127.0.0.1:8767/`. The server uses the launching Python interpreter and binds locally. Choose another available port with `--port` if needed.

Python dependency setup was verified in a new package-local environment on a Mac M4 using Python 3.14 and the existing exact Ollama model. Installation on a clean machine, a new model download and other platforms have not been verified. The approved source package was replayed from an unpacked copy on that same Mac with the existing exact model: three order revisions produced checked SVGs, the browser downloaded the final file, and two unsupported requests preserved the prior order and layout. This MIT-release copy keeps the same runtime code and data; its own archive replay is pending.

## Try an order revision

Start a fresh session and submit these requests in sequence:

1. “Please make a cutting layout with one of each part. Use the stock options listed here and leave all the other settings as they are.” Expect 142 piece copies.
2. “We now need twice as many of every part. Please redo the cutting layout, keeping the same stock options and all the other settings.” Expect 284 piece copies.
3. “Please put the order back to the original quantities, one of each part. We cannot use scrap-1 anymore, so leave it out of the cutting layout. Keep the other stock options and all the other settings the same.” Expect 142 copies and `scrap-1` unavailable.

After success, download the checked SVG. The saved file is checked against the order for piece counts, original geometry, rotations, stock quantities, spacing and margins before the current order updates.

Try “Please make 1.5 copies of every part.” Also try “Please redo the cutting layout with one of each part, but increase the gap between parts from 2 to 3. Keep the listed stock options and the other settings the same.” These requests should ask for clarification and preserve the current order and previous checked preview/download. Reset restores the original order and clears that selection.

## Sample and scope

The 142 outlines come from [SVGnest's author demonstration](https://svgnest.com/), not a customer order. The synthetic inventory has four 255.911 × 169.6175 existing sheets and up to two 511.822 × 339.235 purchase-option sheets. Measurements use original SVG coordinates, not asserted millimetres. Geometry stays fixed, spacing is 2, margin is 1, rotations are 0°/90°/180°/270°, and mirroring is disabled. The solver searches 18 attempts per stock option, prioritizing purchased area then total used area. A checked layout does not establish a global optimum, material savings, physical cutting or human time savings.

Codex assisted development. Supported runtime requests use local Qwen2.5:7b; literal fractional-copy rejection is a program check without a model call. This simulation does not use a real Alexa backend.

## Attribution and license

The full SVGnest MIT notice credits Copyright (c) 2015 Jack Qiao and accompanies the sample and derived data. Exact model and geometry-library notices are retained under `THIRD_PARTY/`; see `THIRD_PARTY_NOTICES.md`. New application code is released under the MIT license, Copyright (c) 2026 Oxygen56, in `LICENSE`. Third-party samples, models, libraries and runtimes retain their separate notices and terms.
