import json
from typing import List, Dict, Any

import streamlit as st
import google.generativeai as genai

# ---------------------------
# API Key (⚠️ hard-coded — don’t commit this!)
# ---------------------------
API_KEY = "AIzaSyAikRV-gvDqSHDJY05GiL7x7GEITgK7FwI"
genai.configure(api_key=API_KEY)

# ---------------------------
# Streamlit page setup
# ---------------------------
st.set_page_config(page_title="GoodRx Demo – Gemini Flash", page_icon="💛", layout="centered")

st.markdown("# 💛 GoodRx – AI Subscription Coach (Gemini Flash)")
st.caption("Demo only. Not medical advice. Don’t enter PHI/PII.")

# ---------------------------
# Demo catalog & pricing rules
# ---------------------------
CATALOG = {
    "plans": {
        "Diabetes Care": {
            "monthly_price": 29.0,
            "includes": [
                "Metformin refills",
                "Glucose monitor strips",
                "Telehealth check-in every 3 months"
            ],
            "description": "Subscription for diabetes maintenance medications and supplies."
        },
        "Heart Health": {
            "monthly_price": 25.0,
            "includes": [
                "ACE inhibitors (typical options)",
                "Digital BP monitor",
                "Priority refills"
            ],
            "description": "Subscription for blood pressure management."
        }
    },
    "bundle_rules": {
        "any_two_plans_discount_pct": 10.0
    },
    "demo_patient": {
        "current_spend": {
            "Metformin": 42.0,
            "ACE_inhibitor": 20.0
        }
    }
}

def bundle_price(plan_names: List[str]) -> float:
    base = sum(CATALOG["plans"][p]["monthly_price"] for p in plan_names)
    discount_pct = 0.0
    if len(plan_names) >= 2:
        discount_pct = CATALOG["bundle_rules"]["any_two_plans_discount_pct"]
    return round(base * (1 - discount_pct / 100.0), 2)

def savings_vs_current(selected_plans: List[str], current_spend_map: Dict[str, float]) -> Dict[str, Any]:
    current = 0.0
    if "Diabetes Care" in selected_plans:
        current += current_spend_map.get("Metformin", 0.0)
    if "Heart Health" in selected_plans:
        current += current_spend_map.get("ACE_inhibitor", 0.0)
    new_monthly = bundle_price(selected_plans)
    monthly_savings = round(max(current - new_monthly, 0.0), 2)
    annual_savings = round(monthly_savings * 12, 2)
    return {
        "current_monthly": round(current, 2),
        "new_monthly": new_monthly,
        "monthly_savings": monthly_savings,
        "annual_savings": annual_savings
    }

def infer_dynamic_context(user_text: str, history_text: str) -> Dict[str, Any]:
    text = (user_text + " " + history_text).lower()
    want_diabetes = ("diabetes" in text) or ("metformin" in text)
    want_heart = ("blood pressure" in text) or ("bp " in text) or ("ace" in text) or ("heart" in text)
    selected = []
    if want_diabetes:
        selected.append("Diabetes Care")
    if want_heart:
        selected.append("Heart Health")
    ctx = {"selected_plans": selected, "quotes": {}}
    if selected:
        ctx["quotes"]["selected_plans_quote"] = savings_vs_current(selected, CATALOG["demo_patient"]["current_spend"])
    if "bundle" in text or "both" in text or ("together" in text):
        both = ["Diabetes Care", "Heart Health"]
        ctx["quotes"]["bundle_quote"] = savings_vs_current(both, CATALOG["demo_patient"]["current_spend"])
        ctx["quotes"]["bundle_plans"] = both
    return ctx

# ---------------------------
# Gemini setup (Flash model only)
# ---------------------------
SYSTEM_PROMPT = """You are an AI subscription coach for a GoodRx-style experience.
GOALS:
1) Explain available medication subscription plans and bundles.
2) Use ONLY the provided JSON data for all numbers—never invent prices.
3) Be concise, friendly, and proactive. Offer bundles when relevant.
4) If costs are asked: show current spend → new subscription price → monthly & annual savings.
5) Safety: You are not a clinician. Do not give medical advice or treatment recommendations.
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
# Sidebar demo controls
# ---------------------------
st.sidebar.header("Demo Controls")

def preload_scripted():
    scripted = [
        ("user", "I need help managing my diabetes medications."),
        ("assistant", "I see you regularly refill Metformin. Many people in your situation save with our Diabetes Care Subscription; it includes Metformin refills, glucose monitor strips, and a telehealth check-in every 3 months."),
        ("user", "How much would that cost me?"),
        ("assistant", "You currently spend about $42/month. With the subscription, your cost drops to $29/month, and you get the telehealth consult included. Over a year, that’s about $156 saved."),
        ("user", "Is there a similar plan for blood pressure?"),
        ("assistant", "Yes. Our Heart Health Plan covers ACE inhibitors, a digital BP monitor, and priority refills for $25/month. Would you like to see both bundled together at a discounted rate?"),
        ("user", "Yes, show me."),
        ("assistant", "Bundling Diabetes Care + Heart Health together saves an additional 10%, bringing your total monthly cost to $49. This bundle has been popular with people managing multiple conditions.")
    ]
    st.session_state.chat = model.start_chat(history=[])
    st.session_state.display_history = scripted

if st.sidebar.button("Load scripted demo"):
    preload_scripted()
    st.rerun()
if st.sidebar.button("Reset chat"):
    st.session_state.chat = model.start_chat(history=[])
    st.session_state.display_history = []

# ---------------------------
# Render history
# ---------------------------
for role, text in st.session_state.display_history:
    with st.chat_message("user" if role == "user" else "assistant"):
        st.markdown(text)

# ---------------------------
# Chat input
# ---------------------------
user_msg = st.chat_input("Type your message…")
if user_msg:
    st.session_state.display_history.append(("user", user_msg))
    with st.chat_message("user"):
        st.markdown(user_msg)

    ctx = infer_dynamic_context(user_msg, history_plain())
    payload = (
        "Use ONLY the following JSON data for pricing:\n\n"
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
    "<br><small>⚠️ Prototype demo only. Not medical advice. "
    "Consult a licensed clinician for personal medical questions.</small>",
    unsafe_allow_html=True
)
