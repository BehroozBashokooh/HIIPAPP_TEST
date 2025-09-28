# tests/test_e2e_dists_all_combos.py
import os
import itertools
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ------- Config -------
APP_URL = os.environ.get("HIIP_APP_URL", "https://hiipapp.streamlit.app/")
ARTIFACT_DIR = Path("test-artifacts")
ARTIFACT_DIR.mkdir(exist_ok=True)

# Limit the number of test cases (Cartesian products can explode).
# Set E2E_MAX_CASES=0 to run ALL combinations.
MAX_CASES = int(os.environ.get("E2E_MAX_CASES", "200"))

# IMPORTANT: replace these with your app's exact widget labels / button texts.
LOCATORS = {
    # Distribution selectboxes
    "grv_dist": "GRV distribution",
    "ntg_dist": "NTG distribution",
    "phi_dist": "Porosity distribution",
    "sw_dist":  "Sw distribution",
    "bo_dist":  "Bo distribution",
    "rf_dist":  "Recovery factor distribution",
    "rs_cgr_dist": "Rs/CGR distribution",  # or split into separate labels if your UI does

    # Min/Mode/Max inputs per parameter (adjust to your UI)
    "grv_min": "GRV min", "grv_mode": "GRV mode", "grv_max": "GRV max",
    "ntg_min": "NTG min", "ntg_mode": "NTG mode", "ntg_max": "NTG max",
    "phi_min": "Porosity min", "phi_mode": "Porosity mode", "phi_max": "Porosity max",
    "sw_min":  "Sw min", "sw_mode": "Sw mode", "sw_max": "Sw max",
    "bo_min":  "Bo min", "bo_mode": "Bo mode", "bo_max": "Bo max",
    "rf_min":  "RF min", "rf_mode": "RF mode", "rf_max": "RF max",
    # For Rs or CGR we’ll set depending on fluid system
    "rs_min":  "Rs min", "rs_mode": "Rs mode", "rs_max": "Rs max",
    "cgr_min": "CGR min","cgr_mode":"CGR mode","cgr_max":"CGR max",

    # Fluid system toggle/radio (adjust to your UI)
    "fluid_system": "Fluid system",  # radio/select label
    # Common options: change names to match your UI exactly:
    "fluid_oil_option": "Oil (Rs)",
    "fluid_cond_option": "Gas/Condensate (CGR)",

    # Simulation controls
    "runs": "Monte Carlo runs",
    "seed": "Random seed",
    "run_button": "Run simulation",  # button text
}

# Distribution types to exercise for *each* parameter
# Make sure these strings exactly match your selectbox options.
DIST_TYPES = ["PERT", "Triangular", "Normal", "Lognormal"]

# Numeric cases (kept constant across dist combos; tweak as needed)
NUMERIC_CASES = {
    "GRV": {"min": 1e6, "mode": 2e6, "max": 4e6},
    "NTG": {"min": 0.20, "mode": 0.35, "max": 0.60},
    "PHI": {"min": 0.10, "mode": 0.18, "max": 0.28},
    "SW":  {"min": 0.15, "mode": 0.25, "max": 0.40},
    "BO":  {"min": 1.05, "mode": 1.20, "max": 1.35},  # rb/stb or m3/m3 as per units
    "RF":  {"min": 0.10, "mode": 0.25, "max": 0.45},
    "RS":  {"min": 50, "mode": 120, "max": 250},      # scf/stb (example)
    "CGR": {"min": 5, "mode": 25, "max": 60},         # stb/MMscf (example)
}

RUNS = 500
SEED = 42

# Streamlit selectors (broad & robust)
STREAMLIT_SELECTORS = [
    '[data-testid="stAppViewContainer"]',
    '[data-testid="stSidebar"]',
    'section.main',
    'div.block-container',
    'canvas',
]
TEXT_HINTS = ["HIIP", "Monte Carlo", "P10", "P50", "P90", "Porosity", "NTG", "GRV"]

# ------- Playwright fixtures -------

@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()

@pytest.fixture
def page(browser, request):
    test_name = request.node.name.replace("/", "_")
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    logs = []
    pg.on("console", lambda msg: logs.append(f"[{msg.type()}] {msg.text()}"))

    try:
        resp = pg.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)
        assert resp is not None and resp.ok, f"HTTP not OK: {getattr(resp,'status','?')} {getattr(resp,'status_text','')}"
        ok = False
        for sel in STREAMLIT_SELECTORS:
            try:
                pg.wait_for_selector(sel, state="visible", timeout=30_000)
                ok = True
                break
            except PWTimeout:
                continue
        if not ok:
            for hint in TEXT_HINTS:
                try:
                    pg.get_by_text(hint, exact=False).wait_for(timeout=10_000)
                    ok = True
                    break
                except PWTimeout:
                    continue
        # Try dismiss common consent buttons if present
        for btn in ["Accept", "I agree", "Allow all", "Ok", "Got it"]:
            try:
                pg.get_by_role("button", name=btn, exact=False).click(timeout=1500)
                ok = True
                break
            except Exception:
                pass

        assert ok, "Could not detect Streamlit UI"
        yield pg

    except Exception:
        ts = int(time.time())
        png = ARTIFACT_DIR / f"{test_name}_{ts}.png"
        html = ARTIFACT_DIR / f"{test_name}_{ts}.html"
        pg.screenshot(path=str(png), full_page=True)
        html.write_text(pg.content(), encoding="utf-8")
        (ARTIFACT_DIR / f"{test_name}_{ts}.console.txt").write_text("\n".join(logs), encoding="utf-8")
        raise
    finally:
        ctx.close()

# ------- Robust UI helpers -------

def _select_by_label(page, label_text, option_text):
    """Click selectbox with a label; fall back to nearest combobox."""
    try:
        page.get_by_label(label_text).click()
    except Exception:
        container = page.get_by_text(label_text, exact=False).locator("xpath=ancestor-or-self::*[1]")
        container.get_by_role("combobox").click()
    page.get_by_role("option", name=option_text, exact=True).click()

def _fill_number(page, label_text, value):
    """Fill numeric input by label; fall back to first input after label."""
    val = str(value)
    try:
        el = page.get_by_label(label_text)
    except Exception:
        el = page.get_by_text(label_text, exact=False).locator("xpath=following::input[1]")
    try:
        el.fill("")
    except Exception:
        pass
    el.type(val)

def _click_button(page, button_text):
    page.get_by_role("button", name=button_text, exact=False).click()

def _wait_for_results(page, timeout_ms=180_000):
    sels = ["canvas", ".stPlotlyChart", ".stAltairChart", ".stDataFrame", '[data-testid="stMetricValue"]']
    for sel in sels:
        try:
            page.wait_for_selector(sel, timeout=timeout_ms, state="visible")
            return True
        except PWTimeout:
            continue
    for t in ["P10", "P50", "P90", "Mean", "Std", "Percentile"]:
        try:
            page.get_by_text(t, exact=False).wait_for(timeout=5_000)
            return True
        except PWTimeout:
            continue
    return False

# ------- Test case generator -------

def dist_combos():
    """
    Generate the full Cartesian product of distribution choices across:
    GRV, NTG, PHI, SW, BO, RF, RS/CGR.
    """
    keys = ["grv_dist","ntg_dist","phi_dist","sw_dist","bo_dist","rf_dist","rs_cgr_dist"]
    for combo in itertools.product(DIST_TYPES, repeat=len(keys)):
        yield dict(zip(keys, combo))

def fluid_modes():
    # Exercise both modes so we cover Rs-only and CGR-only branches
    yield "oil"
    yield "cond"

def build_cases(max_cases: int):
    """
    Build up to max_cases.
    If max_cases == 0, return ALL combinations (may be very large).
    """
    all_items = []
    for fluid in fluid_modes():
        for dists in dist_combos():
            params = {
                # distributions
                **dists,
                # fluid
                "fluid": fluid,
                # numerics
                "grv_min": NUMERIC_CASES["GRV"]["min"], "grv_mode": NUMERIC_CASES["GRV"]["mode"], "grv_max": NUMERIC_CASES["GRV"]["max"],
                "ntg_min": NUMERIC_CASES["NTG"]["min"], "ntg_mode": NUMERIC_CASES["NTG"]["mode"], "ntg_max": NUMERIC_CASES["NTG"]["max"],
                "phi_min": NUMERIC_CASES["PHI"]["min"], "phi_mode": NUMERIC_CASES["PHI"]["mode"], "phi_max": NUMERIC_CASES["PHI"]["max"],
                "sw_min":  NUMERIC_CASES["SW"]["min"],  "sw_mode":  NUMERIC_CASES["SW"]["mode"],  "sw_max":  NUMERIC_CASES["SW"]["max"],
                "bo_min":  NUMERIC_CASES["BO"]["min"],  "bo_mode":  NUMERIC_CASES["BO"]["mode"],  "bo_max":  NUMERIC_CASES["BO"]["max"],
                "rf_min":  NUMERIC_CASES["RF"]["min"],  "rf_mode":  NUMERIC_CASES["RF"]["mode"],  "rf_max":  NUMERIC_CASES["RF"]["max"],
                "runs": RUNS, "seed": SEED,
            }
            if fluid == "oil":
                params.update({
                    "rs_min": NUMERIC_CASES["RS"]["min"], "rs_mode": NUMERIC_CASES["RS"]["mode"], "rs_max": NUMERIC_CASES["RS"]["max"],
                })
            else:
                params.update({
                    "cgr_min": NUMERIC_CASES["CGR"]["min"], "cgr_mode": NUMERIC_CASES["CGR"]["mode"], "cgr_max": NUMERIC_CASES["CGR"]["max"],
                })
            all_items.append(params)

    if max_cases and max_cases > 0 and len(all_items) > max_cases:
        # Deterministic down-sample: stride through the list
        stride = max(1, len(all_items) // max_cases)
        return all_items[::stride][:max_cases]
    return all_items

CASES = build_cases(MAX_CASES)

# Human-readable IDs for pytest
def _case_id(i, p):
    parts = [
        p["fluid"],
        p["grv_dist"], p["ntg_dist"], p["phi_dist"], p["sw_dist"], p["bo_dist"], p["rf_dist"], p["rs_cgr_dist"]
    ]
    return f"{i:04d}-" + "-".join(parts)

# ------- Core test -------

def _set_distributions(page, params):
    _select_by_label(page, LOCATORS["grv_dist"], params["grv_dist"])
    _select_by_label(page, LOCATORS["ntg_dist"], params["ntg_dist"])
    _select_by_label(page, LOCATORS["phi_dist"], params["phi_dist"])
    _select_by_label(page, LOCATORS["sw_dist"],  params["sw_dist"])
    _select_by_label(page, LOCATORS["bo_dist"],  params["bo_dist"])
    _select_by_label(page, LOCATORS["rf_dist"],  params["rf_dist"])
    _select_by_label(page, LOCATORS["rs_cgr_dist"], params["rs_cgr_dist"])

def _set_fluid_mode(page, params):
    # Radio/select for fluid system; choose Oil or Gas/Condensate
    try:
        _select_by_label(
            page,
            LOCATORS["fluid_system"],
            LOCATORS["fluid_oil_option"] if params["fluid"] == "oil" else LOCATORS["fluid_cond_option"]
        )
    except Exception:
        # Some apps use separate radios; try clicking text directly
        option = LOCATORS["fluid_oil_option"] if params["fluid"] == "oil" else LOCATORS["fluid_cond_option"]
        page.get_by_text(option, exact=False).click()

def _set_numeric_ranges(page, params):
    # Always set common parameters
    for k in ("grv_min","grv_mode","grv_max",
              "ntg_min","ntg_mode","ntg_max",
              "phi_min","phi_mode","phi_max",
              "sw_min","sw_mode","sw_max",
              "bo_min","bo_mode","bo_max",
              "rf_min","rf_mode","rf_max"):
        _fill_number(page, LOCATORS[k], params[k])

    # Conditionally set Rs or CGR triples
    if params["fluid"] == "oil":
        for k in ("rs_min","rs_mode","rs_max"):
            _fill_number(page, LOCATORS[k], params[k])
    else:
        for k in ("cgr_min","cgr_mode","cgr_max"):
            _fill_number(page, LOCATORS[k], params[k])

    # Guard monotonic triples
    def _assert_triple(a,b,c):
        assert params[a] <= params[b] <= params[c], f"{a},{b},{c} must be nondecreasing"
    for a,b,c in [
        ("grv_min","grv_mode","grv_max"),
        ("ntg_min","ntg_mode","ntg_max"),
        ("phi_min","phi_mode","phi_max"),
        ("sw_min","sw_mode","sw_max"),
        ("bo_min","bo_mode","bo_max"),
        ("rf_min","rf_mode","rf_max"),
    ]:
        _assert_triple(a,b,c)
    if params["fluid"] == "oil":
        _assert_triple("rs_min","rs_mode","rs_max")
    else:
        _assert_triple("cgr_min","cgr_mode","cgr_max")

def _run_once(page, params):
    _set_fluid_mode(page, params)
    _set_distributions(page, params)
    _set_numeric_ranges(page, params)

    _fill_number(page, LOCATORS["runs"], params["runs"])
    _fill_number(page, LOCATORS["seed"], params["seed"])

    _click_button(page, LOCATORS["run_button"])

    ok = _wait_for_results(page, timeout_ms=180_000)
    if not ok:
        raise AssertionError("No results visualization/metrics detected after run")

@pytest.mark.parametrize(
    "params",
    CASES,
    ids=[_case_id(i,p) for i,p in enumerate(CASES)]
)
def test_all_dist_combinations(page, params):
    _run_once(page, params)