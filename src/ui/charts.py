"""Plotly chart helpers with one consistent palette.

Colour rules: categorical hues in a fixed order, single-hue blue ramp for
magnitude, reserved status colours (always shown together with their label).
No dual axes.
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.inventory.planning import (STATUS_EXCESS, STATUS_INSUFFICIENT, STATUS_LOW,
                                    STATUS_NO_DEMAND, STATUS_OK, STATUS_REORDER)

CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
               "#4a3aa7", "#e34948"]
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
PRIMARY = CATEGORICAL[0]
NEUTRAL = "#898781"

STATUS_COLORS = {
    STATUS_REORDER: "#d03b3b",       # critical
    STATUS_LOW: "#ec835a",           # serious
    STATUS_EXCESS: "#fab219",        # warning
    STATUS_OK: "#0ca30c",            # good
    STATUS_NO_DEMAND: NEUTRAL,
    STATUS_INSUFFICIENT: "#c3c2b7",
}
CLASS_COLORS = {"A": CATEGORICAL[0], "B": CATEGORICAL[1], "C": CATEGORICAL[2],
                "X": CATEGORICAL[0], "Y": CATEGORICAL[1], "Z": CATEGORICAL[2]}


def style(fig: go.Figure, height: int = 380, legend: bool = True) -> go.Figure:
    """Shared layout: title on top, legend in its own row under the title."""
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=90 if legend else 50, b=10),
                      font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif'),
                      title=dict(y=0.98, yanchor="top", x=0, xanchor="left", font=dict(size=15)),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None),
                      showlegend=legend, bargap=0.25, hoverlabel=dict(namelength=-1))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridwidth=1)
    fig.update_traces(selector=dict(type="bar"), marker_line_width=0)
    return fig


def bar(df: pd.DataFrame, x: str, y: str, title: str, color: str | None = None,
        color_map: dict | None = None, horizontal: bool = False, labels: dict | None = None,
        text_format: str | None = None, height: int = 380, order: list | None = None) -> go.Figure:
    kwargs = dict(title=title, labels=labels or {}, color=color,
                  color_discrete_map=color_map,
                  color_discrete_sequence=CATEGORICAL if color else [PRIMARY])
    if order:
        kwargs["category_orders"] = {(y if horizontal else x): order}
    fig = (px.bar(df, x=y, y=x, orientation="h", **kwargs) if horizontal
           else px.bar(df, x=x, y=y, **kwargs))
    if text_format:
        fig.update_traces(texttemplate=text_format, textposition="outside", cliponaxis=False)
    if horizontal:
        fig.update_yaxes(autorange="reversed" if not order else None, title=None)
    if text_format:
        _leave_room_for_labels(fig, df[y], horizontal)
    return style(fig, height, legend=color is not None)


def _leave_room_for_labels(fig: go.Figure, values: pd.Series, horizontal: bool) -> None:
    """Extend the value axis so labels printed outside the bars are not cut off."""
    top = pd.to_numeric(values, errors="coerce").max()
    if pd.notna(top) and top > 0:
        (fig.update_xaxes if horizontal else fig.update_yaxes)(range=[0, top * 1.18])


def status_bar(counts: pd.DataFrame, title: str, value: str = "products",
               value_label: str = "Products") -> go.Figure:
    """Horizontal bar per alert status, coloured by the reserved status palette."""
    fig = px.bar(counts, x=value, y="alert_status", orientation="h", color="alert_status",
                 color_discrete_map=STATUS_COLORS, title=title, text=value,
                 labels={value: value_label, "alert_status": ""})
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_yaxes(categoryorder="array", categoryarray=list(STATUS_COLORS)[::-1])
    _leave_room_for_labels(fig, counts[value], horizontal=True)
    return style(fig, 320, legend=False)


def line(df: pd.DataFrame, x: str, y: str, title: str, color: str | None = None,
         labels: dict | None = None, height: int = 360) -> go.Figure:
    fig = px.line(df, x=x, y=y, color=color, title=title, labels=labels or {},
                  color_discrete_sequence=CATEGORICAL)
    fig.update_traces(line_width=2)
    fig.update_layout(hovermode="x unified")
    return style(fig, height, legend=color is not None)


def histogram(series: pd.Series, title: str, x_label: str, nbins: int = 40) -> go.Figure:
    fig = px.histogram(series.dropna(), nbins=nbins, title=title,
                       labels={"value": x_label}, color_discrete_sequence=[PRIMARY])
    fig.update_layout(yaxis_title="Products")
    return style(fig, 340, legend=False)


def pareto_curve(classified: pd.DataFrame, a_threshold: float, b_threshold: float) -> go.Figure:
    """Cumulative share of consumption value vs share of SKUs (single axis)."""
    df = classified.sort_values("abc_rank")
    df = df.assign(sku_share=df["abc_rank"] / len(df))
    fig = go.Figure()
    for cls in ("A", "B", "C"):
        part = df[df["abc_class"] == cls]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["sku_share"], y=part["cumulative_share"], mode="lines", name=f"Class {cls}",
            line=dict(color=CLASS_COLORS[cls], width=3),
            customdata=part[["sku_id", "product_name"]],
            hovertemplate="%{customdata[0]} %{customdata[1]}<br>Top %{x:.1%} of SKUs"
                          "<br>Cumulative value %{y:.1%}<extra>Class " + cls + "</extra>"))
    for level, label in ((a_threshold, "A/B threshold"), (b_threshold, "B/C threshold")):
        fig.add_hline(y=level, line_dash="dot", line_color=NEUTRAL, line_width=1,
                      annotation_text=f"{label} ({level:.0%})", annotation_position="bottom right")
    fig.update_layout(title="Pareto curve: cumulative share of annual consumption value",
                      xaxis_title="Share of SKUs (ranked by value)",
                      yaxis_title="Cumulative share of value")
    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
    return style(fig, 400)


def matrix_heatmap(matrix: pd.DataFrame, title: str, value_format: str = ",.0f") -> go.Figure:
    fig = px.imshow(matrix, text_auto=value_format, color_continuous_scale=SEQUENTIAL_BLUE,
                    labels=dict(x="XYZ (demand variability)", y="ABC (value)", color=""),
                    title=title, aspect="auto")
    fig.update_xaxes(side="top")
    return style(fig, 360, legend=False)
