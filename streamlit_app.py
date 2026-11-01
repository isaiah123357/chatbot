"""ASRS Bot Pro: grant development assistant for Advance Student Resource Systems, Inc."""
import base64
import hmac
import io
import os
from datetime import date, datetime

import anthropic
import pandas as pd
import streamlit as st

from knowledge import PROGRAMS, SYSTEM_PROMPT, TEMPLATES

ORG_NAME = "Advance Student Resource Systems, Inc."
APP_NAME = "ASRS Bot Pro"

MODELS = {
    "Sonnet 5.5 (recommended)": "claude-sonnet-5-5",
    "Opus 5.5 (highest quality)": "claude-opus-5-5",
    "Haiku 5.5 (fastest)": "claude-haiku-5-5",
    "Fable 5.1 (advanced)": "claude-fable-5-1",
}
WEB_TOOLS = [
    {"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 5},
]
MAX_HISTORY = 20          # messages sent per request; keeps responses fast
TRACKER_FILE = "grant_tracker.json"
STATUSES = ["Researching", "Drafting", "Submitted", "Awarded", "Declined"]
AI_AVATAR = ":material/auto_awesome:"
USER_AVATAR = ":material/person:"

st.set_page_config(page_title=APP_NAME, page_icon=":material/school:", layout="wide")

# ─── STYLE ──────────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stButton button, input, textarea {
  font-family: 'Inter', system-ui, sans-serif; }
h1, h2, h3 { font-weight: 600 !important; letter-spacing: -0.01em; }
.block-container { padding-top: 2.2rem; max-width: 1120px; }
.page-head { border-bottom: 1px solid #474747; padding-bottom: 14px; margin-bottom: 22px; }
.page-head .eyebrow { color: #f48c06; font-size: .75rem; font-weight: 600;
  letter-spacing: .12em; text-transform: uppercase; }
.page-head h1 { margin: 2px 0 2px; font-size: 1.85rem; padding: 0; }
.page-head p { color: #b8b8b8; margin: 0; font-size: .95rem; }
.brand { border-left: 3px solid #e85d04; padding-left: 10px; margin-bottom: 6px; }
.brand b { font-size: 1.05rem; } .brand span { display:block; color:#b8b8b8; font-size:.78rem; }
.tag { display:inline-block; font-size:.7rem; font-weight:500; padding:2px 8px; margin-right:4px;
  border-radius:4px; background:rgba(232,93,4,.14); color:#f48c06; letter-spacing:.02em; }
.muted { color:#b8b8b8; font-size:.9rem; line-height:1.5; }
.footer { color:#8f8f8f; font-size:.75rem; border-top:1px solid #474747; margin-top:36px; padding-top:12px; }
[data-testid="stMetric"] { background:#363636; border:1px solid #474747; border-radius:8px; padding:12px 16px; }
[data-testid="stMetricLabel"] p { color:#b8b8b8; font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; }
[data-testid="stMetricValue"] { font-weight:600; }
.stButton button, .stDownloadButton button { border-radius:6px; font-weight:500; }
.login-card { max-width: 420px; margin: 9vh auto 0; }
</style>
""",
    unsafe_allow_html=True,
)


# ─── HELPERS ────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


def page_header(eyebrow, title, subtitle):
    st.markdown(f'<div class="page-head"><div class="eyebrow">{eyebrow}</div>'
                f'<h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def footer():
    st.markdown(f'<div class="footer">© {date.today().year} {ORG_NAME} · For internal use. '
                'AI-generated drafts should be reviewed for accuracy before submission.</div>',
                unsafe_allow_html=True)


def go_chat(prompt):
    """Send a prompt to the assistant and open it."""
    st.session_state.pending_prompt = prompt
    st.switch_page(PAGES["chat"])


def default_grants():
    return pd.DataFrame([
        {"Funder": "CNYCF Black Equity & Excellence", "Grant": "2023-24 DriveSafe Robotics + E-Gaming",
         "Amount": 9100, "Deadline": date(2024, 4, 29), "Status": "Awarded",
         "Notes": "Award letter dated 2024-10-15"},
        {"Funder": "CNYCF Black Equity & Excellence", "Grant": "2025-26 Multi-program initiative",
         "Amount": 12710, "Deadline": date(2025, 6, 27), "Status": "Submitted",
         "Notes": "Total initiative $15,715; ASRS contribution $3,005"},
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
    """Convert an uploaded file into content the assistant can read."""
    data = f.getvalue()
    name = f.name.lower()
    if name.endswith(".pdf"):
        return [{"type": "document", "title": f.name,
                 "source": {"type": "base64", "media_type": "application/pdf",
                            "data": base64.b64encode(data).decode()}}]
    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return [{"type": "image",
                 "source": {"type": "base64", "media_type": f.type or "image/png",
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
    return [{"type": "text", "text": f"[Attached file: {f.name}]\n{data.decode('utf-8', errors='ignore')}"}]


def stream_reply(messages, status, sources):
    """Stream the assistant's reply. Fills `sources` with any web pages it cites."""
    system = [{"type": "text", "text": SYSTEM_PROMPT,
               "cache_control": {"type": "ephemeral"}}]  # prompt caching: faster, lower cost
    if st.session_state.get("language") == "Español":
        system.append({"type": "text", "text": "Respond in Spanish (español) unless asked otherwise."})
    web = st.session_state.get("web_search")
    if web:
        system.append({"type": "text", "text": (
            f"Today's date is {date.today():%B %d, %Y}. You can search the web and open pages. "
            "Use them for anything current: open grants, deadlines, funder priorities, news, and "
            "statistics. Prefer official funder and government sources, and state deadlines exactly "
            "as the source gives them.")})
    kwargs = dict(model=MODELS[st.session_state.model_label], max_tokens=8000,
                  system=system, messages=list(messages))
    if web:
        kwargs["tools"] = WEB_TOOLS

    for _ in range(4):  # extended web research can pause; continue automatically
        with get_client().messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_start" and event.content_block.type == "server_tool_use":
                    status.caption("Searching the web…" if event.content_block.name == "web_search"
                                   else "Reading source…")
                elif event.type == "text":
                    status.empty()
                    yield event.text
            final = stream.get_final_message()
        for block in final.content:
            for c in (getattr(block, "citations", None) or []):
                url = getattr(c, "url", None)
                if url and url not in sources:
                    sources[url] = getattr(c, "title", None) or url
        if final.stop_reason != "pause_turn":
            break
        kwargs["messages"] = kwargs["messages"] + [{"role": "assistant", "content": final.content}]
    status.empty()


def api_history():
    msgs = [{"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[-MAX_HISTORY:]]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


# ─── SIGN-IN ────────────────────────────────────────────────────────
def login_screen():
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.markdown('<div class="login-card"></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="page-head"><div class="eyebrow">{ORG_NAME}</div>'
                    f'<h1>{APP_NAME}</h1><p>Grant development and communications assistant</p></div>',
                    unsafe_allow_html=True)
        with st.form("login"):
            pw = st.text_input("Access code", type="password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                if hmac.compare_digest(pw, str(st.secrets.get("APP_PASSWORD", "DSR"))):
                    st.session_state.authed = True
                    st.rerun()
                else:
                    st.error("The access code is incorrect.")
        st.caption("Authorized ASRS staff and board members only.")


# ─── PAGES ──────────────────────────────────────────────────────────
def dashboard_page():
    page_header("Overview", "Dashboard", "Organizational impact and grant pipeline at a glance.")
    df = grants()
    awarded = df.loc[df["Status"] == "Awarded", "Amount"].sum()
    pipeline = df.loc[df["Status"].isin(["Researching", "Drafting", "Submitted"]), "Amount"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Students impacted", "5,050+")
    c2.metric("Active programs", len(PROGRAMS))
    c3.metric("Pipeline value", f"${pipeline:,.0f}")
    c4.metric("Total awarded", f"${awarded:,.0f}")

    st.write("")
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.subheader("Start a document")
        a, b = st.columns(2)
        if a.button("Draft a grant proposal", icon=":material/article:", width="stretch"):
            go_chat(TEMPLATES[0]["prompt"])
        if b.button("Research open grants", icon=":material/travel_explore:", width="stretch"):
            go_chat("Research grant opportunities currently open or opening soon that fit ASRS's "
                    "mission (youth STEM enrichment, BIPOC students, Syracuse NY and Virginia). "
                    "For each, give the funder, award range, deadline, eligibility, a link, and why "
                    "ASRS is a strong fit.")
        if a.button("Executive summary", icon=":material/summarize:", width="stretch"):
            go_chat(TEMPLATES[1]["prompt"])
        if b.button("Donor acknowledgment", icon=":material/mail:", width="stretch"):
            go_chat(TEMPLATES[7]["prompt"])
    with right:
        st.subheader("Upcoming deadlines")
        today = date.today()
        open_ = df[df["Status"].isin(["Researching", "Drafting"]) & df["Deadline"].notna()]
        upcoming = open_[open_["Deadline"] >= today].sort_values("Deadline")
        if upcoming.empty:
            st.markdown('<p class="muted">No open deadlines. Add opportunities in the Grant Tracker.</p>',
                        unsafe_allow_html=True)
        for _, r in upcoming.head(5).iterrows():
            days = (r["Deadline"] - today).days
            msg = f"**{r['Funder']}** · {r['Grant']}  \nDue {r['Deadline']:%B %d, %Y} ({days} days)"
            if days <= 14:
                st.warning(msg, icon=":material/schedule:")
            else:
                st.info(msg, icon=":material/event:")
    footer()


def chat_page():
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if not st.session_state.messages:
        page_header("Assistant", "How can I help?",
                    "Draft proposals, letters, budgets, and reports, or research funders. "
                    "Attach PDFs, Word, or Excel files for review.")
        cols = st.columns(3)
        for col, t in zip(cols, [TEMPLATES[1], TEMPLATES[5], TEMPLATES[3]]):
            if col.button(t["name"], icon=t["icon"], width="stretch"):
                st.session_state.pending_prompt = t["prompt"]
                st.rerun()

    for m in st.session_state.messages:
        with st.chat_message(m["role"], avatar=AI_AVATAR if m["role"] == "assistant" else USER_AVATAR):
            st.markdown(m["display"])

    submitted = st.chat_input(
        "Message ASRS Bot Pro",
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
            st.toast(f"Could not read {f.name}: {e}")
    content.append({"type": "text", "text": text})
    display = text + "".join(f"\n\n*Attachment: {f.name}*" for f in files)

    st.session_state.messages.append({"role": "user", "content": content, "display": display})
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(display)

    sources = {}
    with st.chat_message("assistant", avatar=AI_AVATAR):
        status = st.empty()
        try:
            reply = st.write_stream(stream_reply(api_history(), status, sources))
        except anthropic.AuthenticationError:
            reply = None
            st.error("The API key is not valid. An administrator should check ANTHROPIC_API_KEY "
                     "in the app's Secrets.")
        except anthropic.NotFoundError:
            reply = None
            st.error("This API key does not have access to the selected model. "
                     "Choose a different model in the sidebar.")
        except anthropic.BadRequestError as e:
            reply = None
            if "web_" in str(e):
                st.error("Web search is not enabled for this Anthropic account. Enable it in the "
                         "Anthropic Console, or turn off Live web search in the sidebar.")
            else:
                st.error(f"The request could not be completed: {e}")
        except Exception as e:
            reply = None
            st.error(f"The request could not be completed: {e}")

    if isinstance(reply, list):
        reply = "".join(str(x) for x in reply)
    if not reply:
        st.session_state.messages.pop()  # discard the failed request
        return
    if sources:
        links = "\n".join(f"- [{title}]({url})" for url, title in list(sources.items())[:8])
        reply += f"\n\n**Sources**\n{links}"
        st.markdown(f"**Sources**\n{links}")
    st.session_state.messages.append({"role": "assistant", "content": reply, "display": reply})
    st.download_button("Download response", reply, icon=":material/download:",
                       file_name=f"ASRS_{datetime.now():%Y-%m-%d_%H%M}.md",
                       key=f"dl_{len(st.session_state.messages)}")


def templates_page():
    page_header("Library", "Document templates",
                "Generate a first draft grounded in ASRS's programs, outcomes, and budgets.")
    tags = ["All"] + sorted({t["tag"] for t in TEMPLATES})
    pick = st.segmented_control("Category", tags, default="All", label_visibility="collapsed")
    items = [t for t in TEMPLATES if pick in (None, "All") or t["tag"] == pick]
    cols = st.columns(2, gap="medium")
    for i, t in enumerate(items):
        with cols[i % 2].container(border=True):
            st.markdown(f"#### {t['icon']} {t['name']}")
            st.markdown(f'<span class="tag">{t["tag"].upper()}</span>', unsafe_allow_html=True)
            st.markdown(f'<p class="muted">{t["desc"]}</p>', unsafe_allow_html=True)
            if st.button("Generate draft", key=f"tpl_{t['name']}", type="primary",
                         icon=":material/arrow_forward:"):
                go_chat(t["prompt"])
    footer()


def tracker_page():
    page_header("Pipeline", "Grant Tracker", "Track every opportunity from research through award.")
    df = grants()

    counts = df["Status"].value_counts()
    for col, s in zip(st.columns(len(STATUSES)), STATUSES):
        col.metric(s, int(counts.get(s, 0)))

    st.write("")
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
        if st.form_submit_button("Save changes", type="primary", icon=":material/save:"):
            st.session_state.grants = edited.reset_index(drop=True)
            save_grants(st.session_state.grants)
            st.toast("Grant tracker saved.")
            st.rerun()

    c1, c2 = st.columns(2)
    c1.download_button("Export to CSV", df.to_csv(index=False), "ASRS_grant_pipeline.csv",
                       icon=":material/download:", width="stretch")
    up = c2.file_uploader("Import CSV", type="csv", label_visibility="collapsed")
    if up is not None and st.session_state.get("last_import") != up.file_id:
        new = pd.read_csv(up)
        new["Deadline"] = pd.to_datetime(new.get("Deadline"), errors="coerce").dt.date
        st.session_state.grants = new
        st.session_state.last_import = up.file_id
        save_grants(new)
        st.rerun()
    st.caption("Export a CSV backup regularly. Hosted storage may reset when the app restarts.")
    footer()


def programs_page():
    page_header("Portfolio", "Programs", "ASRS initiatives, reach, and history.")
    cols = st.columns(2, gap="medium")
    for i, p in enumerate(PROGRAMS):
        with cols[i % 2].container(border=True):
            st.markdown(f"#### {p['icon']} {p['name']}")
            st.markdown(f'<span class="tag">SINCE {p["since"]}</span>'
                        f'<span class="tag">{p["students"]} STUDENTS</span>', unsafe_allow_html=True)
            st.markdown(f'<p class="muted">{p["desc"]}</p>', unsafe_allow_html=True)
            if st.button("Draft program proposal", key=f"prog_{i}", icon=":material/arrow_forward:"):
                go_chat(f"Write a grant proposal focused on ASRS's {p['name']} program, using our "
                        "documented outcomes, budget figures, and partners.")
    footer()


# ─── APP ────────────────────────────────────────────────────────────
if not st.session_state.get("authed"):
    login_screen()
    st.stop()

PAGES = {
    "dashboard": st.Page(dashboard_page, title="Dashboard", icon=":material/space_dashboard:", default=True),
    "chat": st.Page(chat_page, title="Assistant", icon=":material/forum:"),
    "templates": st.Page(templates_page, title="Templates", icon=":material/description:"),
    "tracker": st.Page(tracker_page, title="Grant Tracker", icon=":material/table_chart:"),
    "programs": st.Page(programs_page, title="Programs", icon=":material/school:"),
}

with st.sidebar:
    st.markdown(f'<div class="brand"><b>{APP_NAME}</b><span>{ORG_NAME}</span></div>',
                unsafe_allow_html=True)

nav = st.navigation(list(PAGES.values()))

with st.sidebar:
    st.divider()
    st.session_state.setdefault("model_label", next(iter(MODELS)))
    st.session_state.setdefault("web_search", True)
    st.selectbox("AI model", list(MODELS), key="model_label",
                 help="Sonnet suits everyday work. Opus produces the strongest long-form proposals. "
                      "Haiku is fastest and lowest cost.")
    st.selectbox("Response language", ["English", "Español"], key="language")
    st.toggle("Live web search", key="web_search",
              help="Allows the assistant to search the web and read pages for current grants, "
                   "deadlines, and funder information.")
    st.divider()
    if st.button("New conversation", icon=":material/add:", width="stretch"):
        st.session_state.messages = []
        st.switch_page(PAGES["chat"])
    if st.button("Sign out", icon=":material/logout:", width="stretch"):
        st.session_state.clear()
        st.rerun()

nav.run()