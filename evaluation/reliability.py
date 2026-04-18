"""Reliability diagram as a self-contained SVG string.

A reliability diagram plots empirical accuracy (y) vs. mean confidence (x) per
bin, alongside the diagonal (perfectly calibrated). Bars below the diagonal =
overconfident; bars above = underconfident. Bar width is proportional to bin
count.
"""
from __future__ import annotations


def reliability_diagram_svg(
    calibration: dict[str, object],
    width: int = 480,
    height: int = 380,
    title: str = "Reliability Diagram",
) -> str:
    """Return an SVG string visualising a fitted calibration."""
    bins = calibration["bins"]
    pad_l, pad_r, pad_t, pad_b = 60, 30, 36, 50
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    total = sum(int(b["count"]) for b in bins)  # type: ignore[arg-type, index]
    max_count = max((int(b["count"]) for b in bins), default=1)  # type: ignore[arg-type]

    def px(x: float) -> float:  # x in [0,1]
        return pad_l + x * plot_w

    def py(y: float) -> float:  # y in [0,1] inverted
        return pad_t + (1.0 - y) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui,sans-serif" font-size="12">',
        f'<rect width="{width}" height="{height}" fill="#0d1117"/>',
        f'<text x="{width / 2}" y="22" fill="#f0f6fc" text-anchor="middle" '
        f'font-weight="600">{title}</text>',
    ]

    # Axes
    parts.append(
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" '
        f'stroke="#30363d" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" '
        f'stroke="#30363d" stroke-width="1"/>'
    )

    # Ticks + gridlines
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        # y axis
        y = py(t)
        parts.append(f'<line x1="{pad_l}" y1="{y}" x2="{pad_l + plot_w}" y2="{y}" '
                     f'stroke="#161b22" stroke-width="1"/>')
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + 4}" fill="#8b949e" text-anchor="end">'
            f'{t:.2f}</text>'
        )
        # x axis
        x = px(t)
        parts.append(
            f'<text x="{x}" y="{pad_t + plot_h + 18}" fill="#8b949e" text-anchor="middle">'
            f'{t:.2f}</text>'
        )

    # Diagonal (perfect calibration)
    parts.append(
        f'<line x1="{px(0)}" y1="{py(0)}" x2="{px(1)}" y2="{py(1)}" '
        f'stroke="#f0b400" stroke-dasharray="4 4" stroke-width="1.5"/>'
    )

    # Bars (one per bin with enough samples)
    bar_width = plot_w / 10
    for b in bins:
        count = int(b["count"])  # type: ignore[arg-type, index]
        if count == 0:
            continue
        empirical = b["empirical_accuracy"]  # type: ignore[index]
        if empirical is None:
            continue
        bin_low = float(b["bin_low"])  # type: ignore[arg-type, index]
        acc = float(empirical)
        x_left = px(bin_low)
        y_top = py(acc)
        h = plot_h - (y_top - pad_t)
        # Color: green if close to diagonal, orange if overconfident, red if much off
        mid_conf = bin_low + 0.05
        gap = acc - mid_conf
        if abs(gap) < 0.05:
            fill = "#3fb950"
        elif gap < 0:
            fill = "#f85149"  # overconfident (acc < conf)
        else:
            fill = "#58a6ff"  # underconfident (acc > conf)
        opacity = 0.4 + 0.5 * (count / max_count)
        parts.append(
            f'<rect x="{x_left + 1}" y="{y_top}" width="{bar_width - 2}" height="{h}" '
            f'fill="{fill}" fill-opacity="{opacity:.2f}"/>'
        )
        # Count label on top
        parts.append(
            f'<text x="{x_left + bar_width / 2}" y="{y_top - 4}" '
            f'fill="#c9d1d9" text-anchor="middle" font-size="10">n={count}</text>'
        )

    # Axis labels
    parts.append(
        f'<text x="{pad_l + plot_w / 2}" y="{height - 12}" fill="#c9d1d9" '
        f'text-anchor="middle" font-size="13">Predicted confidence (bin)</text>'
    )
    parts.append(
        f'<text transform="rotate(-90 16,{pad_t + plot_h / 2})" '
        f'x="16" y="{pad_t + plot_h / 2}" fill="#c9d1d9" text-anchor="middle" '
        f'font-size="13">Empirical accuracy</text>'
    )

    parts.append(
        f'<text x="{width - pad_r}" y="{height - 12}" fill="#8b949e" '
        f'text-anchor="end" font-size="10">n={total} · dashed = perfect calibration</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
