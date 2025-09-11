import os
import json
from typing import List, Dict, Any

import streamlit as st
import google.generativeai as genai
from streamlit_mic_recorder import mic_recorder

# ---------------------------
# Config & API key
# ---------------------------
st.set_page_config(page_title="GoodRx Demo – Gemini Flash (Voice + Text)", page_icon="💛", layout="centered")

# Prefer secrets; uncomment the next line to hard-code (NOT recommended on GitHub/Cloud)
# API_KEY = "YOUR_HARDCODED_KEY_HERE"
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    st.error("No GOOGLE_API_KEY found. Set it in Streamlit Cloud Secrets or your environment.")
    st.stop()

genai.configure(api_key=API_KEY)

# ---------------------------
# Page header
# ---------------------------
st.markdown("# 💛 GoodRx – AI Subscription Coach")
st.caption("Talk or type. Demo only. Not medical advice. Don’t enter PHI/PII.")

# ---------------------------
# Deterministic catalog & pricing
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
            "Metformin": 42.0,        # USD/month
            "ACE_inhibitor": 20.0
        }
    }
}

def bundle_price(plan_names: List[str]) -> float:
    if not plan_names:
        return 0.0
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
    want_heart = ("blood pressure" in text) or (" bp " in text) or ("ace" in text) or ("heart" in text)

    selected = []
    if want_diabetes:
        selected.append("Diabetes Care")
    if want_heart:
        selected.append("Heart Health")

    ctx = {"selected_plans": selected, "quotes": {}}

    if selected:
        q = savings_vs_current(selected, CATALOG["demo_patient"]["current_spend"])
        ctx["quotes"]["selected_plans_quote"] = q

    # Bundle intent
    if "bundle" in text or "both" in text or "together" in text:
        both = ["Diabetes Care", "Heart Health"]
        q2 = savings_vs_current(both, CATALOG["demo_patient"]["current_spend"])
        ctx["quotes"]["bundle_quote"] = q2
        ctx["quotes"]["bundle_plans"] = both

    return ctx

# ---------------------------
# Gemini 1.5 Flash (direct)
# ---------------------------
SYSTEM_PROMPT = """You are an AI subscription coach for a GoodRx-style experience.

GOALS:
1) Help users understand relevant medication subscription plans and bundles.
2) Use ONLY the provided catalog and computed quotes for all numbers—do not invent prices.
3) Be concise, friendly, and proactive. Offer bundles when relevant.
4) When costs are asked: show current spend → new subscription price → monthly and annual savings.
5) Safety: You are not a clinician. Do not provide medical advice, diagnosis, or treatment.

RULES:
- Prices must come from the injected Catalog/Context JSON.
- If something isn’t in the data, say you don’t know.
- If Diabetes and Heart are both relevant, offer a two-plan bundle at 10% off combined price.
- Keep the tone practical and helpful.
"""

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=SYSTEM_PROMPT,
)

# ---------------------------
# Session state
# ---------------------------
if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])
if "display_history" not in st.session_state:
    st.session_state.display_history = []  # list[(role, text)]

def history_plain_text() -> str:
    return "\n".join(f"{r}: {t}" for r, t in st.session_state.display_history)

# ---------------------------
# Sidebar: helpers
# ---------------------------
st.sidebar.header("Demo Controls")

def preload_script():
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
    preload_script()
    st.rerun()

if st.sidebar.button("Reset chat"):
    st.session_state.chat = model.start_chat(history=[])
    st.session_state.display_history = []

st.sidebar.markdown("---")
st.sidebar.write("**Pricing (demo):**")
st.sidebar.write("- Diabetes Care: $29/mo")
st.sidebar.write("- Heart Health: $25/mo")
st.sidebar.write("- Bundle (2 plans): 10% off combined")
st.sidebar.write("- Demo current spend: Metformin $42/mo, ACE inhibitor $20/mo")

# ---------------------------
# Render history
# ---------------------------
for role, text in st.session_state.display_history:
    with st.chat_message("user" if role == "user" else "assistant"):
        st.markdown(text)

# ---------------------------
# Voice input (🎤)
# ---------------------------
st.subheader("🎤 Talk to the assistant")
st.caption("Click to record, then click again to stop. Your audio is sent to Gemini for transcription + reply.")

audio = mic_recorder(
    start_prompt="🎤 Start recording",
    stop_prompt="⬛ Stop",
    just_once=False,
    key="mic",
    format="wav"
)

if audio:
    # The component returns a dict with "bytes" (audio data as bytes)
    audio_bytes = audio.get("bytes")
    if audio_bytes:
        st.audio(audio_bytes, format="audio/wav")

        # Build deterministic context for this turn
        dynamic_ctx = infer_dynamic_context("", history_plain_text())

        # Compose the text part that instructs Gemini to use the JSON for numbers
        text_payload = (
            "You will answer using ONLY the following JSON data for prices and quotes.\n\n"
            "CATALOG_JSON:\n" + json.dumps(CATALOG, indent=2) + "\n\n"
            "CONTEXT_JSON:\n" + json.dumps(dynamic_ctx, indent=2) + "\n\n"
            "AUDIO_MESSAGE follows (user spoke). Transcribe and answer."
        )

        try:
            # Send as multimodal: text + audio
            response = st.session_state.chat.send_message(
                [
                    text_payload,
                    {"mime_type": "audio/wav", "data": audio_bytes},
                ]
            )
            ai_text = response.text or "(No response)"
        except Exception as e:
            ai_text = f"Error calling Gemini with audio: {e}"

        st.session_state.display_history.append(("assistant", ai_text))
        with st.chat_message("assistant"):
            st.markdown(ai_text)

# ---------------------------
# Text input (⌨️)
# ---------------------------
st.subheader("💬 Or type a message")
user_msg = st.chat_input("Type your message…")

if user_msg:
    st.session_state.display_history.append(("user", user_msg))
    with st.chat_message("user"):
        st.markdown(user_msg)

    dynamic_ctx = infer_dynamic_context(user_msg, history_plain_text())
    text_payload = (
        "Use ONLY the following JSON data for pricing:\n\n"
        "CATALOG_JSON:\n" + json.dumps(CATALOG, indent=2) +
        "\n\nCONTEXT_JSON:\n" + json.dumps(dynamic_ctx, indent=2) +
        "\n\nUSER_MESSAGE:\n" + user_msg
    )

    try:
        response = st.session_state.chat.send_message(text_payload)
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
    "<br><small>⚠️ Prototype for demonstration only and not medical advice. "
    "Consult a licensed clinician for personal medical questions.</small>",
    unsafe_allow_html=True
)
