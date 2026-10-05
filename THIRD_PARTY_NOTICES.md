# Retained third-party notices

This is a source-only release. It contains no installed libraries, model weights or runtime binaries. Full existing notices are retained byte for byte; they do not become the application's MIT license.

## SVGnest demonstration input

The input `data/cutting-author-demo.svg` is the SVG embedded in the SVGnest author's repository [index.html](https://github.com/Jack000/SVGnest/blob/master/index.html), used by its [demonstration](https://svgnest.com/). The original saved HTML, retrieval record and complete MIT notice are in `intelligence/research/cutting-output-20261003/root-sources/`. The notice states **Copyright (c) 2015 Jack Qiao** and must accompany the sample and derived part data. The full notice SHA-256 is `63249e67e62c3c4142252688c170ab27fa401f55a96f12b54cd6187ba2f699af`. The sample SHA-256 is `0d67c64c91765eccf197761737b610a5fb5bccbf4976930b94540a540f3a636c`.

No sample-specific alternative terms were observed in the reviewed source. The input's external creator or rights chain has not been independently verified. This package does not claim ownership of those outlines. SVGnest is credited for its demonstration input; the Python packing program was separately written during this work.

## Model and external runtime

**Qwen2.5-7B-Instruct**, Alibaba Cloud, is supplied separately through the `qwen2.5:7b` Ollama tag. The [author model license](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/main/LICENSE) is Apache-2.0, Copyright 2024 Alibaba Cloud. The exact existing license layer, SHA-256 `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e`, is copied in full to `THIRD_PARTY/Qwen2.5-7B-Instruct/LICENSE`. Model weights are not redistributed here. The original checked model manifest is `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` and model blob digest is `2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730`.

**Ollama** is an independently installed runtime, not part of this distribution. Its [upstream license](https://github.com/ollama/ollama/blob/main/LICENSE) is MIT, Copyright (c) Ollama. Preparation used an existing runtime whose observed version was 0.32.5; no Ollama binary is bundled or installed by the source package's setup script. Model and runtime terms are separate.

## Geometry dependencies installed separately

Exact texts retained from the existing installed distributions:

- **Pyclipper 1.4.0**: `THIRD_PARTY/pyclipper-1.4.0.dist-info/licenses/LICENSE`, MIT; Copyright (c) 2015 Gregor Ratajc, Lukas Treyer, Maxime Chalton.
- **Shapely 2.1.2**: `THIRD_PARTY/shapely-2.1.2.dist-info/licenses/LICENSE.txt`, BSD 3-Clause; its complete copyright, conditions and disclaimer are retained.
- **GEOS notice provided by the installed Shapely distribution**: `THIRD_PARTY/shapely-2.1.2.dist-info/licenses/LICENSE_GEOS`, LGPLv2.1. No GEOS binary is bundled here or relicensed as MIT.
- **NumPy 2.5.3**: `THIRD_PARTY/numpy-2.5.3.dist-info/licenses/`, including the full installed top-level and component notices. NumPy is Shapely's required runtime dependency; preserving its top-level BSD label alone would not replace the component notices.

Python's standard library provides the server and model HTTP client. The source package's dependency installation obtains third-party distributions independently; this prepared copy is not a native binary distribution. Changes to distribution contents require checking the notices applicable to those contents.

## Newly authored code

Application, validator, flow adapter, file checker, interface, setup and launcher code were authored or updated with AI assistance during this work. `LICENSE` contains the MIT license approved by the entrant for newly authored application code, Copyright (c) 2026 Oxygen56. It grants no new terms to third-party samples, models, libraries or runtimes.
