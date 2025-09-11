import os
import io
import json
from typing import List, Dict, Any

import streamlit as st
import google.generativeai as genai
from streamlit_mic_recorder import mic_recorder
from gtts import gTTS

# =========================
# Config & API key
# =========================
st.set_page_config(page_title="GoodRx Demos — Chat + Voice", page_icon="💛", layout="centered")

# Prefer secrets; uncomment to hard-code (NOT recommended on GitHub/Cloud)
# API_KEY = "PASTE_YOUR_KEY_HERE"
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    st.error("No GOOGLE_API_KEY found. Add it in Streamlit Cloud Secrets or set it in your environment.")
    st.stop()

genai.configure(api_key=API_KEY)

# Always use Gemini 1.5 Flash
def make_model(system_prompt: str):
    return genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_prompt,
    )

# =========================
# Deterministic catalog & pricing (Chat demo)
# =========================
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
    "bundle_rules": {"any_two_plans_discount_pct": 10.0},
    "demo_patient": {
        "current_spend": {
            "Metformin": 42.0,       # USD/month
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
        ctx["quotes"]["selected_plans_quote"] = savings_vs_current(selected, CATALOG["demo_patient"]["current_spend"])
    if "bundle" in text or "both" in text or "together" in text:
        both = ["Diabetes Care", "Heart Health"]
        ctx["quotes"]["bundle_quote"] = savings_vs_current(both, CATALOG["demo_patient"]["current_spend"])
        ctx["quotes"]["bundle_plans"] = both
    return ctx

def history_to_text(display_history):
    return "\n".join(f"{r}: {t}" for r, t in display_history)

# =========================
# Prompts
# =========================
CHAT_SYSTEM_PROMPT = """You are an AI subscription coach for a GoodRx-style experience.

GOALS:
1) Explain available medication subscription plans and bundles.
2) Use ONLY the provided JSON (catalog + precomputed quotes) for all numbers — never invent prices.
3) Be concise, friendly, and proactive. Offer bundles when relevant.
4) If costs are asked: show current spend → new subscription price → monthly & annual savings.
5) You are not a clinician. Do not give medical advice or treatment recommendations.

OUTPUT:
- Short, clear, helpful replies grounded in the injected JSON.
"""

VOICE_SYSTEM_PROMPT = """You are the GoodRx Senior Voice Bot.
Follow this flow strictly unless the user asks to speak to a person:
1) Greeting + ID verification: ask for full name, date of birth, and phone number on file.
2) Offer help menu (user can say things naturally):
   1. Find the best price for my medicine
   2. Pharmacy didn’t accept my card
   3. Billing or membership
   4. App or account help
   5. Refills or deliveries
   6. GoodRx Care (telehealth) help
   7. General questions
   Or the user can say “Talk to a person.”
3) Branch handling:
   - Price Finder: ask medication name, strength, quantity, then present the lowest price and offer to text a coupon or read card numbers.
   - Pharmacy didn’t accept card: ask which pharmacy + medication; offer to text correct codes or connect to an agent.
   - Billing/Membership: explain Gold; offer keep/cancel/billing question; transfer to billing if cancel.
   - App/Account: e.g., forgot password → offer SMS reset link to phone on file.
   - Delivery/Refill: ask medication; give shipping status (simulate) + offer to text tracking link.
   - GoodRx Care: ask appointment date; connect to care support.
   - General questions: provide brief info.
4) Escalation: if user asks to “talk to a person,” confirm and say you’re connecting them.

STYLE:
- Speak in short, friendly sentences optimized for audio.
- Confirm back critical details (name, DOB, last 4 of phone) before moving on.
- If you "text" or "connect" to someone, just state it as a confirmation (simulation).

IMPORTANT:
- Do not ask for or store PHI beyond what’s in this simulated flow.
- If the user asks for medical advice, politely decline and suggest contacting a clinician.
"""

# =========================
# UI Tabs
# =========================
st.title("💛 GoodRx Demos")
tab_chat, tab_voice = st.tabs(["💬 Chat — Subscription Coach", "🎧 Voice — Senior Support Bot"])

# =========================
# TAB 1 — Chat demo
# =========================
with tab_chat:
    st.write("Ask about diabetes or blood pressure plans, prices, and bundles. Numbers are deterministic from the demo catalog.")
    # Sidebar-like cheat sheet
    st.markdown("> **Pricing (demo):** Diabetes Care $29/mo • Heart Health $25/mo • Bundle = 10% off combined\n\n"
                "> **Demo current spend:** Metformin $42/mo • ACE inhibitor $20/mo")

    if "chat_model" not in st.session_state:
        st.session_state.chat_model = make_model(CHAT_SYSTEM_PROMPT)
    if "chat_session" not in st.session_state:
        st.session_state.chat_session = st.session_state.chat_model.start_chat(history=[])
    if "chat_display" not in st.session_state:
        st.session_state.chat_display = []

    # Render history
    for role, text in st.session_state.chat_display:
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(text)

    # Scripted conversation loader
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Load scripted demo"):
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
            st.session_state.chat_session = st.session_state.chat_model.start_chat(history=[])
            st.session_state.chat_display = scripted
            st.rerun()
    with col2:
        if st.button("Reset chat"):
            st.session_state.chat_session = st.session_state.chat_model.start_chat(history=[])
            st.session_state.chat_display = []
            st.rerun()

    # Chat input
    chat_user = st.chat_input("Type your message…")
    if chat_user:
        st.session_state.chat_display.append(("user", chat_user))
        with st.chat_message("user"):
            st.markdown(chat_user)

        dynamic_ctx = infer_dynamic_context(chat_user, history_to_text(st.session_state.chat_display))
        payload = (
            "Use ONLY the following JSON data for pricing:\n\n"
            "CATALOG_JSON:\n" + json.dumps(CATALOG, indent=2) +
            "\n\nCONTEXT_JSON:\n" + json.dumps(dynamic_ctx, indent=2) +
            "\n\nUSER_MESSAGE:\n" + chat_user
        )

        try:
            resp = st.session_state.chat_session.send_message(payload)
            ai_text = resp.text or "(No response)"
        except Exception as e:
            ai_text = f"Error calling Gemini: {e}"

        st.session_state.chat_display.append(("assistant", ai_text))
        with st.chat_message("assistant"):
            st.markdown(ai_text)

    st.caption("⚠️ Demo only. Not medical advice.")

# =========================
# TAB 2 — Voice demo (talks back)
# =========================
with tab_voice:
    st.write("Speak to the Senior Voice Bot. It will verify identity, present a menu, branch to common tasks, and **talk back**.")
    if "voice_model" not in st.session_state:
        st.session_state.voice_model = make_model(VOICE_SYSTEM_PROMPT)
    if "voice_session" not in st.session_state:
        st.session_state.voice_session = st.session_state.voice_model.start_chat(history=[])
    if "voice_display" not in st.session_state:
        st.session_state.voice_display = []  # (role, text)

    # Controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Start over (Voice)"):
            st.session_state.voice_session = st.session_state.voice_model.start_chat(history=[])
            st.session_state.voice_display = []
            st.rerun()
    with col2:
        st.info("Say anything like: ‘Hi’, ‘Find the best price’, ‘Pharmacy didn’t accept my card’, ‘I forgot my password’, ‘Talk to a person’…")

    # Render history
    for role, text in st.session_state.voice_display:
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(text)

    # --- Voice input ---
    st.subheader("🎤 Talk")
    st.caption("Click to record, then click again to stop. Your audio is sent to Gemini for transcription + reply.")
    audio = mic_recorder(
        start_prompt="🎤 Start recording",
        stop_prompt="⬛ Stop",
        key="mic_voice",
        format="wav",
        just_once=False,
    )

    if audio:
        audio_bytes = audio.get("bytes")
        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")

            # Provide a compact reminder of allowed actions/flow so Gemini stays on script
            guidance = (
                "System reminder: Follow the Senior Voice Bot flow (verify identity, then present the 7-option menu, "
                "then branch accordingly; allow escalation). Keep replies short for audio. If you text or connect, "
                "state it as a confirmation (simulation)."
            )

            try:
                resp = st.session_state.voice_session.send_message(
                    [
                        guidance,
                        {"mime_type": "audio/wav", "data": audio_bytes},
                    ]
                )
                ai_text = resp.text or "(No response)"
            except Exception as e:
                ai_text = f"Error calling Gemini with audio: {e}"

            st.session_state.voice_display.append(("assistant", ai_text))
            with st.chat_message("assistant"):
                st.markdown(ai_text)

            # TTS — speak the bot's reply
            try:
                tts = gTTS(text=ai_text, lang="en")
                buf = io.BytesIO()
                tts.write_to_fp(buf)
                buf.seek(0)
                st.audio(buf, format="audio/mp3")
            except Exception as e:
                st.warning(f"TTS error: {e}")

    # --- Text input fallback (voice tab) ---
    st.subheader("💬 Or type")
    voice_text = st.chat_input("Type here if you prefer…")
    if voice_text:
        st.session_state.voice_display.append(("user", voice_text))
        with st.chat_message("user"):
            st.markdown(voice_text)

        try:
            resp = st.session_state.voice_session.send_message(voice_text)
            ai_text = resp.text or "(No response)"
        except Exception as e:
            ai_text = f"Error calling Gemini: {e}"

        st.session_state.voice_display.append(("assistant", ai_text))
        with st.chat_message("assistant"):
            st.markdown(ai_text)

        # TTS again
        try:
            tts = gTTS(text=ai_text, lang="en")
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            st.audio(buf, format="audio/mp3")
        except Exception as e:
            st.warning(f"TTS error: {e}")

    st.caption("☎️ This is a simulation. We don’t actually place calls or send SMS; we just confirm actions for the demo.")
