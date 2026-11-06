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


def apply_preset():
    for k, v in PRESETS[st.session_state["preset"]].items():
        v = int(v) if k == "start_year" else float(v)
        st.session_state[k] = v
        st.session_state[f"_{k}"] = v * 100  # slider mirror for percentage inputs


def num(label, key, step, fmt="%.0f", help=None, minv=0.0):
    return st.number_input(label, key=key, step=step, format=fmt, help=help, min_value=minv)


def pct(label, key, maxv=100.0, step=1.0, help=None):
    v = st.slider(label, 0.0, maxv, step=step, help=help, key=f"_{key}", format="%.1f%%")
    st.session_state[key] = v / 100
    return v / 100


BRAND = "#053361"   # CarMax blue
ACCENT = "#FFD520"  # CarMax yellow
GREEN = "#2E8540"
GREY = "#8A94A6"


SHORT = {"Team deck base case": "Deck base", "Realistic (recommended)": "Realistic",
         "Conservative (stress test)": "Conservative", "Optimistic": "Optimistic"}
LIFT_OPTS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
REWARD_OPTS = [250, 350, 500, 750]
ENROLL_OPTS = [0.20, 0.30, 0.40, 0.50]


def _set(key, value):
    st.session_state[key] = float(value)
    st.session_state[f"_{key}"] = float(value) * 100


def on_scenario():
    label = st.session_state.get("btn_scenario")
    if label:
        st.session_state["preset"] = {v: k for k, v in SHORT.items()}[label]
        apply_preset()
        for k in ("btn_lift", "btn_reward", "btn_enroll"):
            st.session_state[k] = None


def on_quick(btn, key):
    v = st.session_state.get(btn)
    if v is not None:
        _set(key, v)


def demo_controls():
    """One-click buttons for the live demo (no dropdowns)."""
    with st.container(border=True):
        c1, c3 = st.columns(2)
        c2, c4 = st.columns(2)
        with c1:
            st.segmented_control("Scenario", list(SHORT.values()), key="btn_scenario",
                                 on_change=on_scenario)
        with c2:
            st.segmented_control("Repeat-rate lift", LIFT_OPTS, key="btn_lift",
                                 format_func=lambda x: f"+{x*100:.0f} pts",
                                 on_change=on_quick, args=("btn_lift", "lift"))
        with c3:
            st.segmented_control("Avg reward", REWARD_OPTS, key="btn_reward",
                                 format_func=lambda x: f"${x}",
                                 on_change=on_quick, args=("btn_reward", "avg_reward"))
        with c4:
            st.segmented_control("New-buyer enrollment", ENROLL_OPTS, key="btn_enroll",
                                 format_func=lambda x: f"{x:.0%}",
                                 on_change=on_quick, args=("btn_enroll", "new_enroll"))


def main():
    st.set_page_config(page_title="MyGarage Value Calculator", page_icon="🚗", layout="wide")

    if "preset" not in st.session_state:
        st.session_state["preset"] = "Realistic (recommended)"
        st.session_state["btn_scenario"] = "Realistic"
        apply_preset()

    # ---------------- Sidebar ----------------
    with st.sidebar:
        st.markdown("## MyGarage inputs")
        st.caption(f"Scenario: **{st.session_state['preset']}**. Pick scenarios with the "
                   "buttons on the main page; fine-tune any input below.")

        with st.expander("CarMax baseline (FY2026)", expanded=False):
            num("Retail used units / year", "retail_units", 1000.0)
            num("Average selling price ($)", "asp", 100.0)
            num("Used gross profit per car ($)", "gpu", 25.0)
            num("EPP revenue per car ($)", "epp_per_car", 25.0)
            num("Advertising spend ($)", "advertising", 1e6)

        with st.expander("Adoption", expanded=True):
            num("Recent owners eligible at launch", "recent_owners", 10000.0,
                help="CarMax buyers from FY2024-26 (~2.34M).")
            pct("Recent owners who enroll", "existing_enroll", 60.0)
            pct("New buyers who enroll at delivery", "new_enroll", 90.0)
            pct("Year-1 rollout ramp", "year1_ramp", 100.0, 5.0,
                help="Share of full adoption reached in Year 1 (pilot to national).")
            pct("Enrolled owners lost per year", "attrition", 50.0,
                help="Owners who sell the car elsewhere or stop using the app.")

        with st.expander("Repeat purchase & rewards", expanded=True):
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
            num("One-time build ($)", "build_cost", 250000.0)
            num("Fixed run cost / year ($)", "fixed_cost", 100000.0)

        with st.expander("Cost-savings levers", expanded=True):
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

    st.markdown(
        f"<h1 style='color:{BRAND};margin-bottom:0'>MyGarage by CarMax · Value Calculator</h1>"
        f"<p style='color:{GREY};margin-top:4px'>Scenario: <b>{st.session_state['preset']}</b>"
        f" (edited inputs apply on top). $ figures are pre-tax unless noted.</p>",
        unsafe_allow_html=True,
    )

    demo_controls()
    c = st.columns(5)
    c[0].metric("5-yr total value", m(tot5), f"{m(sav5)} from cost savings")
    c[1].metric("5-yr ROI on $%.0fM" % (p.build_cost / 1e6), f"{roi_tot:,.0%}",
                f"{roi_prog:,.0%} without savings", delta_color="off")
    c[2].metric("Payback", payback_year(df["Cumulative total value"], df),
                f"program only: {payback_year(df['Cumulative program profit'], df)}",
                delta_color="off")
    c[3].metric("NPV @ %.0f%%" % (p.discount_rate * 100), m(npv_tot))
    c[4].metric("Yr-5 net earnings / EPS", m(ni_y5), f"+${eps_y5:.2f} per share")

    tabs = st.tabs(["Overview", "Assumptions in use", "Cost savings", "Profitability", "Customer experience",
                    "Sensitivity", "Year-by-year table", "Sources & method"])

    # ---------------- Overview ----------------
    with tabs[0]:
        left, right = st.columns([3, 2])
        with left:
            fig = go.Figure()
            fig.add_bar(x=df["Year"], y=df["Program profit"] / 1e6, name="Program profit",
                        marker_color=BRAND)
            fig.add_bar(x=df["Year"], y=df["Total cost savings"] / 1e6, name="Cost savings",
                        marker_color=ACCENT)
            fig.add_scatter(x=df["Year"], y=df["Cumulative total value"] / 1e6,
                            name="Cumulative value", mode="lines+markers",
                            line=dict(color=GREEN, width=3))
            fig.update_layout(barmode="relative", title="Annual value by source ($M)",
                              height=420, legend=dict(orientation="h", y=-0.15),
                              margin=dict(t=50, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        with right:
            st.markdown("#### What the board should hear")
            st.markdown(
                f"- MyGarage earns **{m(prog5)}** in program profit over five years after the "
                f"**{m(p.build_cost)}** build.\n"
                f"- The design also **saves {m(sav5)}** in costs CarMax already pays: "
                f"marketing, reconditioning, appraisal risk, customer care and warranty goodwill.\n"
                f"- Together: **{m(tot5)}**, a **{roi_tot:,.0%}** ROI and a "
                f"**{margin_tot:.1%}** margin on MyGarage revenue "
                f"(vs {margin_prog:.1%} on program profit alone).\n"
                f"- Break-even repeat lift: **{be_tot*100:.1f} pts** with savings"
                + (f", {be_prog*100:.1f} pts without" if be_prog is not None else "")
                + f". We assume {p.lift*100:.1f}."
                if be_tot is not None else "- Not profitable within the tested lift range."
            )
            sga_like = yrs[["Savings: marketing (new)", "Savings: marketing (owned channel)",
                            "Savings: customer care"]].iloc[-1].sum()
            st.info(f"By Year 5, MyGarage's SG&A-type savings ({m(sga_like)}/yr) equal "
                    f"**{sga_like / SGA_TARGET:.1%}** of CarMax's $200M SG&A savings target.")

    # ---------------- Assumptions ----------------
    with tabs[1]:
        st.markdown(f"Every variable behind the numbers above (preset: **{st.session_state['preset']}**). "
                    "✎ = changed from the preset during this demo.")
        g1, g2 = st.columns(2)
        for i, (title, keys) in enumerate(GROUPS):
            with (g1 if i % 2 == 0 else g2):
                st.markdown(f"**{title}**")
                st.dataframe(assumptions_table(p, st.session_state["preset"], keys),
                             hide_index=True, use_container_width=True)
        st.caption("Key formulas: extra repeat cars = enrolled owners × lift ÷ cycle years · "
                   "rewards paid on every repeat purchase by an enrolled owner · "
                   "ROI = 5-yr value after build ÷ build cost · CAF finance income not counted.")

    # ---------------- Cost savings ----------------
    with tabs[2]:
        scols = [c_ for c_ in df.columns if c_.startswith("Savings:")]
        totals = yrs[scols].sum().sort_values()
        a, b = st.columns([3, 2])
        with a:
            fig = go.Figure(go.Bar(
                x=totals.values / 1e6, y=[s.replace("Savings: ", "").capitalize() for s in totals.index],
                orientation="h", marker_color=ACCENT,
                text=[m(v) for v in totals.values], textposition="outside"))
            fig.update_layout(title="Five-year cost savings by lever ($M)", height=400,
                              margin=dict(t=50, l=10, r=40))
            st.plotly_chart(fig, use_container_width=True)
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
            use_container_width=True)
        st.caption("$M per year. Every lever is editable under 'Cost-savings levers'.")

    # ---------------- Profitability ----------------
    with tabs[3]:
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
            wf.update_layout(title="Five-year bridge: revenue to total value ($M)", height=450)
            st.plotly_chart(wf, use_container_width=True)
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
                        marker_color=[GREY, BRAND], text=[f"${clv0:,.0f}", f"${clv1:,.0f}"],
                        textposition="outside")
            fig.update_layout(title="Lifetime gross profit per CarMax buyer", height=380,
                              yaxis_title="$ per customer")
            st.plotly_chart(fig, use_container_width=True)
        with b:
            fig = go.Figure()
            fig.add_bar(x=yrs["Year"], y=yrs["Service visits"], name="Service visits captured",
                        marker_color=BRAND)
            fig.add_bar(x=yrs["Year"], y=yrs["Enrolled owners"] * p.contacts * p.contact_reduction,
                        name="Care calls avoided", marker_color=ACCENT)
            fig.update_layout(title="Touchpoints that keep owners connected", height=380,
                              barmode="group", legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, use_container_width=True)
        st.caption("CLV = gross profit per purchase (car + EPP + service over the ownership "
                   "cycle) plus discounted future repeat purchases, net of rewards. It answers "
                   "the 'extended customer life with us' point from the slide 12 notes.")

    # ---------------- Sensitivity ----------------
    with tabs[5]:
        lifts = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
        rewards = [250, 350, 500, 750]
        inc = st.toggle("Include cost savings", value=True)
        col = "Total value" if inc else "Program profit"
        grid = [[run_model(Inputs(**{**asdict(p), "lift": L, "avg_reward": R}))[col].sum() / 1e6
                 for R in rewards] for L in lifts]
        hm = go.Figure(go.Heatmap(
            z=grid, x=[f"${r} reward" for r in rewards], y=[f"+{L*100:.0f} pts" for L in lifts],
            colorscale=[[0, "#C0392B"], [0.5, "#F7F7F7"], [1, GREEN]], zmid=0,
            text=[[f"{v:,.1f}" for v in row] for row in grid], texttemplate="%{text}"))
        hm.update_layout(title=f"Five-year {col.lower()} after build ($M) by lift and reward",
                         height=430, yaxis_title="Repeat-rate lift")
        st.plotly_chart(hm, use_container_width=True)
        st.caption("Compare with deck slide 24 (program profit only).")

    # ---------------- Table ----------------
    with tabs[6]:
        show = df.drop(columns=["t"]).set_index("Year")
        money = [c_ for c_ in show.columns if c_ not in
                 ("Enrolled owners", "Incremental repeat cars", "Scans", "Verified trade-ins",
                  "Service visits")]
        out = show.copy()
        out[money] = (out[money] / 1e6).round(2)
        out[[c_ for c_ in show.columns if c_ not in money]] = \
            out[[c_ for c_ in show.columns if c_ not in money]].round(0)
        st.dataframe(out.T, use_container_width=True)
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
