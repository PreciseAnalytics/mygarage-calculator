"""
MyGarage by CarMax - Value & Cost-Savings Calculator
Team 5, UVA McIntire MSIT Module 1

Interactive what-if tool that shows how MyGarage affects:
  1. Revenue and program profit (repeat sales, protection plans, service)
  2. Cost savings CarMax gets from the design (marketing, reconditioning,
     appraisal risk, customer care, early issue detection)
  3. Profitability (margin, ROI, payback, NPV, net earnings, EPS)
  4. Customer experience (retention, lifetime value, verified care records)

Run:
    pip install -r requirements.txt
    streamlit run mygarage_calculator.py

CarMax facts default to FY2026 results / Form 10-K (fiscal year ended
Feb 28, 2026). Everything else is a team assumption you can change in the
sidebar. The core program math mirrors the MyGarage financial model used in
the pitch deck (slides 12, 15, 24, 25) so the "Team deck" preset lands close
to the deck's numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, fields

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Sourced CarMax facts (FY2026)
# ---------------------------------------------------------------------------
CARMAX_FACTS = {
    "Retail used units sold": ("780,684", "FY2026 results (Apr 14, 2026)"),
    "Average retail selling price": ("$26,121", "FY2026 results"),
    "Used vehicle gross profit per unit": ("$2,253", "FY2026 results"),
    "EPP revenue": ("$448.7M (~$575 per car)", "FY2026 results / 10-K"),
    "Advertising expense": ("$283.0M (~$362 per retail unit)", "FY2026 results"),
    "SG&A": ("$2,453.4M; 87.4% of gross profit", "FY2026 results"),
    "SG&A savings target": ("$200M exit-rate savings by end of FY2027", "FY2026 results"),
    "Net earnings / diluted EPS": ("$247.3M / $1.68", "FY2026 results"),
    "Service department margin": ("Roughly break-even; negative in Q3 FY2026", "Q3 FY2026 earnings call"),
    "Reconditioning cost reduction": ("$125 per unit goal met in FY2025", "Q3 FY2026 earnings call"),
    "Stores with service": ("256", "Form 10-K FY2026"),
}

SHARES_OUTSTANDING_M = 247.3 / 1.68  # implied diluted shares, millions
SGA_TARGET = 200_000_000


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
@dataclass
class Inputs:
    # CarMax base (sourced)
    retail_units: float = 780_684
    asp: float = 26_121
    gpu: float = 2_253
    epp_per_car: float = 575
    advertising: float = 283_000_000
    # Adoption
    recent_owners: float = 2_340_000
    existing_enroll: float = 0.10
    new_enroll: float = 0.40
    year1_ramp: float = 0.90
    attrition: float = 0.20         # enrolled owners lost per year (sold car elsewhere, disengaged)
    # Repeat purchase
    cycle_years: float = 5
    base_repeat: float = 0.20
    lift: float = 0.05
    avg_reward: float = 500
    reward_take: float = 1.00
    # Service & scans
    svc_share: float = 0.25
    svc_share_baseline: float = 0.05
    visits: float = 1.5
    ticket: float = 120
    svc_margin: float = 0.33
    scan_share: float = 0.15
    scan_cost: float = 6
    # Program costs
    build_cost: float = 8_000_000
    fixed_cost: float = 3_100_000
    # Cost-savings levers
    acq_mult: float = 1.0           # x avg ad $/unit avoided per incremental repeat buyer
    owned_shift: float = 0.30       # share of ad $/unit saved on baseline repeat buyers reached via app
    trade_rate: float = 0.70        # repeat buyers who trade in
    badge_share: float = 0.50       # trade-ins with a verified CarMax care record
    recon_cost: float = 1_800       # avg reconditioning cost per car (team estimate)
    recon_reduction: float = 0.10   # cut for verified, well-maintained trade-ins
    appraisal_saving: float = 75    # appraisal / wholesale loss avoided per verified trade-in
    contacts: float = 0.5           # customer-care contacts per owner per year
    contact_cost: float = 8
    contact_reduction: float = 0.15
    goodwill_per_scan: float = 15   # early-detection goodwill/warranty cost avoided per scan
    issue_detect: float = 0.08      # scans that catch an issue early
    # Finance
    tax_rate: float = 0.25
    discount_rate: float = 0.10
    start_year: int = 2026


def _preset(**overrides) -> dict:
    d = asdict(Inputs())
    d.update(overrides)
    return d


PRESETS = {
    "Team deck base case": _preset(),
    "Realistic (recommended)": _preset(
        existing_enroll=0.08, new_enroll=0.35, year1_ramp=0.75, attrition=0.20, lift=0.04,
        svc_share=0.22, visits=1.3, acq_mult=0.9, owned_shift=0.20,
        badge_share=0.40, recon_reduction=0.08, appraisal_saving=50,
        contact_reduction=0.12, goodwill_per_scan=10,
    ),
    "Conservative (stress test)": _preset(
        existing_enroll=0.08, new_enroll=0.30, year1_ramp=0.60, attrition=0.25, lift=0.03,
        svc_share=0.20, visits=1.2, acq_mult=0.75, owned_shift=0.15,
        badge_share=0.35, recon_reduction=0.05, appraisal_saving=40,
        contact_reduction=0.10, goodwill_per_scan=8,
    ),
    "Optimistic": _preset(
        existing_enroll=0.15, new_enroll=0.50, year1_ramp=1.0, attrition=0.15, lift=0.07,
        svc_share=0.30, visits=1.8, acq_mult=1.25, owned_shift=0.40,
        badge_share=0.60, recon_reduction=0.15, appraisal_saving=100,
        contact_reduction=0.20, goodwill_per_scan=20,
    ),
}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def run_model(p: Inputs, horizon: int = 5) -> pd.DataFrame:
    """Return a year-by-year table (Year 0 = build)."""
    ad_per_unit = p.advertising / p.retail_units
    rows = [{
        "Year": f"{p.start_year} (Yr 0)", "t": 0, "Enrolled owners": 0,
        "Incremental repeat cars": 0, "Revenue": 0, "Variable costs": 0,
        "Rewards paid": 0, "Contribution": 0, "Fixed costs": 0,
        "Program profit": -p.build_cost,
        "Savings: marketing (new)": 0, "Savings: marketing (owned channel)": 0,
        "Savings: reconditioning": 0, "Savings: appraisal risk": 0,
        "Savings: customer care": 0, "Savings: early detection": 0,
        "Total cost savings": 0, "Total value": -p.build_cost,
        "Scans": 0, "Verified trade-ins": 0, "Service visits": 0,
    }]
    for t in range(1, horizon + 1):
        ramp = p.year1_ramp if t == 1 else 1.0
        keep = 1 - p.attrition
        existing = (p.recent_owners * p.existing_enroll
                    * max(0.0, 1 - (t - 1) / p.cycle_years) * keep ** (t - 1))
        cohorts = int(min(t, p.cycle_years))
        new = p.retail_units * p.new_enroll * sum(keep ** k for k in range(cohorts))
        pool = (existing + new) * ramp

        base_rep = pool * p.base_repeat / p.cycle_years
        incr = pool * p.lift / p.cycle_years
        repeats = base_rep + incr

        car_rev = incr * (p.asp + p.epp_per_car)
        visits = pool * p.svc_share * p.visits
        svc_rev = visits * p.ticket
        revenue = car_rev + svc_rev

        car_cogs = incr * (p.asp - p.gpu)
        rewards = repeats * p.reward_take * p.avg_reward
        svc_cost = svc_rev * (1 - p.svc_margin)
        scans = pool * p.scan_share
        scan_cost = scans * p.scan_cost
        var = car_cogs + rewards + svc_cost + scan_cost
        contrib = revenue - var
        program = contrib - p.fixed_cost

        trades = repeats * p.trade_rate
        verified = trades * p.badge_share
        s = {
            "Savings: marketing (new)": incr * ad_per_unit * p.acq_mult,
            "Savings: marketing (owned channel)": base_rep * ad_per_unit * p.owned_shift,
            "Savings: reconditioning": verified * p.recon_cost * p.recon_reduction,
            "Savings: appraisal risk": verified * p.appraisal_saving,
            "Savings: customer care": pool * p.contacts * p.contact_cost * p.contact_reduction,
            "Savings: early detection": scans * p.goodwill_per_scan,
        }
        total_s = sum(s.values())
        rows.append({
            "Year": f"{p.start_year + t} (Yr {t})", "t": t, "Enrolled owners": pool,
            "Incremental repeat cars": incr, "Revenue": revenue, "Variable costs": var,
            "Rewards paid": rewards, "Contribution": contrib, "Fixed costs": p.fixed_cost,
            "Program profit": program, **s, "Total cost savings": total_s,
            "Total value": program + total_s, "Scans": scans,
            "Verified trade-ins": verified, "Service visits": visits,
        })
    df = pd.DataFrame(rows)
    df["Cumulative program profit"] = df["Program profit"].cumsum()
    df["Cumulative total value"] = df["Total value"].cumsum()
    return df


def payback_year(cum: pd.Series, df: pd.DataFrame) -> str:
    for c, label in zip(cum, df["Year"]):
        if c >= 0 and label.endswith("(Yr 0)") is False:
            return label
    return "Beyond Year 5"


def npv(values, rate) -> float:
    return sum(v / (1 + rate) ** i for i, v in enumerate(values))


def breakeven_lift(p: Inputs, include_savings: bool) -> float | None:
    col = "Total value" if include_savings else "Program profit"
    lo, hi = -0.05, 0.20
    f = lambda x: run_model(Inputs(**{**asdict(p), "lift": x}))[col].sum()
    if f(hi) < 0:
        return None
    if f(lo) > 0:
        return lo
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return hi


def clv(p: Inputs, with_mygarage: bool) -> float:
    """Lifetime gross profit of one buyer, over repeat cycles, discounted per cycle."""
    d = (1 + p.discount_rate) ** p.cycle_years
    share = p.svc_share if with_mygarage else p.svc_share_baseline
    svc = share * p.visits * p.ticket * p.svc_margin * p.cycle_years
    per_cycle = p.gpu + p.epp_per_car + svc
    r = p.base_repeat + (p.lift if with_mygarage else 0)
    reward = p.avg_reward * p.reward_take if with_mygarage else 0
    q = r / d
    return per_cycle + q * (per_cycle - reward) / (1 - q)


# field: (label, unit, type, source)
ASSUMPTION_LABELS = {
    "retail_units": ("Retail used cars sold / year", "n", "CarMax fact", "FY2026 results"),
    "asp": ("Average selling price", "$", "CarMax fact", "FY2026 results"),
    "gpu": ("Gross profit per used car", "$", "CarMax fact", "FY2026 results"),
    "epp_per_car": ("Protection-plan (EPP) revenue per car", "$", "CarMax fact", "10-K: $448.7M / units"),
    "advertising": ("Advertising spend / year", "$", "CarMax fact", "FY2026 results"),
    "recent_owners": ("Recent owners eligible at launch", "n", "CarMax fact", "10-K units FY2024-26"),
    "existing_enroll": ("Recent owners who enroll", "%", "Team assumption", ""),
    "new_enroll": ("New buyers who enroll at delivery", "%", "Team assumption", "Pilot go/no-go target"),
    "year1_ramp": ("Year-1 rollout ramp", "%", "Team assumption", "Pilot to national"),
    "attrition": ("Enrolled owners lost per year", "%", "Team assumption", ""),
    "cycle_years": ("Ownership cycle", "yrs", "Team assumption", ""),
    "base_repeat": ("Baseline repeat-purchase rate", "%", "Team assumption", ""),
    "lift": ("Repeat-rate lift from MyGarage", "pts", "Team assumption", "Key driver"),
    "avg_reward": ("Average reward redeemed", "$", "Team proposal", "Paid only at trade-in"),
    "reward_take": ("Repeat buyers who redeem", "%", "Team assumption", ""),
    "svc_share": ("Enrolled owners who service at CarMax", "%", "Team assumption", ""),
    "svc_share_baseline": ("Owners who service at CarMax today", "%", "Team assumption", ""),
    "visits": ("Service visits / year", "n", "Team assumption", ""),
    "ticket": ("Revenue per service visit", "$", "Team assumption", ""),
    "svc_margin": ("Service margin", "%", "Team assumption", "CarMax service ~break-even today"),
    "scan_share": ("Owners doing the yearly scan", "%", "Team assumption", ""),
    "scan_cost": ("Labor cost per scan", "$", "Team assumption", ""),
    "build_cost": ("One-time build", "$", "Team estimate", "Budget tab"),
    "fixed_cost": ("Fixed run cost / year", "$", "Team estimate", "Budget tab"),
    "acq_mult": ("Acquisition cost avoided per extra repeat buyer (x ad $/car)", "x", "Team assumption", "Ad $/car = $283M / 780,684"),
    "owned_shift": ("Ad cost saved on loyal buyers reached in-app", "%", "Team assumption", ""),
    "trade_rate": ("Repeat buyers who trade in", "%", "Team assumption", ""),
    "badge_share": ("Trade-ins with verified care record", "%", "Team assumption", ""),
    "recon_cost": ("Avg reconditioning cost per car", "$", "Team estimate", "Not disclosed by CarMax"),
    "recon_reduction": ("Recon cost cut on verified trade-ins", "%", "Team assumption", ""),
    "appraisal_saving": ("Appraisal loss avoided per verified trade-in", "$", "Team estimate", ""),
    "contacts": ("Care contacts per owner / year", "n", "Team estimate", ""),
    "contact_cost": ("Cost per care contact", "$", "Team estimate", ""),
    "contact_reduction": ("Contacts avoided via the app", "%", "Team assumption", ""),
    "goodwill_per_scan": ("Warranty/goodwill cost avoided per scan", "$", "Team estimate", ""),
    "issue_detect": ("Scans that catch an issue early", "%", "Team assumption", ""),
    "tax_rate": ("Tax rate", "%", "Team assumption", ""),
    "discount_rate": ("Discount rate (NPV)", "%", "Team assumption", ""),
}

GROUPS = [
    ("CarMax baseline", ["retail_units", "asp", "gpu", "epp_per_car", "advertising", "recent_owners"]),
    ("Adoption & repeat purchase", ["existing_enroll", "new_enroll", "year1_ramp", "attrition",
                                    "cycle_years", "base_repeat", "lift", "avg_reward", "reward_take"]),
    ("Service, scans & program cost", ["svc_share", "svc_share_baseline", "visits", "ticket",
                                       "svc_margin", "scan_share", "scan_cost", "build_cost",
                                       "fixed_cost"]),
    ("Cost-savings levers & finance", ["acq_mult", "owned_shift", "trade_rate", "badge_share",
                                       "recon_cost", "recon_reduction", "appraisal_saving",
                                       "contacts", "contact_cost", "contact_reduction",
                                       "goodwill_per_scan", "issue_detect", "tax_rate",
                                       "discount_rate"]),
]


def fmt_val(v, unit):
    if unit == "%":
        return f"{v:.0%}" if abs(v * 100 - round(v * 100)) < 1e-9 else f"{v:.1%}"
    if unit == "pts":
        return f"+{v * 100:.1f} pts"
    if unit == "$":
        return f"${v / 1e6:,.2f}M" if abs(v) >= 1e6 else f"${v:,.0f}"
    if unit == "x":
        return f"{v:.2f}x"
    return f"{v:,.1f}" if v != int(v) else f"{int(v):,}"


def assumptions_table(p, preset_name, keys):
    base = PRESETS[preset_name]
    rows = []
    for k in keys:
        label, unit, kind, src = ASSUMPTION_LABELS[k]
        v = getattr(p, k)
        changed = abs(float(v) - float(base[k])) > 1e-9
        rows.append({"Variable": label, "Value": fmt_val(v, unit) + (" ✎" if changed else ""),
                     "Type": kind, "Note / source": src})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def m(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x) / 1e6:,.1f}M"


_M_KEYS = {"advertising", "build_cost", "fixed_cost"}  # keys displayed in $M

def apply_preset():
    """Apply the current preset values to session state.
    Must be called before any widgets are instantiated (top of main()).
    Button handlers must NOT call this directly — set _pending_preset instead
    and let the top-of-run guard apply it on the next rerun.
    """
    for k, v in PRESETS[st.session_state["preset"]].items():
        v = int(v) if k == "start_year" else float(v)
        st.session_state[k] = v
        st.session_state[f"_{k}"] = v * 100       # slider mirror for % inputs
        if k in _M_KEYS:
            st.session_state[f"_m_{k}"] = v / 1e6  # $M mirror for numM inputs


def num(label, key, step, fmt="%.0f", help=None, minv=0.0):
    return st.number_input(label, key=key, step=step, format=fmt, help=help, min_value=minv)


def numM(label, key, step_m=1.0, help=None, minv=0.0):
    """Number input displayed and entered in $M — stores full dollar value in session state."""
    mirror = f"_m_{key}"
    # Initialise mirror from the real key on first render
    if mirror not in st.session_state and key in st.session_state:
        st.session_state[mirror] = st.session_state[key] / 1e6
    v_m = st.number_input(
        f"{label} ($M)",
        key=mirror,
        step=step_m,
        format="%.2f",
        help=(help or "") + " — enter value in millions (e.g. 8 = $8M)",
        min_value=minv,
    )
    st.session_state[key] = v_m * 1e6
    return v_m * 1e6


def pct(label, key, maxv=100.0, step=1.0, help=None):
    v = st.slider(label, 0.0, maxv, step=step, help=help, key=f"_{key}", format="%.1f%%")
    st.session_state[key] = v / 100
    return v / 100


BRAND = "#1565C0"   # CarMax blue (chart)
ACCENT = "#FFD520"  # CarMax yellow
GREEN = "#00E676"
GREY = "#8A94A6"
RED = "#FF5252"

SHORT = {"Team deck base case": "Deck base", "Realistic (recommended)": "Realistic",
         "Conservative (stress test)": "Conservative", "Optimistic": "Optimistic"}
LIFT_OPTS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
REWARD_OPTS = [250, 350, 500, 750]
ENROLL_OPTS = [0.20, 0.30, 0.40, 0.50]


def _set(key, value):
    """Queue a single-key override to be applied before widgets render."""
    if "_pending_overrides" not in st.session_state:
        st.session_state["_pending_overrides"] = {}
    st.session_state["_pending_overrides"][key] = float(value)


def on_reset(mode="all"):
    """mode='all' resets everything; mode='inputs' resets sidebar inputs only."""
    if mode in ("all", "scenarios"):
        st.session_state["_scenario_sel"] = "Realistic"
        st.session_state["preset"] = "Realistic (recommended)"
        st.session_state["_pending_preset"] = "Realistic (recommended)"
        st.session_state["_lift_sel"] = None
        st.session_state["_reward_sel"] = None
        st.session_state["_enroll_sel"] = None
    if mode in ("all", "inputs"):
        # Re-apply the current preset to reset sidebar inputs to their defaults
        st.session_state["_pending_preset"] = st.session_state.get("preset", "Realistic (recommended)")


def _btn_row(label, options, state_key, fmt_func, on_select):
    """Render a labeled row of solid toggle-buttons using st.button."""
    st.markdown(f"<div class='ctrl-label'>{label}</div>", unsafe_allow_html=True)
    cols = st.columns(len(options))
    sel = st.session_state.get(state_key)
    for col, opt in zip(cols, options):
        display = fmt_func(opt)
        is_sel = (sel == opt)
        with col:
            if st.button(display, key=f"_btw_{state_key}_{opt}", width="stretch"):
                st.session_state[state_key] = opt
                on_select(opt)
                st.rerun()
            key_cls = f"_btw_{state_key}_{opt}".replace(".", "_")
            color = "#FFD520" if is_sel else "#1e3f7a"
            text_color = "#0a1f44" if is_sel else "#ffffff"
            border = "#FFD520" if is_sel else "#4a6aaa"
            st.markdown(f"""
            <style>
            div[data-testid="stButton"][class*="{key_cls}"] button,
            .st-key-_btw_{state_key.replace('.','_')}_{str(opt).replace('.','_')} button {{
                background: {color} !important;
                color: {text_color} !important;
                border: 2px solid {border} !important;
            }}
            </style>""", unsafe_allow_html=True)


_CTRL_THEMES = {
    "scenario": {"bg": "#004D40", "border": "#00BFA5", "label": "Scenario"},
    "lift":     {"bg": "#311B92", "border": "#7C4DFF", "label": "Repeat-rate lift"},
    "reward":   {"bg": "#BF360C", "border": "#FF6E40", "label": "Avg reward"},
    "enroll":   {"bg": "#1B5E20", "border": "#69F0AE", "label": "New-buyer enrollment"},
}


def _ctrl_section_css(section_key: str, btn_keys: list[str], sel_key: str, sel_val) -> str:
    """Emit CSS for one control section: colored bg wrapper + per-button selected state."""
    t = _CTRL_THEMES[section_key]
    lines = [
        f".ctrl-wrap-{section_key} {{ background:{t['bg']}; border-radius:0; "
        f"border:none; padding:14px 16px; margin:0; }}",
        f".ctrl-wrap-{section_key} .ctrl-label {{ color:#ffffff !important; text-align:center !important; }}",
    ]
    for bkey, opt in btn_keys:
        is_sel = sel_val == opt
        bg = "#FFD520" if is_sel else t["bg"]
        tc = "#0a1f44" if is_sel else "#ffffff"
        bd = "#FFD520" if is_sel else t["border"]
        fw = "900" if is_sel else "700"
        border_css = f"border:2px solid {bd}!important;" if is_sel else "border:none!important;box-shadow:none!important;"
        lines.append(
            f".st-key-{bkey} button {{background:{bg}!important;color:{tc}!important;"
            f"{border_css}font-size:1.05rem!important;"
            f"font-weight:{'700' if is_sel else '600'}!important;padding:8px 4px!important;"
            f"border-radius:6px!important;min-height:38px!important;"
            f"font-family:'Inter','Poppins',sans-serif!important;"
            f"letter-spacing:0!important;}}"
            f" .st-key-{bkey} button p, .st-key-{bkey} button div"
            f" {{font-size:1.05rem!important;font-weight:{'700' if is_sel else '600'}!important;"
            f"color:{tc}!important;font-family:'Inter','Poppins',sans-serif!important;"
            f"letter-spacing:0!important;}}"
        )
    return "\n".join(lines)


def demo_controls():
    """Four themed control sections — each with its own background color."""
    for k, default in [("_scenario_sel", "Realistic"), ("_lift_sel", None),
                       ("_reward_sel", None), ("_enroll_sel", None)]:
        if k not in st.session_state:
            st.session_state[k] = default

    scen_labels = list(SHORT.values())
    sel_sc = st.session_state.get("_scenario_sel", "Realistic")
    sel_lift = st.session_state.get("_lift_sel")
    sel_rew = st.session_state.get("_reward_sel")
    sel_enr = st.session_state.get("_enroll_sel")
    sc_keys = [(f"sc_btn_{label.replace(' ', '_')}", label) for label in scen_labels]
    lift_keys = [(f"lift_btn_{int(opt*1000)}", opt) for opt in LIFT_OPTS]
    rew_keys = [(f"rew_btn_{opt}", opt) for opt in REWARD_OPTS]
    enr_keys = [(f"enr_btn_{int(opt*100)}", opt) for opt in ENROLL_OPTS]
    css = "\n".join([
        _ctrl_section_css("scenario", sc_keys, "_scenario_sel", sel_sc),
        _ctrl_section_css("lift", lift_keys, "_lift_sel", sel_lift),
        _ctrl_section_css("reward", rew_keys, "_reward_sel", sel_rew),
        _ctrl_section_css("enroll", enr_keys, "_enroll_sel", sel_enr),
    ])
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    container_css = """
    .st-key-wrap_scenario { background:#004D40; border-radius:0; border:none; padding:8px 10px; margin:0; }
    .st-key-wrap_lift     { background:#311B92; border-radius:0; border:none; padding:8px 10px; margin:0; }
    .st-key-wrap_reward   { background:#BF360C; border-radius:0; border:none; padding:8px 10px; margin:0; }
    .st-key-wrap_enroll   { background:#1B5E20; border-radius:0; border:none; padding:8px 10px; margin:0; }
    """
    st.markdown(f"<style>{container_css}</style>", unsafe_allow_html=True)
    st.markdown("""
    <div style='background:#04152D;padding:6px 0 2px 0;margin:0 -1.5rem;
                text-align:center;font-size:0.78rem;font-weight:700;
                text-transform:uppercase;letter-spacing:2px;color:#90b4e0;'>
        Quick scenario controls — Scenario &nbsp;·&nbsp; Repeat-rate lift &nbsp;·&nbsp;
        Avg reward &nbsp;·&nbsp; New-buyer enrollment
    </div>
    """, unsafe_allow_html=True)
    c_sc, c_lift, c_rew, c_enr = st.columns(4)
    with c_sc:
        with st.container(key="wrap_scenario"):
            st.markdown("<div class='ctrl-label'>Scenario</div>", unsafe_allow_html=True)
            # 2×2 grid so height matches the other sections
            row1 = st.columns(2)
            row2 = st.columns(2)
            grids = [row1[0], row1[1], row2[0], row2[1]]
            for grid_col, (bkey, label) in zip(grids, sc_keys):
                with grid_col:
                    if st.button(label, key=bkey, width="stretch"):
                        preset_name = {v: k for k, v in SHORT.items()}[label]
                        st.session_state["_scenario_sel"] = label
                        st.session_state["preset"] = preset_name
                        st.session_state["_pending_preset"] = preset_name
                        for key in ("_lift_sel", "_reward_sel", "_enroll_sel"):
                            st.session_state[key] = None
                        st.rerun()
    with c_lift:
        with st.container(key="wrap_lift"):
            st.markdown("<div class='ctrl-label'>Repeat-rate lift</div>", unsafe_allow_html=True)
            cols = st.columns(len(lift_keys))
            for col, (bkey, opt) in zip(cols, lift_keys):
                with col:
                    if st.button(f"+{opt*100:.0f}", key=bkey, width="stretch"):
                        st.session_state["_lift_sel"] = opt
                        _set("lift", opt)
                        st.rerun()
    with c_rew:
        with st.container(key="wrap_reward"):
            st.markdown("<div class='ctrl-label'>Average reward</div>", unsafe_allow_html=True)
            cols = st.columns(len(rew_keys))
            for col, (bkey, opt) in zip(cols, rew_keys):
                with col:
                    if st.button(f"${opt}", key=bkey, width="stretch"):
                        st.session_state["_reward_sel"] = opt
                        _set("avg_reward", opt)
                        st.rerun()
    with c_enr:
        with st.container(key="wrap_enroll"):
            st.markdown("<div class='ctrl-label'>New-buyer enrollment</div>", unsafe_allow_html=True)
            cols = st.columns(len(enr_keys))
            for col, (bkey, opt) in zip(cols, enr_keys):
                with col:
                    if st.button(f"{opt:.0%}", key=bkey, width="stretch"):
                        st.session_state["_enroll_sel"] = opt
                        _set("new_enroll", opt)
                        st.rerun()
            st.markdown("""<style>
            .st-key-reset_scenarios_btn button{background:rgba(0,0,0,0.25)!important;
                color:#ffffff!important;border:1px solid rgba(255,255,255,0.3)!important;
                font-size:0.95rem!important;font-weight:700!important;border-radius:6px!important;
                padding:6px 0!important;margin-top:4px!important;}
            </style>""", unsafe_allow_html=True)
            if st.button("↺  Reset scenarios", key="reset_scenarios_btn", width="stretch"):
                on_reset("scenarios")
                st.rerun()


def _year_banner(df: pd.DataFrame, sel_t: int | None):
    """Show a compact selected-year highlight strip. Returns the selected row or None."""
    if sel_t is None or sel_t <= 0:
        return None
    rows = df[df["t"] == sel_t]
    if rows.empty:
        return None
    row = rows.iloc[0]
    profit_color = "#4CAF50" if row["Program profit"] >= 0 else "#FF5252"
    st.markdown(f"""
    <div style='background:#132d50;border-left:4px solid #FFD520;border-radius:6px;
                padding:10px 20px;margin-bottom:8px;display:flex;gap:32px;flex-wrap:wrap;align-items:center;'>
      <span style='font-size:1.1rem;font-weight:900;color:#FFD520;'>&#9654; {row["Year"]}</span>
      <span style='color:#90b4e0;font-size:0.85rem;font-weight:700;'>
        Enrolled: <b style='color:#4DD0E1;font-size:1.1rem;'>{int(row["Enrolled owners"]):,}</b> &nbsp;|&nbsp;
        Program profit: <b style='color:{profit_color};font-size:1.1rem;'>{m(row["Program profit"])}</b> &nbsp;|&nbsp;
        Cost savings: <b style='color:#FFD520;font-size:1.1rem;'>{m(row["Total cost savings"])}</b> &nbsp;|&nbsp;
        Total value: <b style='color:#4CAF50;font-size:1.1rem;'>{m(row["Total value"])}</b> &nbsp;|&nbsp;
        Cumulative: <b style='color:#CE93D8;font-size:1.1rem;'>{m(row["Cumulative total value"])}</b>
      </span>
    </div>
    """, unsafe_allow_html=True)
    return row


def main():
    st.set_page_config(page_title="MyGarage Value Calculator", page_icon="🚗", layout="wide",
                       initial_sidebar_state="expanded")

    if "preset" not in st.session_state:
        st.session_state["preset"] = "Realistic (recommended)"
        st.session_state["btn_scenario"] = "Realistic"
        apply_preset()

    if "selected_year_t" not in st.session_state:
        st.session_state["selected_year_t"] = None
    if "kpi_sel" not in st.session_state:
        st.session_state["kpi_sel"] = None
    if "_toggle_sidebar" not in st.session_state:
        st.session_state["_toggle_sidebar"] = False

    # Apply any pending preset change BEFORE widgets are instantiated
    if st.session_state.get("_pending_preset"):
        st.session_state["preset"] = st.session_state["_pending_preset"]
        apply_preset()
        st.session_state["_pending_preset"] = None

    # Apply any pending single-key overrides (lift, avg_reward, new_enroll etc.)
    for k, v in st.session_state.pop("_pending_overrides", {}).items():
        st.session_state[k] = v
        st.session_state[f"_{k}"] = v * 100
        if k in _M_KEYS:
            st.session_state[f"_m_{k}"] = v / 1e6

    # Logo in sidebar — clicking navigates home
    st.logo("logo.svg", size="large")

    # Force sidebar always open on desktop, hide on mobile
    st.markdown("""
    <style>
    #MainMenu { visibility: hidden; }

    /* ── DESKTOP: always show sidebar, hide toggle buttons ── */
    @media (min-width: 769px) {
        [data-testid="stSidebar"] {
            transform: none !important;
            display: block !important;
            visibility: visible !important;
            left: 0 !important;
            min-width: 200px !important;
            max-width: 200px !important;
            width: 200px !important;
        }
        [data-testid="stSidebarCollapseButton"],
        div[data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
    }

    /* ── MOBILE: hide sidebar, show expand button ── */
    @media (max-width: 768px) {
        [data-testid="stSidebar"] {
            display: none !important;
        }
        div[data-testid="stSidebarCollapsedControl"] {
            display: flex !important;
            position: fixed !important;
            top: 12px !important;
            left: 12px !important;
            z-index: 9999 !important;
        }
        div[data-testid="stSidebarCollapsedControl"] button {
            background: #1565C0 !important;
            border: 2px solid #FFD520 !important;
            border-radius: 8px !important;
            color: #FFD520 !important;
        }
        /* Main content takes full width on mobile */
        .stMainBlockContainer {
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
        }
        /* Stack the 4-column controls vertically */
        [data-testid="stHorizontalBlock"]:has(.st-key-wrap_scenario) {
            flex-direction: column !important;
            margin: 0 -0.75rem !important;
        }
        [data-testid="stHorizontalBlock"]:has(.st-key-wrap_scenario) > div {
            width: 100% !important;
            flex: none !important;
        }
        /* Hero: shrink and stack */
        .mg-hero {
            flex-direction: column !important;
            align-items: flex-start !important;
            padding: 10px 12px !important;
            margin: 0 -0.75rem !important;
        }
        .mg-hero-text h1 { font-size: 1.4rem !important; }
        .mg-hero-text .sub { font-size: 0.82rem !important; }
        .mg-hero-text .team-line { font-size: 0.72rem !important; }
        .mg-hero-scenario { text-align: left !important; margin-top: 6px !important; }
        .mg-hero-scenario .sc-badge { font-size: 1rem !important; padding: 5px 14px !important; }
        /* Inputs bar and callout: allow wrapping on mobile */
        .inputs-bar, .callout-strip {
            flex-wrap: wrap !important;
            margin: 0 -0.75rem !important;
            gap: 4px !important;
            padding: 8px 6px !important;
        }
        .inputs-bar .ib-item, .callout-strip .co-item {
            padding: 4px 10px !important;
            width: 30% !important;
            border-right: none !important;
            border-bottom: 1px solid rgba(255,213,32,0.15) !important;
        }
        .inputs-bar .ib-val { font-size: 1.1rem !important; }
        .callout-strip .co-num { font-size: 1.1rem !important; }
        /* KPI row: wrap tiles */
        .kpi-row { flex-wrap: wrap !important; margin: 0 -0.75rem !important; }
        .kpi-item { width: 50% !important; flex: none !important; }
        .kpi-value { font-size: 1.5rem !important; }
    }
    </style>
    """, unsafe_allow_html=True)

    # ---------------- Sidebar ----------------
    with st.sidebar:
        st.markdown("**Inputs** — fine-tune below")

        with st.expander("CarMax baseline (FY2026)", expanded=False):
            num("Retail used units / year", "retail_units", 1000.0)
            num("Average selling price ($)", "asp", 100.0)
            num("Used gross profit per car ($)", "gpu", 25.0)
            num("EPP revenue per car ($)", "epp_per_car", 25.0)
            numM("Advertising spend", "advertising", 1.0)

        with st.expander("Adoption", expanded=False):
            num("Recent owners eligible at launch", "recent_owners", 10000.0,
                help="CarMax buyers from FY2024-26 (~2.34M).")
            pct("Recent owners who enroll", "existing_enroll", 60.0)
            pct("New buyers who enroll at delivery", "new_enroll", 90.0)
            pct("Year-1 rollout ramp", "year1_ramp", 100.0, 5.0,
                help="Share of full adoption reached in Year 1 (pilot to national).")
            pct("Enrolled owners lost per year", "attrition", 50.0,
                help="Owners who sell the car elsewhere or stop using the app.")

        with st.expander("Repeat purchase & rewards", expanded=False):
            num("Ownership cycle (years)", "cycle_years", 1.0, minv=1.0)
            pct("Baseline repeat rate (per cycle)", "base_repeat", 60.0)
            pct("Repeat-rate lift from MyGarage (pts)", "lift", 15.0, 0.5)
            num("Average reward redeemed ($)", "avg_reward", 25.0)
            pct("Repeat buyers who redeem a reward", "reward_take", 100.0, 5.0)

        with st.expander("Service & condition scans"):
            pct("Enrolled owners who service at CarMax", "svc_share", 60.0)
            pct("Baseline owners who service at CarMax", "svc_share_baseline", 30.0)
            num("Service visits / year", "visits", 0.1, "%.1f")
            num("Revenue per visit ($)", "ticket", 5.0)
            pct("Service margin", "svc_margin", 60.0)
            pct("Owners doing a yearly scan", "scan_share", 60.0)
            num("Labor cost per scan ($)", "scan_cost", 1.0)

        with st.expander("Program costs"):
            numM("One-time build", "build_cost", 0.25)
            numM("Fixed run cost / year", "fixed_cost", 0.1)

        with st.expander("Cost-savings levers", expanded=False):
            num("Acquisition cost avoided per extra repeat buyer (x avg ad $/car)",
                "acq_mult", 0.05, "%.2f",
                help="1.0 = the ~$362 CarMax spends on advertising per retail car.")
            pct("Ad cost saved on baseline repeat buyers (reached in-app)", "owned_shift", 80.0)
            pct("Repeat buyers who trade in", "trade_rate", 100.0)
            pct("Trade-ins with a verified care record", "badge_share", 100.0)
            num("Avg reconditioning cost per car ($)", "recon_cost", 50.0,
                help="Not disclosed by CarMax; team estimate.")
            pct("Recon cost cut on verified trade-ins", "recon_reduction", 40.0)
            num("Appraisal/wholesale loss avoided per verified trade-in ($)",
                "appraisal_saving", 5.0)
            num("Care contacts per owner / year", "contacts", 0.1, "%.1f")
            num("Cost per care contact ($)", "contact_cost", 1.0)
            pct("Contacts avoided via in-app self-service", "contact_reduction", 60.0)
            num("Goodwill/warranty cost avoided per scan ($)", "goodwill_per_scan", 1.0)
            pct("Scans that catch an issue early", "issue_detect", 40.0)

        with st.expander("Finance"):
            pct("Tax rate", "tax_rate", 40.0)
            pct("Discount rate (NPV)", "discount_rate", 25.0)
            st.number_input("Build year (Year 0)", key="start_year", step=1, format="%d")

        st.markdown("""<style>
        .st-key-reset_inputs_btn button{background:#1a3d6e!important;color:#FFD520!important;
            border:1px solid rgba(255,213,32,0.5)!important;font-weight:700!important;
            border-radius:6px!important;width:100%!important;}
        </style>""", unsafe_allow_html=True)
        if st.button("↺  Reset inputs to scenario defaults", key="reset_inputs_btn", width="stretch",
                     help="Restore all sidebar values to the current scenario's defaults"):
            on_reset("inputs")
            st.rerun()

    p = Inputs(**{f.name: st.session_state[f.name] for f in fields(Inputs)})
    p.start_year = int(p.start_year)
    df = run_model(p)
    yrs = df[df.t > 0]

    # ---------------- KPIs ----------------
    prog5 = df["Program profit"].sum()
    sav5 = yrs["Total cost savings"].sum()
    tot5 = df["Total value"].sum()
    roi_prog = prog5 / p.build_cost
    roi_tot = tot5 / p.build_cost
    y5 = yrs.iloc[-1]
    dep = p.build_cost / 5
    ni_y5 = (y5["Total value"] - dep) * (1 - p.tax_rate)
    eps_y5 = ni_y5 / (SHARES_OUTSTANDING_M * 1e6)
    npv_tot = npv(df["Total value"].tolist(), p.discount_rate)
    rev5 = yrs["Revenue"].sum()
    margin_prog = yrs["Program profit"].sum() / rev5 if rev5 else 0
    margin_tot = yrs["Total value"].sum() / rev5 if rev5 else 0
    be_prog = breakeven_lift(p, False)
    be_tot = breakeven_lift(p, True)

    # ── Presentation CSS ──────────────────────────────────────────────────────
    st.markdown("""
    <style>
    /* ── Import Inter + Poppins from Google Fonts ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Poppins:wght@400;500;600;700;800;900&display=swap');

    /* ── Apply Inter/Poppins to all text — never touch icon font classes ── */
    body, h1, h2, h3, h4, h5, h6,
    p, label, input, textarea, select,
    [data-testid="stMarkdownContainer"] *,
    [data-testid="stText"],
    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"],
    [data-testid="stMetricDelta"],
    [data-testid="stNumberInput"] input,
    [data-testid="stSlider"] p,
    [data-testid="stCaption"],
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] h2 {
        font-family: "Inter", "Poppins", sans-serif !important;
    }
    /* Buttons: only the text node inside, not the icon span */
    [data-testid="stButton"] button p,
    [data-testid="stButton"] button > div {
        font-family: "Inter", "Poppins", sans-serif !important;
    }


    /* ── Plotly cursor: pointer instead of crosshair ── */
    .js-plotly-plot .plotly .cursor-crosshair { cursor: pointer !important; }
    .js-plotly-plot .plotly svg { cursor: pointer !important; }

    /* ── Remove top dead space ── */
    header[data-testid="stHeader"] { display: none !important; }
    /* ── Hide Streamlit Cloud chrome ── */
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    footer,
    footer > *,
    #stDecoration { display: none !important; visibility: hidden !important; }
    .stMainBlockContainer { padding-top: 0 !important; padding-left: 1.5rem !important; padding-right: 1.5rem !important; }
    /* Tight vertical rhythm — everything flows as one page */
    .stVerticalBlock { gap: 0.35rem !important; }
    /* Control row: no gap between the 4 colour sections */
    .st-key-wrap_scenario > div, .st-key-wrap_lift > div,
    .st-key-wrap_reward > div, .st-key-wrap_enroll > div { gap: 0 !important; }
    /* Kill column gaps so colour blocks sit flush against each other */
    .st-key-wrap_scenario, .st-key-wrap_lift,
    .st-key-wrap_reward,   .st-key-wrap_enroll { height: 100% !important; }
    [data-testid="stHorizontalBlock"]:has(.st-key-wrap_scenario) {
        gap: 0 !important;
        padding: 0 !important;
        margin: 0 -1.5rem !important;
    }

    /* ═══════════════════════════════════════════════════
       HERO BANNER — full-width flush header, no rounding
    ═══════════════════════════════════════════════════ */
    .mg-hero {
        background: #0d3880;
        border-radius: 0;
        padding: 10px 24px 10px 24px;
        margin: 0 -1.5rem 0 -1.5rem;
        border-bottom: 3px solid #FFD520;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
    }
    .mg-hero-left { display: flex; align-items: center; gap: 20px; }
    .mg-hero-logo { flex-shrink: 0; cursor: pointer; }
    .mg-hero-logo a { display: block; line-height: 0; }
    .mg-hero-logo svg { transition: opacity 0.15s; }
    .mg-hero-logo a:hover svg { opacity: 0.8; }
    .mg-hero-text h1 {
        font-size: 2.1rem; font-weight: 900; color: #FFD520;
        margin: 0 0 2px 0; letter-spacing: -0.5px;
    }
    .mg-hero-text .sub { font-size: 1rem; color: #e0eeff; font-weight: 500; }
    .mg-hero-text .team-line {
        font-size: 0.9rem; color: #ffffff; margin-top: 4px; font-weight: 700;
    }
    .mg-hero-scenario { text-align: right; flex-shrink: 0; }
    .mg-hero-scenario .sc-label {
        font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1.5px;
        color: #e0eeff; font-weight: 700; margin-bottom: 6px;
    }
    .mg-hero-scenario .sc-badge {
        display: inline-block; background: #FFD520; color: #051e45;
        font-weight: 900; font-size: 1.3rem; border-radius: 6px; padding: 8px 24px;
    }

    /* ═══════════════════════════════════════════════════
       CONTROLS — section labels
    ═══════════════════════════════════════════════════ */
    .ctrl-label {
        font-family: "Inter", "Poppins", sans-serif !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
        margin-bottom: 6px !important;
        letter-spacing: 0 !important;
        color: #ffffff !important;
        text-align: center !important;
    }
    [data-testid="stButton"] button {
        font-family: "Inter", "Poppins", sans-serif !important;
        font-size: 1.15rem !important;
        font-weight: 600 !important;
        padding: 9px 6px !important;
        border-radius: 6px !important;
        min-height: 42px !important;
        border: none !important;
        box-shadow: none !important;
        letter-spacing: 0 !important;
    }
    [data-testid="stButton"] button p,
    [data-testid="stButton"] button div {
        font-family: "Inter", "Poppins", sans-serif !important;
        font-size: 1.15rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
        letter-spacing: 0 !important;
    }

    /* ═══════════════════════════════════════════════════
       ACTIVE INPUTS BAR
    ═══════════════════════════════════════════════════ */
    .inputs-bar {
        background: #091e3a;
        border-top: 2px solid rgba(255,213,32,0.35);
        border-bottom: 2px solid rgba(255,213,32,0.35);
        border-left: none; border-right: none;
        border-radius: 0;
        padding: 7px 8px;
        display: flex;
        gap: 0;
        flex-wrap: nowrap;
        align-items: center;
        justify-content: space-around;
        margin: 0 -1.5rem;
    }
    .inputs-bar .ib-item {
        display: flex; flex-direction: column; align-items: center;
        padding: 0 20px; border-right: 1px solid rgba(255,213,32,0.2);
    }
    .inputs-bar .ib-item:last-child { border-right: none; }
    .inputs-bar .ib-val  { font-size: 1.5rem; font-weight: 900; color: #FFD520; line-height: 1.1; }
    .inputs-bar .ib-lbl  {
        font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1px;
        color: #90b4e0; font-weight: 700; margin-top: 2px;
    }

    /* ═══════════════════════════════════════════════════
       KPI ROW — full-width band, no card border
    ═══════════════════════════════════════════════════ */
    .kpi-row {
        display: flex;
        margin: 0 -1.5rem;
        background: #071528;
        border-top: 3px solid #FFD520;
        border-bottom: 3px solid #FFD520;
        border-left: none; border-right: none;
        border-radius: 0;
        overflow: hidden;
    }
    .kpi-item {
        flex: 1;
        text-align: center;
        padding: 10px 8px 8px 8px;
        border-left: 1px solid rgba(255,213,32,0.4);
    }
    .kpi-item:first-child { border-left: none; }
    .kpi-label {
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        font-weight: 700;
        color: #e0eeff;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 2.2rem;
        font-weight: 900;
        line-height: 1;
        margin-bottom: 4px;
    }
    .kpi-delta { font-size: 0.78rem; color: #b0c8f0; font-weight: 600; }
    .kv-green  { color: #4CAF50; }
    .kv-orange { color: #FF9800; }
    .kv-blue   { color: #64B5F6; }
    .kv-purple { color: #CE93D8; }
    .kv-teal   { color: #4DD0E1; }

    /* ═══════════════════════════════════════════════════
       CALLOUT STRIP
    ═══════════════════════════════════════════════════ */
    .callout-strip {
        background: #091e3a;
        border-top: 1px solid rgba(100,140,200,0.3);
        border-bottom: 1px solid rgba(100,140,200,0.3);
        border-left: none; border-right: none;
        border-radius: 0;
        padding: 7px 8px;
        display: flex;
        gap: 0;
        flex-wrap: nowrap;
        margin: 0 -1.5rem 0 -1.5rem;
        align-items: center;
        justify-content: space-around;
    }
    .callout-strip .co-item {
        display: flex; flex-direction: column; align-items: center;
        padding: 0 16px; border-right: 1px solid rgba(100,140,200,0.25);
    }
    .callout-strip .co-item:last-child { border-right: none; }
    .callout-strip .co-num  { font-size: 1.6rem; font-weight: 900; color: #FFD520; line-height: 1.1; }
    .callout-strip .co-txt  { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.8px; color: #90b4e0; font-weight: 700; margin-top: 2px; text-align: center; }

    /* ═══════════════════════════════════════════════════
       PITCH BOX + SGA BAR
    ═══════════════════════════════════════════════════ */
    .pitch-box {
        background: #0d2a52;
        border-left: 5px solid #FFD520;
        border-radius: 10px;
        padding: 28px 30px 24px 30px;
        margin-bottom: 10px;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 540px;
    }
    .pitch-box h3 {
        color: #FFD520; font-size: 1.5rem; font-weight: 800; margin: 0 0 20px 0;
    }
    .pitch-box ul { margin: 0; padding-left: 22px; flex: 1; }
    .pitch-box li {
        color: #e0eeff; font-size: 1.25rem; margin-bottom: 18px; line-height: 1.75;
    }
    .pitch-box li b { color: #FFD520; }
    .sga-bar {
        background: #0d2a52;
        border: 1px solid #FFD520;
        border-radius: 8px;
        padding: 16px 22px;
        color: #e0eeff;
        font-size: 1.2rem;
        line-height: 1.7;
    }
    .sga-bar b { color: #FFD520; font-size: 1.3rem; }

    /* ═══════════════════════════════════════════════════
       SIDEBAR + LOGO
    ═══════════════════════════════════════════════════ */
    /* Make the logo prominent — full-width navy block at top of sidebar */
    [data-testid="stSidebarHeader"] {
        background: #0d3880 !important;
        padding: 12px 16px !important;
        border-bottom: 3px solid #FFD520 !important;
    }
    [data-testid="stSidebarHeader"] img {
        width: 100% !important;
        max-width: 220px !important;
        height: auto !important;
    }
    /* Remove all borders/outlines from sidebar expanders and inputs */
    [data-testid="stSidebar"] details,
    [data-testid="stSidebar"] details summary,
    [data-testid="stSidebar"] [data-testid="stExpander"],
    [data-testid="stSidebar"] [data-testid="stExpanderDetails"],
    [data-testid="stSidebar"] [data-testid="stNumberInput"] div,
    [data-testid="stSidebar"] [data-testid="stNumberInput"] input,
    [data-testid="stSidebar"] [data-testid="stSlider"],
    [data-testid="stSidebar"] [data-baseweb="input"] {
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    /* Subtle separator line between expanders instead of full box border */
    [data-testid="stSidebar"] details {
        border-bottom: 1px solid rgba(100,140,200,0.15) !important;
        border-radius: 0 !important;
    }

    [data-testid="stSidebar"] { font-size: 0.82rem !important; }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label {
        font-size: 0.82rem !important;
        font-weight: 500 !important;
        line-height: 1.4 !important;
    }
    [data-testid="stSidebar"] input { font-size: 0.85rem !important; font-weight: 600 !important; }
    [data-testid="stSidebar"] summary p,
    [data-testid="stSidebar"] summary span {
        font-size: 0.88rem !important; font-weight: 700 !important;
    }
    [data-testid="stSidebar"] h2 { font-size: 1.05rem !important; font-weight: 900 !important; }
    /* More breathing room between sidebar widgets */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 1rem !important; }
    [data-testid="stSidebar"] [data-testid="stNumberInput"] { margin-bottom: 0.5rem !important; }
    </style>
    """, unsafe_allow_html=True)

    # ── Hero banner ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class='mg-hero'>
        <div class='mg-hero-left'>
            <div class='mg-hero-logo'>
                <a href="/" title="Back to home">
                <svg width="72" height="72" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="6" y="28" width="60" height="38" rx="3" fill="#FFD520"/>
                  <rect x="10" y="32" width="52" height="30" rx="2" fill="#0d3880"/>
                  <line x1="10" y1="42" x2="62" y2="42" stroke="#FFD520" stroke-width="2"/>
                  <line x1="10" y1="52" x2="62" y2="52" stroke="#FFD520" stroke-width="2"/>
                  <polygon points="2,30 36,8 70,30" fill="#FFD520"/>
                  <polygon points="6,30 36,12 66,30" fill="#1a5fa8"/>
                  <rect x="17" y="55" width="38" height="7" rx="3" fill="#FFD520"/>
                  <rect x="22" y="50" width="28" height="7" rx="3" fill="#FFD520"/>
                  <circle cx="24" cy="62" r="3" fill="#0d3880"/>
                  <circle cx="48" cy="62" r="3" fill="#0d3880"/>
                </svg>
                </a>
            </div>
            <div class='mg-hero-text'>
                <h1>MyGarage by CarMax</h1>
                <div class='sub'>5-Year Revenue &amp; Profitability Calculator</div>
                <div class='team-line'>Team 5 &mdash; Anthony &nbsp;|&nbsp; Eric &nbsp;|&nbsp; Evaslie &nbsp;|&nbsp; Josh &nbsp;|&nbsp; Kip &nbsp;|&nbsp; Mike &nbsp;&middot;&nbsp; UVA McIntire MSIT &nbsp;&middot;&nbsp; Prof. Stefano Grazioli, Ph.D.</div>
            </div>
        </div>
        <div class='mg-hero-scenario'>
            <div class='sc-label'>Active Scenario</div>
            <div class='sc-badge'>{st.session_state['preset']}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


    demo_controls()

    # ── Active-inputs annotation bar ─────────────────────────────────────────
    st.markdown(f"""
    <div class='inputs-bar'>
        <div class='ib-item'><span class='ib-val'>{p.new_enroll:.0%}</span><span class='ib-lbl'>New-buyer enrollment</span></div>
        <div class='ib-item'><span class='ib-val'>+{p.lift*100:.0f} pts</span><span class='ib-lbl'>Repeat-rate lift</span></div>
        <div class='ib-item'><span class='ib-val'>${p.avg_reward:,.0f}</span><span class='ib-lbl'>Avg reward</span></div>
        <div class='ib-item'><span class='ib-val'>{p.existing_enroll:.0%}</span><span class='ib-lbl'>Existing owners enrolled</span></div>
        <div class='ib-item'><span class='ib-val'>${p.build_cost/1e6:.0f}M</span><span class='ib-lbl'>Build cost</span></div>
        <div class='ib-item'><span class='ib-val'>{p.year1_ramp:.0%}</span><span class='ib-lbl'>Yr-1 ramp</span></div>
    </div>
    """, unsafe_allow_html=True)

    # ── KPI row — interactive ─────────────────────────────────────────────────
    pb = payback_year(df["Cumulative total value"], df)
    if "kpi_sel" not in st.session_state:
        st.session_state["kpi_sel"] = None

    KPI_DEFS = [
        ("total",   "5-Year Total Value",   m(tot5),          f"{m(sav5)} from cost savings", "kv-green"),
        ("roi",     "5-Year ROI",           f"{roi_tot:,.0%}", f"on ${p.build_cost/1e6:.0f}M build", "kv-orange"),
        ("payback", "Payback Period",        pb,               "incl. cost savings",            "kv-blue"),
        ("npv",     "NPV",                  m(npv_tot),        f"@ {p.discount_rate:.0%} discount","kv-purple"),
        ("eps",     "Yr-5 Earnings Lift",   m(ni_y5),          f"+${eps_y5:.2f}/share EPS",    "kv-teal"),
    ]

    # KPI row: HTML display + small toggle button per tile
    COLOR_MAP = {"kv-green": "#4CAF50", "kv-orange": "#FF9800",
                 "kv-blue": "#64B5F6", "kv-purple": "#CE93D8", "kv-teal": "#4DD0E1"}

    kpi_btn_css = ""
    for kid, *_ in KPI_DEFS:
        is_sel = st.session_state["kpi_sel"] == kid
        bg = "#1a3d6e" if is_sel else "#071528"
        kpi_btn_css += (
            f".st-key-kpi_{kid} button{{background:{bg}!important;border:none!important;"
            f"border-top:{'3px solid #FFD520' if is_sel else '3px solid transparent'}!important;"
            f"border-radius:0!important;width:100%!important;padding:4px 0!important;"
            f"font-size:0.82rem!important;font-weight:600!important;color:#90b4e0!important;}}"
            f".st-key-kpi_{kid} button p,.st-key-kpi_{kid} button div"
            f"{{font-size:0.82rem!important;color:#90b4e0!important;}}"
        )
    st.markdown(f"<style>{kpi_btn_css}</style>", unsafe_allow_html=True)

    k_cols = st.columns(5)
    for col, (kid, label, value, delta, color_cls) in zip(k_cols, KPI_DEFS):
        is_sel = st.session_state["kpi_sel"] == kid
        val_color = COLOR_MAP[color_cls]
        tile_bg = "#1a3d6e" if is_sel else "#071528"
        top_border = "border-top:3px solid #FFD520;" if is_sel else "border-top:3px solid transparent;"
        with col:
            st.markdown(f"""
            <div style='background:{tile_bg};{top_border}text-align:center;
                        padding:8px 8px 2px 8px;border-left:1px solid rgba(255,213,32,0.15);'>
              <div style='font-size:0.72rem;text-transform:uppercase;letter-spacing:1px;
                          font-weight:700;color:#90b4e0;margin-bottom:4px;'>{label}</div>
              <div style='font-size:2.1rem;font-weight:900;line-height:1;color:{val_color};
                          font-family:"Inter","Poppins",sans-serif;'>{value}</div>
              <div style='font-size:0.82rem;color:#7090b8;font-weight:600;
                          margin-top:6px;padding-bottom:8px;'>{delta}</div>
            </div>""", unsafe_allow_html=True)
            toggle_label = "▲ collapse" if is_sel else "▼ details"
            if st.button(toggle_label, key=f"kpi_{kid}", width="stretch"):
                st.session_state["kpi_sel"] = None if is_sel else kid
                st.rerun()

    # KPI detail expansion strip
    sel = st.session_state["kpi_sel"]
    if sel == "total":
        c1, c2, c3 = st.columns(3)
        c1.metric("Program profit (5yr)", m(prog5), help="Revenue minus variable costs, fixed costs, and build")
        c2.metric("Cost savings (5yr)", m(sav5), help="Marketing, recon, appraisal, care, early detection")
        c3.metric("Total value (5yr)", m(tot5), help="Program profit + cost savings")
        scols = [c for c in df.columns if c.startswith("Savings:")]
        st.bar_chart(yrs.set_index("Year")[scols].rename(columns=lambda s: s.replace("Savings: ", "")))
    elif sel == "roi":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Build cost", m(p.build_cost))
        c2.metric("5-yr return", m(tot5))
        c3.metric("ROI (total)", f"{roi_tot:.0%}")
        c4.metric("ROI (program only)", f"{roi_prog:.0%}")
        st.caption("ROI = 5-year value after build ÷ build cost. Total ROI includes cost savings; program-only does not.")
    elif sel == "payback":
        cum = df[["Year", "Cumulative total value"]].copy()
        cum["Cumulative total value"] = cum["Cumulative total value"] / 1e6
        st.line_chart(cum.set_index("Year"), y="Cumulative total value", color="#00E676")
        st.caption(f"Cumulative total value turns positive at **{pb}** — that is the payback year.")
    elif sel == "npv":
        disc_vals = [v / (1 + p.discount_rate) ** i for i, v in enumerate(df["Total value"].tolist())]
        npv_df = pd.DataFrame({"Year": df["Year"], "Discounted value ($M)": [v / 1e6 for v in disc_vals]})
        st.bar_chart(npv_df.set_index("Year"), color="#CE93D8")
        st.caption(f"Each year's value discounted at {p.discount_rate:.0%}/yr. Sum = {m(npv_tot)} NPV.")
    elif sel == "eps":
        y5r = yrs.iloc[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("Yr-5 total value", m(y5r["Total value"]))
        c2.metric("After tax & depreciation", m(ni_y5))
        c3.metric("EPS lift", f"+${eps_y5:.3f}")
        st.caption(f"Depreciation = build ÷ 5 = {m(p.build_cost/5)}/yr. Tax rate {p.tax_rate:.0%}. "
                   f"Diluted shares: {SHARES_OUTSTANDING_M:.1f}M.")

    # ── Callout strip ─────────────────────────────────────────────────────────
    sga_like_y5 = yrs[["Savings: marketing (new)", "Savings: marketing (owned channel)",
                        "Savings: customer care"]].iloc[-1].sum()
    clv0, clv1 = clv(p, False), clv(p, True)
    enrolled_y5 = int(yrs["Enrolled owners"].iloc[-1])
    st.markdown(f"""
    <div class='callout-strip'>
        <div class='co-item'><span class='co-num'>{enrolled_y5:,}</span>
            <span class='co-txt'>enrolled owners by Yr 5</span></div>
        <div class='co-item'><span class='co-num'>${clv1:,.0f}</span>
            <span class='co-txt'>lifetime value per buyer</span></div>
        <div class='co-item'><span class='co-num'>{p.lift*100:.0f} pts</span>
            <span class='co-txt'>repeat-rate lift</span></div>
        <div class='co-item'><span class='co-num'>{sga_like_y5/SGA_TARGET:.0%}</span>
            <span class='co-txt'>of CarMax $200M SG&amp;A target met (Yr 5)</span></div>
        <div class='co-item'><span class='co-num'>{margin_tot:.1%}</span>
            <span class='co-txt'>margin incl. savings</span></div>
    </div>
    """, unsafe_allow_html=True)

    tabs = st.tabs(["Overview", "Assumptions in use", "Cost savings", "Profitability",
                    "Customer experience", "Sensitivity", "Year-by-year table", "Sources & method"])

    # ---------------- Overview ----------------
    with tabs[0]:
        left, right = st.columns([3, 2])
        with left:
            fig = go.Figure()

            # Build rich hover data for each year row
            hover_profit = [
                f"<b>{row['Year']}</b><br>"
                f"<b style='color:#90b8ff'>Program profit: ${row['Program profit']/1e6:+.2f}M</b><br>"
                f"Revenue: ${row['Revenue']/1e6:.2f}M<br>"
                f"Variable costs: ${row['Variable costs']/1e6:.2f}M<br>"
                f"Rewards paid: ${row['Rewards paid']/1e6:.2f}M<br>"
                f"Fixed costs: ${row['Fixed costs']/1e6:.2f}M<br>"
                f"Repeat cars: {row['Incremental repeat cars']:,.0f}<br>"
                f"Service visits: {row['Service visits']:,.0f}"
                for _, row in df.iterrows()
            ]
            hover_savings = [
                f"<b>{row['Year']}</b><br>"
                f"<b style='color:#FFD520'>Cost savings: ${row['Total cost savings']/1e6:.2f}M</b><br>"
                f"Marketing (new): ${row['Savings: marketing (new)']/1e6:.2f}M<br>"
                f"Marketing (owned): ${row['Savings: marketing (owned channel)']/1e6:.2f}M<br>"
                f"Reconditioning: ${row['Savings: reconditioning']/1e6:.2f}M<br>"
                f"Appraisal risk: ${row['Savings: appraisal risk']/1e6:.2f}M<br>"
                f"Customer care: ${row['Savings: customer care']/1e6:.2f}M<br>"
                f"Early detection: ${row['Savings: early detection']/1e6:.2f}M"
                for _, row in df.iterrows()
            ]
            hover_cum = [
                f"<b>{row['Year']}</b><br>"
                f"<b style='color:#00E676'>Cumulative value: ${row['Cumulative total value']/1e6:.2f}M</b><br>"
                f"Total value this year: ${row['Total value']/1e6:.2f}M<br>"
                f"Enrolled owners: {int(row['Enrolled owners']):,}"
                for _, row in df.iterrows()
            ]

            fig.add_bar(x=df["Year"], y=df["Program profit"] / 1e6, name="Program profit",
                        marker_color="#2979FF",
                        text=[f"${v/1e6:+.1f}M" for v in df["Program profit"]],
                        textposition="outside", textfont=dict(color="#90b8ff", size=17, family="Inter, Poppins, sans-serif"),
                        hovertemplate="%{customdata}<extra></extra>",
                        customdata=hover_profit)
            fig.add_bar(x=df["Year"], y=df["Total cost savings"] / 1e6, name="Cost savings",
                        marker_color=ACCENT,
                        text=[f"${v/1e6:.1f}M" if v > 0 else "" for v in df["Total cost savings"]],
                        textposition="outside", textfont=dict(color="#FFD520", size=17, family="Inter, Poppins, sans-serif"),
                        hovertemplate="%{customdata}<extra></extra>",
                        customdata=hover_savings)
            cum_vals = df["Cumulative total value"] / 1e6
            fig.add_scatter(x=df["Year"], y=cum_vals,
                            name="Cumulative value", mode="lines+markers",
                            line=dict(color=GREEN, width=4),
                            marker=dict(size=10, color=GREEN),
                            hovertemplate="%{customdata}<extra></extra>",
                            customdata=hover_cum)
            # Annotate each cumulative point — skip Yr 0 (always -$8M build)
            for i, (yr, v) in enumerate(zip(df["Year"], cum_vals)):
                if i == 0:
                    continue
                fig.add_annotation(
                    x=yr, y=v,
                    text=f"<b>${v:.1f}M</b>",
                    showarrow=False,
                    yshift=20,
                    font=dict(color=GREEN, size=16, family="Inter, Poppins, sans-serif"),
                    bgcolor="rgba(4,21,45,0.75)",
                    borderpad=3,
                )
            # Clean up x-axis labels to just show year number
            x_labels = [str(p.start_year + t) for t in range(6)]
            fig.update_layout(
                barmode="relative", title="<b>Annual value by source ($M)</b>",
                title_font=dict(size=20, color="#FFD520"),
                height=520,
                hoverlabel=dict(
                    bgcolor="#0d2a52", bordercolor="#FFD520",
                    font=dict(size=14, color="#e0eeff", family="Inter, Poppins, sans-serif"),
                ),
                dragmode=False,
                legend=dict(orientation="h", y=-0.12, font=dict(size=15),
                            bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)"),
                margin=dict(t=60, l=10, r=10, b=60),
                paper_bgcolor="#04152D", plot_bgcolor="#0a2444",
                font=dict(color="#d0e4ff", size=14),
                xaxis=dict(gridcolor="rgba(255,255,255,0.07)",
                           tickfont=dict(size=17, family="Inter, Poppins, sans-serif"),
                           tickvals=df["Year"].tolist(), ticktext=x_labels),
                yaxis=dict(gridcolor="rgba(255,255,255,0.07)",
                           tickfont=dict(size=14, family="Inter, Poppins, sans-serif")),
            )
            sel_event = st.plotly_chart(fig, alt="Annual value waterfall chart",
                                        on_select="rerun", selection_mode="points",
                                        key="overview_chart")
            # Capture clicked year from bar selection
            pts = (sel_event.selection.get("points") or []) if sel_event and sel_event.selection else []
            if pts:
                clicked_x = pts[0].get("x")
                if clicked_x:
                    # Map "2027 (Yr 1)" format OR plain "2027" back to t index
                    clicked_t = next((row["t"] for _, row in df.iterrows() if row["Year"] == clicked_x
                                      or str(p.start_year + int(row["t"])) == str(clicked_x)), None)
                    if clicked_t is not None:
                        prev = st.session_state.get("selected_year_t")
                        st.session_state["selected_year_t"] = None if prev == clicked_t else clicked_t
                        st.rerun()
        with right:
            be_txt = (f"Break-even lift: <b>{be_tot*100:.1f} pts</b> with savings"
                      + (f", {be_prog*100:.1f} pts without" if be_prog is not None else "")
                      + f". We assume {p.lift*100:.1f} pts."
                      if be_tot is not None
                      else "Not profitable within tested lift range.")
            sga_like = yrs[["Savings: marketing (new)", "Savings: marketing (owned channel)",
                            "Savings: customer care"]].iloc[-1].sum()
            st.markdown(f"""
            <div class='pitch-box'>
                <h3>&#128200; What the board should hear</h3>
                <ul>
                <li>Program earns <b>{m(prog5)}</b> over 5 yrs on a <b>{m(p.build_cost)}</b> build.</li>
                <li>Design saves <b>{m(sav5)}</b> in costs CarMax already pays &mdash;
                    marketing, recon, appraisal, care &amp; warranty.</li>
                <li>Together: <b>{m(tot5)}</b> &middot; <b>{roi_tot:,.0%}</b> ROI &middot;
                    <b>{margin_tot:.1%}</b> margin (vs {margin_prog:.1%} program-only).</li>
                <li>{be_txt}</li>
                </ul>
            </div>
            <div class='sga-bar'>
                &#128200; By Yr 5 SG&amp;A-type savings
                <b>({m(sga_like)}/yr)</b> = <b>{sga_like/SGA_TARGET:.1%}</b>
                of CarMax's $200M savings target.
            </div>
            """, unsafe_allow_html=True)

        # ── Selected-year detail strip (shown when user clicks a bar) ────────
        sel_t = st.session_state.get("selected_year_t")
        if sel_t is not None and sel_t > 0:
            row = df[df["t"] == sel_t].iloc[0]
            yr_label = row["Year"]
            scols = [c for c in df.columns if c.startswith("Savings:")]
            st.markdown(f"""
            <div style='background:#0d2a52;border-top:3px solid #FFD520;border-bottom:3px solid #FFD520;
                        padding:14px 24px;margin:0 -1.5rem;display:flex;gap:0;flex-wrap:nowrap;
                        justify-content:space-around;align-items:center;'>
              <div style='text-align:center;padding:0 16px;border-right:1px solid rgba(255,213,32,0.3)'>
                <div style='font-size:0.78rem;text-transform:uppercase;letter-spacing:1px;color:#90b4e0;font-weight:700;'>Year</div>
                <div style='font-size:1.8rem;font-weight:900;color:#FFD520;'>{yr_label}</div>
              </div>
              <div style='text-align:center;padding:0 16px;border-right:1px solid rgba(255,213,32,0.3)'>
                <div style='font-size:0.78rem;text-transform:uppercase;letter-spacing:1px;color:#90b4e0;font-weight:700;'>Enrolled Owners</div>
                <div style='font-size:1.8rem;font-weight:900;color:#4DD0E1;'>{int(row["Enrolled owners"]):,}</div>
              </div>
              <div style='text-align:center;padding:0 16px;border-right:1px solid rgba(255,213,32,0.3)'>
                <div style='font-size:0.78rem;text-transform:uppercase;letter-spacing:1px;color:#90b4e0;font-weight:700;'>Program Profit</div>
                <div style='font-size:1.8rem;font-weight:900;color:#{"4CAF50" if row["Program profit"]>=0 else "FF5252"};'>{m(row["Program profit"])}</div>
              </div>
              <div style='text-align:center;padding:0 16px;border-right:1px solid rgba(255,213,32,0.3)'>
                <div style='font-size:0.78rem;text-transform:uppercase;letter-spacing:1px;color:#90b4e0;font-weight:700;'>Cost Savings</div>
                <div style='font-size:1.8rem;font-weight:900;color:#FFD520;'>{m(row["Total cost savings"])}</div>
              </div>
              <div style='text-align:center;padding:0 16px;border-right:1px solid rgba(255,213,32,0.3)'>
                <div style='font-size:0.78rem;text-transform:uppercase;letter-spacing:1px;color:#90b4e0;font-weight:700;'>Total Value</div>
                <div style='font-size:1.8rem;font-weight:900;color:#4CAF50;'>{m(row["Total value"])}</div>
              </div>
              <div style='text-align:center;padding:0 16px;'>
                <div style='font-size:0.78rem;text-transform:uppercase;letter-spacing:1px;color:#90b4e0;font-weight:700;'>Cumulative</div>
                <div style='font-size:1.8rem;font-weight:900;color:#CE93D8;'>{m(row["Cumulative total value"])}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)
        elif sel_t == 0:
            st.info("Year 0 is the build year — no revenue yet. Build cost: " + m(p.build_cost))

    # ---------------- Assumptions ----------------
    with tabs[1]:
        st.markdown(f"Every variable behind the numbers above (preset: **{st.session_state['preset']}**). "
                    "✎ = changed from the preset during this demo.")
        g1, g2 = st.columns(2)
        for i, (title, keys) in enumerate(GROUPS):
            with (g1 if i % 2 == 0 else g2):
                st.markdown(f"**{title}**")
                st.dataframe(assumptions_table(p, st.session_state["preset"], keys),
                             hide_index=True, width="stretch")
        st.caption("Key formulas: extra repeat cars = enrolled owners × lift ÷ cycle years · "
                   "rewards paid on every repeat purchase by an enrolled owner · "
                   "ROI = 5-yr value after build ÷ build cost · CAF finance income not counted.")

    # ---------------- Cost savings ----------------
    with tabs[2]:
        _year_banner(df, st.session_state.get("selected_year_t"))
        scols = [c_ for c_ in df.columns if c_.startswith("Savings:")]
        totals = yrs[scols].sum().sort_values()
        a, b = st.columns([3, 2])
        with a:
            fig = go.Figure(go.Bar(
                x=totals.values / 1e6, y=[s.replace("Savings: ", "").capitalize() for s in totals.index],
                orientation="h", marker_color=ACCENT,
                text=[m(v) for v in totals.values], textposition="outside",
                textfont=dict(color="#d0e4ff", size=16)))
            fig.update_layout(
                title="<b>Five-year cost savings by lever ($M)</b>",
                title_font=dict(size=21, color="#FFD520"),
                height=400, margin=dict(t=50, l=10, r=80),
                paper_bgcolor="#04152D", plot_bgcolor="#0a2444",
                font=dict(color="#d0e4ff", size=16),
                xaxis=dict(gridcolor="rgba(255,255,255,0.07)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.07)"),
            )
            st.plotly_chart(fig, alt="Cost savings by lever")
        with b:
            st.markdown("#### How the design saves money")
            st.markdown(
                "- **Marketing (new):** each extra repeat buyer is a customer CarMax didn't "
                "have to win with paid search and ads.\n"
                "- **Marketing (owned channel):** owners who would have come back anyway are "
                "reached in the app instead of through paid media.\n"
                "- **Reconditioning:** trade-ins with a verified CarMax care record need less "
                "work, building on CarMax's own per-unit recon cost program.\n"
                "- **Appraisal risk:** verified history means fewer mispriced trade-ins "
                "and wholesale losses.\n"
                "- **Customer care:** service booking, records and repair status in the app "
                "replace calls to the customer experience centers.\n"
                "- **Early detection:** yearly scans catch problems before they become "
                "warranty disputes or goodwill repairs (the Outback story)."
            )
        st.dataframe(
            (yrs.set_index("Year")[scols + ["Total cost savings"]] / 1e6).round(2)
            .rename(columns=lambda s: s.replace("Savings: ", "")),
            width="stretch")
        st.caption("$M per year. Every lever is editable under 'Cost-savings levers'.")

    # ---------------- Profitability ----------------
    with tabs[3]:
        _year_banner(df, st.session_state.get("selected_year_t"))
        a, b = st.columns(2)
        with a:
            wf = go.Figure(go.Waterfall(
                orientation="v",
                x=["Incremental revenue", "Car cost of sales", "Rewards", "Service & scan costs",
                   "Fixed costs", "Build", "Cost savings", "5-yr total value"],
                measure=["absolute", "relative", "relative", "relative", "relative",
                         "relative", "relative", "total"],
                y=[rev5 / 1e6,
                   -(yrs["Incremental repeat cars"] * (p.asp - p.gpu)).sum() / 1e6,
                   -yrs["Rewards paid"].sum() / 1e6,
                   -(yrs["Variable costs"].sum()
                     - (yrs["Incremental repeat cars"] * (p.asp - p.gpu)).sum()
                     - yrs["Rewards paid"].sum()) / 1e6,
                   -yrs["Fixed costs"].sum() / 1e6, -p.build_cost / 1e6, sav5 / 1e6, 0],
                increasing=dict(marker_color=GREEN), decreasing=dict(marker_color="#C0392B"),
                totals=dict(marker_color=BRAND)))
            wf.update_layout(
                title="<b>Five-year bridge: revenue → total value ($M)</b>",
                title_font=dict(size=21, color="#FFD520"),
                height=450,
                paper_bgcolor="#04152D", plot_bgcolor="#0a2444",
                font=dict(color="#d0e4ff", size=16),
                xaxis=dict(gridcolor="rgba(255,255,255,0.07)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.07)"),
            )
            st.plotly_chart(wf, alt="Waterfall bridge chart")
        with b:
            per_owner = tot5 / yrs["Enrolled owners"].mean() if yrs["Enrolled owners"].mean() else 0
            st.markdown("#### Profitability, not just revenue")
            k1, k2 = st.columns(2)
            k1.metric("Margin on MyGarage revenue", f"{margin_tot:.1%}",
                      f"{(margin_tot - margin_prog)*100:+.1f} pts from savings")
            k2.metric("5-yr value per enrolled owner", f"${per_owner:,.0f}")
            k1.metric("Reward cost as % of car profit",
                      f"{p.avg_reward / p.gpu:.0%}", help="Avg reward ÷ $2,253 gross profit per car")
            k2.metric("Yr-5 lift to FY2026 net earnings", f"{ni_y5 / 247.3e6:.1%}")
            st.caption(
                "Car revenue is large but low margin, so MyGarage's program margin looks thin. "
                "Cost savings fall straight to the bottom line, which is why they move "
                "profitability more than revenue. Year-5 net earnings depreciate the build over "
                "5 years and apply the tax rate.")

    # ---------------- Customer experience ----------------
    with tabs[4]:
        _year_banner(df, st.session_state.get("selected_year_t"))
        clv0, clv1 = clv(p, False), clv(p, True)
        r0, r1 = p.base_repeat, p.base_repeat + p.lift
        k = st.columns(4)
        k[0].metric("Repeat rate per cycle", f"{r1:.0%}", f"{(r1 - r0)*100:+.1f} pts")
        k[1].metric("Customer lifetime value", f"${clv1:,.0f}", f"{'+' if clv1 >= clv0 else '-'}${abs(clv1 - clv0):,.0f} vs ${clv0:,.0f} today")
        k[2].metric("Owners with a verified care record (Yr 5)",
                    f"{y5['Enrolled owners'] * p.badge_share:,.0f}")
        k[3].metric("Issues caught early by scans (5 yrs)",
                    f"{(yrs['Scans'] * p.issue_detect).sum():,.0f}")
        a, b = st.columns(2)
        with a:
            fig = go.Figure()
            fig.add_bar(x=["Without MyGarage", "With MyGarage"], y=[clv0, clv1],
                        marker_color=[GREY, GREEN], text=[f"${clv0:,.0f}", f"${clv1:,.0f}"],
                        textposition="outside", textfont=dict(size=17, color="#FFD520"))
            fig.update_layout(
                title="<b>Lifetime gross profit per CarMax buyer</b>",
                title_font=dict(size=21, color="#FFD520"),
                height=380, yaxis_title="$ per customer",
                paper_bgcolor="#04152D", plot_bgcolor="#0a2444",
                font=dict(color="#d0e4ff", size=16),
                yaxis=dict(gridcolor="rgba(255,255,255,0.07)"),
            )
            st.plotly_chart(fig, alt="Customer lifetime value comparison")
        with b:
            fig = go.Figure()
            fig.add_bar(x=yrs["Year"], y=yrs["Service visits"], name="Service visits captured",
                        marker_color="#2979FF",
                        text=[f"{v:,.0f}" for v in yrs["Service visits"]],
                        textposition="outside", textfont=dict(color="#d0e4ff", size=12))
            care_avoided = yrs["Enrolled owners"] * p.contacts * p.contact_reduction
            fig.add_bar(x=yrs["Year"], y=care_avoided,
                        name="Care calls avoided", marker_color=ACCENT,
                        text=[f"{v:,.0f}" for v in care_avoided],
                        textposition="outside", textfont=dict(color="#d0e4ff", size=12))
            fig.update_layout(
                title="<b>Touchpoints that keep owners connected</b>",
                title_font=dict(size=21, color="#FFD520"),
                height=380, barmode="group",
                legend=dict(orientation="h", y=-0.15, font=dict(size=13)),
                paper_bgcolor="#04152D", plot_bgcolor="#0a2444",
                font=dict(color="#d0e4ff", size=16),
                yaxis=dict(gridcolor="rgba(255,255,255,0.07)"),
            )
            st.plotly_chart(fig, alt="Service and care touchpoints")
        st.caption("CLV = gross profit per purchase (car + EPP + service over the ownership "
                   "cycle) plus discounted future repeat purchases, net of rewards. It answers "
                   "the 'extended customer life with us' point from the slide 12 notes.")

    # ---------------- Sensitivity ----------------
    with tabs[5]:
        _year_banner(df, st.session_state.get("selected_year_t"))
        lifts = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
        rewards = [250, 350, 500, 750]
        inc = st.toggle("Include cost savings", value=True)
        col = "Total value" if inc else "Program profit"
        grid = [[run_model(Inputs(**{**asdict(p), "lift": L, "avg_reward": R}))[col].sum() / 1e6
                 for R in rewards] for L in lifts]
        hm = go.Figure(go.Heatmap(
            z=grid, x=[f"${r} reward" for r in rewards], y=[f"+{L*100:.0f} pts" for L in lifts],
            colorscale=[[0, "#F3B6BD"], [0.5, "#E7EDF3"], [1, "#A8DDBB"]], zmid=0,
            text=[[f"{v:,.1f}" for v in row] for row in grid], texttemplate="%{text}",
            textfont=dict(size=14, color="#d0e4ff")))
        hm.update_layout(
            title=f"<b>Five-year {col.lower()} after build ($M)</b>",
            title_font=dict(size=21, color="#FFD520"),
            height=430, yaxis_title="Repeat-rate lift",
            paper_bgcolor="#04152D", plot_bgcolor="#0a2444",
            font=dict(color="#d0e4ff", size=16),
        )
        st.plotly_chart(hm, alt="Sensitivity heatmap")
        st.caption("Compare with deck slide 24 (program profit only).")

    # ---------------- Table ----------------
    with tabs[6]:
        sel_t = st.session_state.get("selected_year_t")
        _year_banner(df, sel_t)
        show = df.drop(columns=["t"]).set_index("Year")
        money = [c_ for c_ in show.columns if c_ not in
                 ("Enrolled owners", "Incremental repeat cars", "Scans", "Verified trade-ins",
                  "Service visits")]
        out = show.copy()
        out[money] = (out[money] / 1e6).round(2)
        out[[c_ for c_ in show.columns if c_ not in money]] = \
            out[[c_ for c_ in show.columns if c_ not in money]].round(0)
        st.dataframe(out.T, width="stretch")
        st.caption("Money rows in $M; counts in units.")
        st.download_button("Download table (CSV)", out.to_csv().encode(),
                           "mygarage_model_output.csv", "text/csv")
        st.download_button("Download current inputs (CSV)",
                           pd.Series(asdict(p)).to_csv().encode(),
                           "mygarage_inputs.csv", "text/csv")

    # ---------------- Sources ----------------
    with tabs[7]:
        st.markdown("#### CarMax facts used as defaults")
        st.table(pd.DataFrame(CARMAX_FACTS, index=["Value", "Source"]).T)
        st.markdown(
            "#### Method\n"
            "- **Enrolled owners** = recent owners × enroll rate (aging out over the ownership "
            "cycle) + each year's new buyers × enroll rate, less annual attrition; Year 1 scaled "
            "by the rollout ramp. The 'Team deck' preset (10% of recent owners, 90% ramp, 20% "
            "attrition) reproduces the deck's revenue line within about 5%.\n"
            "- **Incremental repeat cars** = enrolled owners × lift ÷ cycle years. Revenue = "
            "those cars × (price + EPP) + service visits × revenue per visit.\n"
            "- **Rewards** are paid on *all* repeat purchases by enrolled owners (baseline and "
            "incremental), so cannibalization is counted.\n"
            "- **Cost savings** are costs CarMax already incurs that MyGarage reduces; they are "
            "kept separate from program profit so the board can see both views.\n"
            "- **ROI** = five-year value after the build ÷ build cost (same definition as the "
            "deck). CAF finance income on extra sales is not counted, so results are conservative "
            "on that side.\n"
            "- Reconditioning cost per car, care-contact cost and goodwill per scan are not "
            "disclosed by CarMax; they are team estimates and should be presented as such."
        )


if __name__ == "__main__":
    main()
