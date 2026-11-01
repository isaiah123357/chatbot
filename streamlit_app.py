"""ASRS Bot Pro: AI grant-writing assistant for Advance Student Resource Systems."""
import base64
import hmac
import io
import os
from datetime import date, datetime

import anthropic
import pandas as pd
import streamlit as st

from knowledge import PROGRAMS, SYSTEM_PROMPT, TEMPLATES

MODEL = "claude-sonnet-5-5"
MAX_HISTORY = 20          # messages sent to the AI per turn (keeps it fast)
TRACKER_FILE = "grant_tracker.json"
STATUSES = ["Researching", "Drafting", "Submitted", "Awarded", "Declined"]

st.set_page_config(page_title="ASRS Bot Pro", page_icon="🟠", layout="wide")

# ─── STYLE (light-touch CSS so pages stay fast) ─────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=DM+Serif+Display&display=swap');
html, body, [class*="css"], .stMarkdown, .stButton button { font-family: 'DM Sans', sans-serif; }
h1, h2, h3 { font-family: 'DM Serif Display', serif !important; font-weight: 400 !important; }
.block-container { padding-top: 2rem; max-width: 1100px; }
.asrs-hero { background: linear-gradient(120deg, #d62828 0%, #e85d04 55%, #faa307 100%);
  border-radius: 16px; padding: 22px 26px; margin-bottom: 18px; color: #fff; }
.asrs-hero h1 { color: #fff !important; margin: 0; font-size: 2rem; }
.asrs-hero p { margin: 4px 0 0; opacity: .92; }
.asrs-tag { display: inline-block; font-size: .72rem; padding: 2px 9px; border-radius: 999px;
  background: rgba(232,93,4,.18); color: #f48c06; font-weight: 500; }
.asrs-muted { color: #b5b5b5; font-size: .9rem; }
[data-testid="stMetricValue"] { color: #f48c06; }
[data-testid="stChatMessage"] { border-radius: 14px; }
.stButton button { border-radius: 10px; }
</style>
""",
    unsafe_allow_html=True,
)


# ─── HELPERS ────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


def hero(title, subtitle):
    st.markdown(f'<div class="asrs-hero"><h1>{title}</h1><p>{subtitle}</p></div>',
                unsafe_allow_html=True)


def go_chat(prompt):
    """Send a prompt to the chat page and switch to it."""
    st.session_state.pending_prompt = prompt
    st.switch_page(PAGES["chat"])


def default_grants():
    return pd.DataFrame([
        {"Funder": "CNYCF Black Equity & Excellence", "Grant": "2023-24 DSR + E-Gaming",
         "Amount": 9100, "Deadline": date(2024, 4, 29), "Status": "Awarded",
         "Notes": "Award letter 2024-10-15"},
        {"Funder": "CNYCF Black Equity & Excellence", "Grant": "2025-26 Multi-program initiative",
         "Amount": 12710, "Deadline": date(2025, 6, 27), "Status": "Submitted",
         "Notes": "Total initiative $15,715; ASRS self-funds $3,005"},
    ])


def load_grants():
    if os.path.exists(TRACKER_FILE):
        try:
            df = pd.read_json(TRACKER_FILE, orient="records")
            df["Deadline"] = pd.to_datetime(df["Deadline"], errors="coerce").dt.date
            return df
        except Exception:
            pass
    return default_grants()


def save_grants(df):
    out = df.copy()
    out["Deadline"] = out["Deadline"].astype(str)
    out.to_json(TRACKER_FILE, orient="records", indent=2)


def grants():
    if "grants" not in st.session_state:
        st.session_state.grants = load_grants()
    return st.session_state.grants


def file_to_blocks(f):
    """Turn an uploaded file into content blocks the AI can read."""
    data = f.getvalue()
    name = f.name.lower()
    if name.endswith(".pdf"):
        return [{"type": "document", "title": f.name,
                 "source": {"type": "base64", "media_type": "application/pdf",
                            "data": base64.b64encode(data).decode()}}]
    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        media = f.type or "image/png"
        return [{"type": "image",
                 "source": {"type": "base64", "media_type": media,
                            "data": base64.b64encode(data).decode()}}]
    if name.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return [{"type": "text", "text": f"[Attached Word document: {f.name}]\n{text}"}]
    if name.endswith(".xlsx"):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        text = "\n\n".join(f"Sheet {k}:\n{v.to_csv(index=False)}" for k, v in sheets.items())
        return [{"type": "text", "text": f"[Attached spreadsheet: {f.name}]\n{text}"}]
    text = data.decode("utf-8", errors="ignore")
    return [{"type": "text", "text": f"[Attached file: {f.name}]\n{text}"}]


def stream_reply(messages):
    """Stream the AI reply as text chunks."""
    system = [{"type": "text", "text": SYSTEM_PROMPT,
               "cache_control": {"type": "ephemeral"}}]  # prompt caching = faster replies
    if st.session_state.get("language") == "Español":
        system.append({"type": "text", "text": "Respond in Spanish (español) unless asked otherwise."})
    kwargs = dict(model=MODEL, max_tokens=8000, system=system, messages=messages)
    if st.session_state.get("web_search"):
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    with get_client().messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            yield text


def api_history():
    msgs = [{"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[-MAX_HISTORY:]]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


# ─── LOGIN ──────────────────────────────────────────────────────────
def login_screen():
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.markdown("<br><br>", unsafe_allow_html=True)
        hero("ASRS Bot Pro", "AI-Powered Grant Assistant · Advance Student Resource Systems")
        with st.form("login"):
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                if hmac.compare_digest(pw, str(st.secrets.get("APP_PASSWORD", "DSR"))):
                    st.session_state.authed = True
                    st.rerun()
                else:
                    st.error("Incorrect password")


# ─── PAGES ──────────────────────────────────────────────────────────
def dashboard_page():
    hero("Welcome back", "Here's where ASRS stands today.")
    df = grants()
    awarded = df.loc[df["Status"] == "Awarded", "Amount"].sum()
    pipeline = df.loc[df["Status"].isin(["Researching", "Drafting", "Submitted"]), "Amount"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Students impacted", "5,050+")
    c2.metric("Active programs", len(PROGRAMS))
    c3.metric("In pipeline", f"${pipeline:,.0f}")
    c4.metric("Awarded", f"${awarded:,.0f}")

    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.subheader("Quick actions")
        a, b = st.columns(2)
        if a.button("✍️ Draft a proposal", width="stretch"):
            go_chat(TEMPLATES[0]["prompt"])
        if b.button("🔎 Find new grants", width="stretch"):
            st.session_state.web_search = True
            go_chat("Search the web for current grant opportunities that fit ASRS's mission "
                    "(youth STEM, BIPOC students, Syracuse NY and Virginia). List funder, amount, "
                    "deadline, eligibility, and why ASRS fits.")
        if a.button("📋 Executive summary", width="stretch"):
            go_chat(TEMPLATES[1]["prompt"])
        if b.button("💌 Thank-you letter", width="stretch"):
            go_chat(TEMPLATES[7]["prompt"])
    with right:
        st.subheader("Upcoming deadlines")
        today = date.today()
        open_ = df[df["Status"].isin(["Researching", "Drafting"]) & df["Deadline"].notna()]
        upcoming = open_[open_["Deadline"] >= today].sort_values("Deadline")
        if upcoming.empty:
            st.markdown('<p class="asrs-muted">No open deadlines. Add grants in the Grant Tracker.</p>',
                        unsafe_allow_html=True)
        for _, r in upcoming.head(5).iterrows():
            days = (r["Deadline"] - today).days
            msg = f"**{r['Funder']}** · {r['Grant']} · due {r['Deadline']:%b %d} ({days} days)"
            st.warning(msg) if days <= 14 else st.info(msg)


def chat_page():
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if not st.session_state.messages:
        hero("ASRS Bot Pro", "Ask for a proposal, a letter, a budget, or anything about ASRS.")
        cols = st.columns(3)
        starters = [TEMPLATES[1], TEMPLATES[5], TEMPLATES[9]]
        for col, t in zip(cols, starters):
            if col.button(f"{t['icon']} {t['name']}", width="stretch"):
                st.session_state.pending_prompt = t["prompt"]
                st.rerun()

    for m in st.session_state.messages:
        with st.chat_message(m["role"], avatar="🟠" if m["role"] == "assistant" else "👤"):
            st.markdown(m["display"])

    submitted = st.chat_input(
        "Message ASRS Bot Pro… (attach PDFs, Word, Excel, images)",
        accept_file="multiple",
        file_type=["pdf", "docx", "xlsx", "txt", "csv", "md", "png", "jpg", "jpeg", "webp"],
    )

    text, files = None, []
    if submitted:
        text, files = submitted.text, submitted.files
    elif st.session_state.get("pending_prompt"):
        text = st.session_state.pop("pending_prompt")

    if not (text or files):
        return

    text = text or "Please review the attached file(s)."
    content = []
    for f in files:
        try:
            content += file_to_blocks(f)
        except Exception as e:
            st.toast(f"Couldn't read {f.name}: {e}")
    content.append({"type": "text", "text": text})
    display = text + ("".join(f"\n\n📎 *{f.name}*" for f in files))

    st.session_state.messages.append({"role": "user", "content": content, "display": display})
    with st.chat_message("user", avatar="👤"):
        st.markdown(display)

    with st.chat_message("assistant", avatar="🟠"):
        try:
            reply = st.write_stream(stream_reply(api_history()))
        except anthropic.AuthenticationError:
            reply = "⚠️ The API key isn't valid. Check ANTHROPIC_API_KEY in the app's Secrets."
            st.error(reply)
        except Exception as e:
            reply = f"⚠️ Something went wrong: {e}"
            st.error(reply)
    if isinstance(reply, list):
        reply = "".join(str(x) for x in reply)
    if not reply or reply.startswith("⚠️"):
        st.session_state.messages.pop()  # drop the failed turn so the next try starts clean
        return
    st.session_state.messages.append({"role": "assistant", "content": reply, "display": reply})

    if reply:
        st.download_button("⬇️ Download reply", reply, file_name=f"asrs_{datetime.now():%Y%m%d_%H%M}.md",
                           key=f"dl_{len(st.session_state.messages)}")


def templates_page():
    hero("Templates", "One click to a first draft built on ASRS's real data.")
    tags = ["All"] + sorted({t["tag"] for t in TEMPLATES})
    pick = st.segmented_control("Filter", tags, default="All", label_visibility="collapsed")
    items = [t for t in TEMPLATES if pick in (None, "All") or t["tag"] == pick]
    cols = st.columns(2, gap="medium")
    for i, t in enumerate(items):
        with cols[i % 2].container(border=True):
            st.markdown(f"### {t['icon']} {t['name']}")
            st.markdown(f'<span class="asrs-tag">{t["tag"]}</span>', unsafe_allow_html=True)
            st.markdown(f'<p class="asrs-muted">{t["desc"]}</p>', unsafe_allow_html=True)
            if st.button("Use template", key=f"tpl_{t['name']}", type="primary"):
                go_chat(t["prompt"])


def tracker_page():
    hero("Grant Tracker", "Every opportunity from research to award.")
    df = grants()

    counts = df["Status"].value_counts()
    cols = st.columns(len(STATUSES))
    for col, s in zip(cols, STATUSES):
        col.metric(s, int(counts.get(s, 0)))

    with st.form("tracker"):
        edited = st.data_editor(
            df, num_rows="dynamic", width="stretch", hide_index=True,
            column_config={
                "Funder": st.column_config.TextColumn(required=True, width="medium"),
                "Grant": st.column_config.TextColumn(width="medium"),
                "Amount": st.column_config.NumberColumn(format="$%d", min_value=0),
                "Deadline": st.column_config.DateColumn(format="MMM D, YYYY"),
                "Status": st.column_config.SelectboxColumn(options=STATUSES, required=True),
                "Notes": st.column_config.TextColumn(width="large"),
            },
        )
        if st.form_submit_button("💾 Save changes", type="primary"):
            st.session_state.grants = edited.reset_index(drop=True)
            save_grants(st.session_state.grants)
            st.toast("Tracker saved")
            st.rerun()

    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Export to CSV", df.to_csv(index=False), "asrs_grants.csv",
                       width="stretch")
    up = c2.file_uploader("Import CSV", type="csv", label_visibility="collapsed")
    if up is not None and st.session_state.get("last_import") != up.file_id:
        new = pd.read_csv(up)
        new["Deadline"] = pd.to_datetime(new.get("Deadline"), errors="coerce").dt.date
        st.session_state.grants = new
        st.session_state.last_import = up.file_id
        save_grants(new)
        st.rerun()
    st.caption("Tip: export a CSV backup now and then. Streamlit Cloud can reset saved files "
               "when the app restarts.")


def programs_page():
    hero("Programs", "Everything ASRS runs, and a quick way to write about it.")
    cols = st.columns(2, gap="medium")
    for i, p in enumerate(PROGRAMS):
        with cols[i % 2].container(border=True):
            st.markdown(f"### {p['icon']} {p['name']}")
            st.markdown(f'<span class="asrs-tag">Since {p["since"]}</span> '
                        f'<span class="asrs-tag">{p["students"]} students</span>',
                        unsafe_allow_html=True)
            st.markdown(f'<p class="asrs-muted">{p["desc"]}</p>', unsafe_allow_html=True)
            if st.button("Write a proposal for this", key=f"prog_{i}"):
                go_chat(f"Write a grant proposal focused on ASRS's {p['name']} program, using our real "
                        f"outcomes, budget figures, and partners.")


# ─── APP ────────────────────────────────────────────────────────────
if not st.session_state.get("authed"):
    login_screen()
    st.stop()

PAGES = {
    "dashboard": st.Page(dashboard_page, title="Dashboard", icon=":material/space_dashboard:", default=True),
    "chat": st.Page(chat_page, title="AI Chat", icon=":material/chat:"),
    "templates": st.Page(templates_page, title="Templates", icon=":material/description:"),
    "tracker": st.Page(tracker_page, title="Grant Tracker", icon=":material/table_chart:"),
    "programs": st.Page(programs_page, title="Programs", icon=":material/school:"),
}

with st.sidebar:
    st.markdown("## 🟠 ASRS Bot Pro")
    st.caption("AI-Powered Grant Assistant")

nav = st.navigation(list(PAGES.values()))

with st.sidebar:
    st.divider()
    st.selectbox("Language", ["English", "Español"], key="language")
    st.toggle("Web search", key="web_search", help="Let the AI look up current grants and funders.")
    if st.button("🆕 New chat", width="stretch"):
        st.session_state.messages = []
        st.switch_page(PAGES["chat"])
    if st.button("Log out", width="stretch"):
        st.session_state.clear()
        st.rerun()

nav.run()
