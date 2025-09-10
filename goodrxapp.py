import json
from typing import List, Dict, Any

import streamlit as st
import google.generativeai as genai
import os

# ---------------------------
# API Key (env var)
# ---------------------------
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    st.warning("Missing GOOGLE_API_KEY environment variable. Set it before running.")
genai.configure(api_key=API_KEY)

# ---------------------------
# Streamlit page setup
# ---------------------------
st.set_page_config(
    page_title="ProjectEase – Predictive Task Coach (TechCo Demo)",
    page_icon="🧩",
    layout="centered",
)

st.markdown("# 🧩 ProjectEase – Predictive Task Coach")
st.caption(
    "TechCo x Ciklum proposal demo. Simplicity-first, predictive insights. Not connected to production data."
)

# ---------------------------
# Demo catalog, KPIs & pricing rules (demo-only numbers)
# ---------------------------
CATALOG: Dict[str, Any] = {
    "features": {
        "Predictive Scheduling": {
            "monthly_price_per_user": 3.0,
            "includes": [
                "Auto-prioritize tasks by likelihood of delay",
                "Suggest next-best actions",
                "Lightweight inline nudges inside ProjectEase"
            ],
            "description": "Predict late tasks early and propose micro-adjustments to keep teams on track."
        },
        "Risk Radar": {
            "monthly_price_per_user": 2.0,
            "includes": [
                "Risk scoring for tasks & epics",
                "Explainable drivers (owner load, scope creep, blockers)",
                "Daily digest with top 5 risks"
            ],
            "description": "Surface delivery risks with simple, explainable scores."
        },
        "Smart Summaries": {
            "monthly_price_per_user": 1.5,
            "includes": [
                "One-click standup & status summaries",
                "Stakeholder-ready weekly updates",
                "Action items extracted from comments"
            ],
            "description": "Generate crisp updates without changing the current workflow."
        }
    },
    "bundle_rules": {
        "any_two_features_discount_pct": 10.0,
        "all_three_features_discount_pct": 15.0
    },
    # Demo customer baselines and ROI knobs (assumptions for the calculator)
    "demo_customer": {
        "seats": 100,                   # active PM/engineer seats in ProjectEase
        "hourly_blended_rate": 60.0,    # $/hour for time-savings math
        "current_kpis": {
            "on_time_rate": 0.72,       # fraction of tasks delivered on time
            "avg_status_prep_hours_per_mgr_per_week": 2.0,
            "avg_delay_cost_per_task": 120.0,  # spillover/coordination cost proxy
        },
        # Conservative impact assumptions per feature (can be tuned live)
        "impacts": {
            "Predictive Scheduling": {
                "on_time_rate_uplift_pct": 6.0,
                "time_saved_minutes_per_user_per_week": 12
            },
            "Risk Radar": {
                "on_time_rate_uplift_pct": 4.0,
                "delay_cost_reduction_pct": 8.0
            },
            "Smart Summaries": {
                "time_saved_minutes_per_mgr_per_week": 60
            }
        }
    }
}

# ---------------------------
# Pricing & ROI helpers (uses ONLY CATALOG data)
# ---------------------------

def bundle_price_per_user(feature_names: List[str]) -> float:
    base = sum(CATALOG["features"][f]["monthly_price_per_user"] for f in feature_names)
    discount_pct = 0.0
    if len(feature_names) == 2:
        discount_pct = CATALOG["bundle_rules"]["any_two_features_discount_pct"]
    elif len(feature_names) >= 3:
        discount_pct = CATALOG["bundle_rules"]["all_three_features_discount_pct"]
    return round(base * (1 - discount_pct / 100.0), 2)


def monthly_cost(feature_names: List[str], seats: int) -> float:
    return round(bundle_price_per_user(feature_names) * seats, 2)


def estimate_roi(selected: List[str], demo: Dict[str, Any]) -> Dict[str, Any]:
    seats = demo["seats"]
    rate = demo["hourly_blended_rate"]
    kpis = demo["current_kpis"]
    impacts = demo["impacts"]

    # Baselines
    on_time = kpis["on_time_rate"]
    status_hours = kpis["avg_status_prep_hours_per_mgr_per_week"]
    delay_cost = kpis["avg_delay_cost_per_task"]

    # Derived impacts
    uplift = 0.0
    delay_reduction_pct = 0.0
    team_time_saved_hours_per_week = 0.0
    mgr_time_saved_hours_per_week = 0.0

    if "Predictive Scheduling" in selected:
        uplift += impacts["Predictive Scheduling"]["on_time_rate_uplift_pct"]
        team_time_saved_hours_per_week += seats * impacts["Predictive Scheduling"]["time_saved_minutes_per_user_per_week"] / 60.0

    if "Risk Radar" in selected:
        uplift += impacts["Risk Radar"]["on_time_rate_uplift_pct"]
        delay_reduction_pct += impacts["Risk Radar"]["delay_cost_reduction_pct"]

    if "Smart Summaries" in selected:
        mgr_time_saved_hours_per_week += impacts["Smart Summaries"]["time_saved_minutes_per_mgr_per_week"] / 60.0

    # Compose outcomes (conservative compounding avoided; use additive for demo clarity)
    new_on_time_rate = min(on_time + uplift / 100.0, 0.99)

    # Monetary benefits (very simplified demo logic)
    weekly_savings = team_time_saved_hours_per_week * rate + mgr_time_saved_hours_per_week * rate
    monthly_savings = round(weekly_savings * 4.33, 2)

    # Delay cost reduction proxy
    delay_cost_savings = round(delay_cost * (delay_reduction_pct / 100.0) * 10, 2)  # assume 10 at-risk tasks/mo
    monthly_savings += delay_cost_savings

    # Costs
    cost_monthly = monthly_cost(selected, seats)

    # ROI
    net_monthly = round(max(monthly_savings - cost_monthly, 0.0), 2)
    payback_months = None
    if cost_monthly > 0 and monthly_savings > 0:
        payback_months = round(cost_monthly / monthly_savings, 2)

    return {
        "seats": seats,
        "price_per_user": bundle_price_per_user(selected) if selected else 0.0,
        "monthly_cost": cost_monthly,
        "current_on_time_rate": round(on_time, 2),
        "projected_on_time_rate": round(new_on_time_rate, 2),
        "monthly_savings": round(monthly_savings, 2),
        "net_monthly_benefit": net_monthly,
        "payback_months": payback_months,
    }


# ---------------------------
# Dynamic context from user text (keyword-only; no PII)
# ---------------------------

def infer_dynamic_context(user_text: str, history_text: str) -> Dict[str, Any]:
    text = (user_text + " " + history_text).lower()
    want_predict = any(k in text for k in ["predict", "late", "schedule", "priorit", "forecast"]) 
    want_risk = any(k in text for k in ["risk", "blocker", "slip", "delay"])
    want_summary = any(k in text for k in ["summary", "summaries", "standup", "status", "update"]) 

    selected: List[str] = []
    if want_predict:
        selected.append("Predictive Scheduling")
    if want_risk:
        selected.append("Risk Radar")
    if want_summary:
        selected.append("Smart Summaries")

    ctx: Dict[str, Any] = {"selected_features": selected, "quotes": {}}
    if selected:
        ctx["quotes"]["selected_features_quote"] = estimate_roi(selected, CATALOG["demo_customer"]) 
    if any(x in text for x in ["bundle", "both", "all three", "together"]):
        all_three = ["Predictive Scheduling", "Risk Radar", "Smart Summaries"]
        ctx["quotes"]["bundle_quote"] = estimate_roi(all_three, CATALOG["demo_customer"]) 
        ctx["quotes"]["bundle_features"] = all_three
    return ctx


# ---------------------------
# Gemini setup (Flash model only)
# ---------------------------
SYSTEM_PROMPT = """You are an AI coach inside ProjectEase (TechCo). Your job is to make delivery smoother without complexity.
GOALS:
1) Explain available predictive features and simple bundles.
2) Use ONLY the provided JSON data for all prices, seats, and KPI effects—never invent numbers.
3) Be concise, friendly, and proactive. Offer bundles when relevant.
4) If costs/ROI are asked: show price per user → monthly platform cost → estimated monthly savings → projected on‑time rate → payback.
5) Simplicity-first: avoid jargon, keep answers skimmable. Provide short bullet lists.
6) Safety & privacy: This is a demo. Don’t ask for or process PII. Don’t claim to act on real projects.
7) TechCo constraints: focus on lightweight ML, explainability, and low ops.
"""

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=SYSTEM_PROMPT,
)

# ---------------------------
# Chat state
# ---------------------------
if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])
if "display_history" not in st.session_state:
    st.session_state.display_history = []  # (role, text)


def history_plain() -> str:
    return "\n".join(f"{r}: {t}" for r, t in st.session_state.display_history)


# ---------------------------
# Sidebar demo controls (adjust demo assumptions safely)
# ---------------------------
with st.sidebar:
    st.header("Demo Controls")

    seats = st.number_input("Seats", min_value=10, max_value=5000, value=CATALOG["demo_customer"]["seats"], step=10)
    rate = st.number_input("Hourly blended rate ($)", min_value=10.0, max_value=500.0, value=CATALOG["demo_customer"]["hourly_blended_rate"], step=5.0)
    on_time_baseline = st.slider("Baseline on‑time rate", 0.3, 0.95, float(CATALOG["demo_customer"]["current_kpis"]["on_time_rate"]))

    if st.button("Apply demo changes"):
        CATALOG["demo_customer"]["seats"] = int(seats)
        CATALOG["demo_customer"]["hourly_blended_rate"] = float(rate)
        CATALOG["demo_customer"]["current_kpis"]["on_time_rate"] = float(on_time_baseline)
        st.toast("Demo parameters updated.")

    def preload_scripted():
        scripted = [
            ("user", "We keep discovering late tasks too late. Can you help us predict slips?"),
            ("assistant", "Predictive Scheduling flags likely delays early and suggests next actions. It’s lightweight and explainable inside ProjectEase."),
            ("user", "What does it cost for ~100 seats and what’s the ROI?"),
            ("assistant", "Price is per user per month from the JSON. I’ll show price, savings, and payback using the demo assumptions."),
            ("user", "We also want risk visibility for leadership."),
            ("assistant", "Adding Risk Radar gives risk scores and a daily digest. Want to see a bundle with Smart Summaries too?"),
            ("user", "Yes, show the bundle."),
            ("assistant", "Bundling all three applies a 15% discount. I’ll calculate cost, savings, and on‑time uplift.")
        ]
        st.session_state.chat = model.start_chat(history=[])
        st.session_state.display_history = scripted

    if st.button("Load scripted demo"):
        preload_scripted()
        st.experimental_rerun()

    if st.button("Reset chat"):
        st.session_state.chat = model.start_chat(history=[])
        st.session_state.display_history = []
        st.experimental_rerun()


# ---------------------------
# Render history
# ---------------------------
for role, text in st.session_state.display_history:
    with st.chat_message("user" if role == "user" else "assistant"):
        st.markdown(text)


# ---------------------------
# Chat input
# ---------------------------
user_msg = st.chat_input("Ask about features, pricing, or ROI…")
if user_msg:
    st.session_state.display_history.append(("user", user_msg))
    with st.chat_message("user"):
        st.markdown(user_msg)

    ctx = infer_dynamic_context(user_msg, history_plain())
    payload = (
        "Use ONLY the following JSON data for pricing & ROI. "
        "If quoting numbers, cite them as coming from CATALOG_JSON or CONTEXT_JSON.\n\n"
        "CATALOG_JSON:\n" + json.dumps(CATALOG, indent=2) +
        "\n\nCONTEXT_JSON:\n" + json.dumps(ctx, indent=2) +
        "\n\nUSER_MESSAGE:\n" + user_msg
    )

    try:
        response = st.session_state.chat.send_message(payload)
        ai_text = response.text or "(No response)"
    except Exception as e:
        ai_text = f"Error calling Gemini: {e}"

    st.session_state.display_history.append(("assistant", ai_text))
    with st.chat_message("assistant"):
        st.markdown(ai_text)


# ---------------------------
# Footer
# ---------------------------
st.markdown(
    """
    <br><small>
    Prototype for TechCo x Ciklum Proposal. Demo numbers only; not commitments. 
    Designed for a 6‑month Expo timeline, simplicity‑first, minimal ops.
    </small>
    """,
    unsafe_allow_html=True,
)
