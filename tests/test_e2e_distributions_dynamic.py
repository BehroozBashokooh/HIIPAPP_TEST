import os, time, itertools
from pathlib import Path
import pytest
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

APP_URL = os.environ.get("HIIP_APP_URL", "https://hiipapp.streamlit.app/")
ARTIFACT_DIR = Path("test-artifacts"); ARTIFACT_DIR.mkdir(exist_ok=True)
MAX_CASES = int(os.environ.get("E2E_MAX_CASES", "200"))  # 0 => all
BLOCK_3P = os.environ.get("E2E_BLOCK_3P", "1") != "0"   # block third-party by default

LOCATORS = {
    "grv_dist": "GRV distribution",
    "ntg_dist": "NTG distribution",
    "phi_dist": "Porosity distribution",
    "sw_dist":  "Sw distribution",
    "bo_dist":  "Bo distribution",
    "rf_dist":  "Recovery factor distribution",
    "rs_cgr_dist": "Rs/CGR distribution",
    "fluid_system": "Fluid system",
    "fluid_oil_option": "Oil (Rs)",
    "fluid_cond_option": "Gas/Condensate (CGR)",
    "runs": "Monte Carlo runs",
    "seed": "Random seed",
    "run_button": "Run simulation",
}

STREAMLIT_SELECTORS = [
    '[data-testid="stAppViewContainer"]',
    'section.main',
    'div.block-container',
]
TEXT_HINTS = ["HIIP", "Monte Carlo", "P10", "P50", "P90", "Porosity", "NTG", "GRV"]

RUNS = 400
SEED = 42
PARAM_KEYS = ["grv_dist","ntg_dist","phi_dist","sw_dist","bo_dist","rf_dist","rs_cgr_dist"]

# ---------- Playwright fixtures (scoped + request filtering + container artifacts) ----------

def _same_site_allowlist(app_url: str):
    host = urlparse(app_url).hostname or ""
    # Allow only same-origin + common Streamlit static if needed
    allowed = {
        host,
        "static.streamlit.io",
        "fonts.gstatic.com",
        "fonts.googleapis.com",
    }
    return allowed

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

    # (optional) block third-party assets (avatars, repo images, etc.)
    if BLOCK_3P:
        allow = _same_site_allowlist(APP_URL)
        def route_filter(route):
            try:
                h = urlparse(route.request.url).hostname or ""
                if any(h == a or h.endswith("." + a) for a in allow):
                    return route.continue_()
                # block images / media / styles from third-party
                if route.request.resource_type in ("image","media","font","stylesheet"):
                    return route.abort()
                # still block everything else third-party
                return route.abort()
            except Exception:
                return route.continue_()
        pg.route("**/*", route_filter)

    try:
        resp = pg.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)
        assert resp and resp.ok, f"HTTP not OK: {getattr(resp,'status','?')} {getattr(resp,'status_text','')}"

        # Find app root container
        app_root = None
        for sel in STREAMLIT_SELECTORS:
            try:
                pg.wait_for_selector(sel, state="visible", timeout=30_000)
                app_root = pg.locator(sel)
                if app_root.count() > 0:
                    break
            except PWTimeout:
                continue
        if app_root is None:
            # fallback to text hints within page (then set app_root to body)
            for hint in TEXT_HINTS:
                try:
                    pg.get_by_text(hint, exact=False).wait_for(timeout=10_000)
                    app_root = pg.locator("body")
                    break
                except PWTimeout:
                    continue
        assert app_root is not None, "Could not detect Streamlit UI"

        yield (pg, app_root)

    except Exception:
        ts = int(time.time())
        # Element-only screenshot and HTML (try app root first, else full page)
        try:
            root = pg.locator('[data-testid="stAppViewContainer"]').first
            root.screenshot(path=str(ARTIFACT_DIR / f"{test_name}_{ts}.png"))
            (ARTIFACT_DIR / f"{test_name}_{ts}.html").write_text(root.inner_html(), encoding="utf-8")
        except Exception:
            pg.screenshot(path=str(ARTIFACT_DIR / f"{test_name}_{ts}.png"), full_page=True)
            (ARTIFACT_DIR / f"{test_name}_{ts}.html").write_text(pg.content(), encoding="utf-8")
        (ARTIFACT_DIR / f"{test_name}_{ts}.console.txt").write_text("\n".join(logs), encoding="utf-8")
        raise
    finally:
        ctx.close()

# ---------- Scoped helpers (operate ONLY within app_root) ----------

def _click_select_by_label(scope, label_text):
    # Try label association
    try:
        scope.get_by_label(label_text).click()
        return
    except Exception:
        pass
    # Fallback: nearest combobox within same container
    scope.get_by_text(label_text, exact=False)\
         .locator("xpath=ancestor-or-self::*[1]")\
         .get_by_role("combobox")\
         .click()

def _select_option_in_open_listbox(scope, option_text):
    # Look for the *visible* listbox under the same scope
    lb = scope.get_by_role("listbox").filter(has_text="").first
    # fallback if listbox role not present: use role=option anywhere visible under scope
    try:
        lb.get_by_role("option", name=option_text, exact=False).click()
        return
    except Exception:
        pass
    scope.get_by_role("option", name=option_text, exact=False).first.click()

def _get_options_for(scope, label_text):
    """
    Open the select next to label_text and scrape ONLY from the visible listbox,
    avoiding global page options (e.g., header/profile menus).
    """
    _click_select_by_label(scope, label_text)
    options = set()
    try:
        listbox = scope.get_by_role("listbox").first
        listbox.wait_for(timeout=5_000)
        for opt in listbox.get_by_role("option").all():
            txt = (opt.inner_text() or "").strip()
            if txt:
                options.add(txt)
    except Exception:
        # Try generic visible options within scope
        for opt in scope.get_by_role("option").all():
            try:
                if opt.is_visible():
                    txt = (opt.inner_text() or "").strip()
                    if txt:
                        options.add(txt)
            except Exception:
                continue
    # Close dropdown
    try:
        scope.page.keyboard.press("Escape")
    except Exception:
        pass
    return sorted(options)

def _choose_fluid(scope, fluid: str):
    target = "Oil" if fluid == "oil" else "Gas"
    try:
        _click_select_by_label(scope, LOCATORS["fluid_system"])
        _select_option_in_open_listbox(scope, LOCATORS["fluid_oil_option"] if fluid == "oil" else LOCATORS["fluid_cond_option"])
    except Exception:
        # Fallback: click radio/text inside app_root only
        scope.get_by_text(LOCATORS["fluid_oil_option"] if fluid == "oil" else LOCATORS["fluid_cond_option"], exact=False).click()

def _safe_fill(scope, label_text, value):
    val = str(value)
    try:
        el = scope.get_by_label(label_text)
    except Exception:
        try:
            el = scope.get_by_text(label_text, exact=False).locator("xpath=following::input[1]")
        except Exception:
            return
    try:
        el.fill("")
    except Exception:
        pass
    try:
        el.type(val)
    except Exception:
        pass

def _click_button(scope, button_text):
    scope.get_by_role("button", name=button_text, exact=False).first.click()

def _wait_for_results(scope, timeout_ms=180_000):
    sels = ["canvas", ".stPlotlyChart", ".stAltairChart", ".stDataFrame", '[data-testid="stMetricValue"]']
    for sel in sels:
        try:
            scope.locator(sel).first.wait_for(timeout=timeout_ms, state="visible")
            return True
        except PWTimeout:
            continue
    for t in ["P10", "P50", "P90", "Mean", "Std", "Percentile"]:
        try:
            scope.get_by_text(t, exact=False).first.wait_for(timeout=5_000)
            return True
        except PWTimeout:
            continue
    return False

# ---------- Discovery limited to app_root ----------

def _discover_all_options(scope):
    discovered = {}
    for key in ["grv_dist","ntg_dist","phi_dist","sw_dist","bo_dist","rf_dist"]:
        label = LOCATORS[key]
        try:
            discovered[key] = _get_options_for(scope, label)
        except Exception:
            discovered[key] = []
    union_rs_cgr = set()
    for fluid in ["oil", "cond"]:
        try:
            _choose_fluid(scope, fluid)
            union_rs_cgr.update(_get_options_for(scope, LOCATORS["rs_cgr_dist"]))
        except Exception:
            pass
    discovered["rs_cgr_dist"] = sorted(union_rs_cgr)
    return discovered

def _build_cases_from_discovery(discovered: dict, max_cases: int):
    keys = [k for k in PARAM_KEYS if discovered.get(k)]
    if not keys: return []
    option_lists = [discovered[k] for k in keys]
    all_combos = [dict(zip(keys, combo)) for combo in itertools.product(*option_lists)]
    expanded = []
    for fluid in ["oil", "cond"]:
        for combo in all_combos:
            expanded.append({"fluid": fluid, **combo})
    if max_cases and max_cases > 0 and len(expanded) > max_cases:
        stride = max(1, len(expanded) // max_cases)
        expanded = expanded[::stride][:max_cases]
    return expanded

# ---------- Test body ----------

def _run_once(scope, params):
    _choose_fluid(scope, params.get("fluid", "oil"))
    # Set distribution selects (only the ones present in this case)
    for key, dist_name in params.items():
        if key == "fluid": continue
        label = LOCATORS.get(key)
        if not label: continue
        try:
            _click_select_by_label(scope, label)
            _select_option_in_open_listbox(scope, dist_name)
        except Exception:
            pass

    _safe_fill(scope, LOCATORS["runs"], RUNS)
    _safe_fill(scope, LOCATORS["seed"], SEED)
    _click_button(scope, LOCATORS["run_button"])
    assert _wait_for_results(scope), "No results visualization/metrics detected after run"

def _case_id(i, params):
    parts = [params.get("fluid","?")] + [params[k] for k in PARAM_KEYS if k in params]
    return f"{i:04d}-" + "-".join(parts)

def pytest_generate_tests(metafunc):
    if "params" not in metafunc.fixturenames: return
    # Do a quick discovery in a throwaway context (scoped to app root)
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        ctx = br.new_context()
        pg = ctx.new_page()
        resp = pg.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)
        assert resp and resp.ok
        app_root = None
        for sel in STREAMLIT_SELECTORS:
            try:
                pg.wait_for_selector(sel, state="visible", timeout=30_000)
                app_root = pg.locator(sel)
                if app_root.count() > 0:
                    break
            except PWTimeout:
                continue
        if app_root is None:
            app_root = pg.locator("body")
        discovered = _discover_all_options(app_root)
        (ARTIFACT_DIR / "discovered_distributions.txt").write_text(
            "\n".join(f"{k}: {', '.join(v) if v else '(none)'}" for k,v in discovered.items()),
            encoding="utf-8"
        )
        cases = _build_cases_from_discovery(discovered, MAX_CASES)
        ids = [_case_id(i,c) for i,c in enumerate(cases)]
        ctx.close(); br.close()
    metafunc.parametrize("params", cases, ids=ids)

@pytest.mark.order("last")
def test_all_distributions_dynamic(page, params):
    pg, app_root = page
    _run_once(app_root, params)