"""Visual styling: one small stylesheet shared by every page.

Colours use semi-transparent tints so the styling works in both the light and
the dark Streamlit theme (Settings -> Theme).
"""
import html

import streamlit as st

CSS = """
<style>
:root {
  --brand: #2a78d6;
  --brand-2: #1baf7a;
  --card-border: rgba(128, 128, 128, 0.22);
  --card-bg: rgba(128, 128, 128, 0.06);
  --muted: rgba(128, 128, 128, 0.95);
}
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }

/* KPI cards */
div[data-testid="stMetric"] {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-left: 4px solid var(--brand);
  border-radius: 12px;
  padding: 14px 16px 10px 16px;
}
div[data-testid="stMetricLabel"] p { font-size: 0.82rem; font-weight: 600; opacity: 0.8; }
div[data-testid="stMetricValue"] { font-size: 1.65rem; font-weight: 700; }

/* Page hero */
.app-hero {
  padding: 20px 24px; margin-bottom: 18px; border-radius: 16px;
  background: linear-gradient(120deg, rgba(42,120,214,0.14), rgba(27,175,122,0.10));
  border: 1px solid rgba(42,120,214,0.25);
}
.app-hero h1 { font-size: 1.9rem; margin: 0 0 4px 0; padding: 0; line-height: 1.25; }
.app-hero p { margin: 0; opacity: 0.85; font-size: 0.98rem; }
.chips { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px;
  border-radius: 999px; font-size: 0.78rem; font-weight: 600;
  border: 1px solid var(--card-border); background: rgba(128,128,128,0.08);
}
.chip.synthetic { border-color: rgba(235,104,52,0.55); background: rgba(235,104,52,0.12); }
.chip.user { border-color: rgba(12,163,12,0.5); background: rgba(12,163,12,0.10); }
.chip.none { border-color: rgba(208,59,59,0.5); background: rgba(208,59,59,0.10); }

/* Info cards (home page steps / features) */
.card {
  height: 100%; padding: 16px 18px; border-radius: 14px;
  border: 1px solid var(--card-border); background: var(--card-bg);
}
.card .step { font-size: 0.75rem; font-weight: 700; letter-spacing: .06em;
              text-transform: uppercase; color: var(--brand); }
.card h4 { margin: 4px 0 6px 0; padding: 0; font-size: 1.02rem; }
.card p { margin: 0; font-size: 0.9rem; opacity: 0.85; }

/* Sidebar user card */
.user-card {
  padding: 10px 12px; border-radius: 12px; border: 1px solid var(--card-border);
  background: var(--card-bg); margin-bottom: 8px; font-size: 0.88rem;
}
.user-card .role { font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
                   letter-spacing: .05em; color: var(--brand); }

/* Sign-in card */
.login-head { text-align: center; margin: 2.5rem 0 1rem 0; }
.login-head .logo {
  width: 56px; height: 56px; border-radius: 16px; margin: 0 auto 12px auto;
  display: grid; place-items: center; color: #fff; font-weight: 800; font-size: 1.5rem;
  background: linear-gradient(135deg, var(--brand), var(--brand-2));
}
.login-head h2 { margin: 0; padding: 0; }
.login-head p { opacity: 0.75; margin: 4px 0 0 0; }

/* Tabs and tables */
button[data-baseweb="tab"] p { font-weight: 600; }
div[data-testid="stDataFrame"] { border-radius: 10px; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, description: str, chips: list[tuple[str, str]] | None = None) -> None:
    """Page header card. ``chips`` = [(text, css class)]; all text is HTML-escaped."""
    chip_html = "".join(f'<span class="chip {html.escape(cls)}">{html.escape(text)}</span>'
                        for text, cls in (chips or []))
    st.markdown(f"""<div class="app-hero"><h1>{html.escape(title)}</h1>
        <p>{html.escape(description)}</p>
        {f'<div class="chips">{chip_html}</div>' if chip_html else ''}</div>""",
                unsafe_allow_html=True)


def card(title: str, body: str, step: str = "") -> None:
    st.markdown(f"""<div class="card">{f'<div class="step">{html.escape(step)}</div>' if step else ''}
        <h4>{html.escape(title)}</h4><p>{html.escape(body)}</p></div>""", unsafe_allow_html=True)
