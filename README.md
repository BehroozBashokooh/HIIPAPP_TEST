# HIIPApp E2E Tests

This repository contains an automated **end-to-end (E2E) test suite** for the [HIIPApp](https://hiipapp.streamlit.app/) Streamlit application.  
The tests are written with [pytest](https://docs.pytest.org/), [pytest-xdist](https://pypi.org/project/pytest-xdist/), and [Playwright](https://playwright.dev/python/).

The main test (`tests/test_e2e_distributions_dynamic.py`) dynamically discovers all available distribution types in the app’s dropdown menus (including discrete and fixed types) and exercises different combinations to ensure the app runs without errors.

---

## Features

- 🔎 **Dynamic discovery** of distribution types (no hard-coding).
- 🧪 **Automated test cases** for GRV, NTG, porosity, Sw, Bo, RF, and Rs/CGR under both fluid systems (Oil and Gas/Condensate).
- 📸 **Artifacts on failure** (screenshots, HTML, console logs) saved under `test-artifacts/`.
- ⚡ **Parallel execution** with pytest-xdist.
- 🛑 **Third-party blocking** (optional) so only app content is tested (skips profile avatars, repo links, etc.).

---

## Requirements

- Python 3.10+  
- [uv](https://github.com/astral-sh/uv) for environment management (or you can use `pip`/`venv` if preferred)  
- Chromium browser (installed automatically by Playwright)

