"""SDBS utility functions."""

from __future__ import annotations

import re


_LATEX_SPECIAL = re.compile(r"[&%$#_{}~^\\]")


def latex_escape(value: str) -> str:
    """Escape special LaTeX characters in a string.

    Replaces characters that have special meaning in LaTeX (such as ``&``,
    ``%``, ``$``, ``#``, ``_``, ``{``, ``}``, ``~``, ``^``, ``\\``)
    with their LaTeX-safe equivalents.

    Args:
        value: Raw string to escape.

    Returns:
        String with LaTeX special characters escaped.
    """
    def _replace(m: re.Match) -> str:
        ch = m.group(0)
        mapping = {
            "\\": "\\textbackslash{}",
            "&": "\\&",
            "%": "\\%",
            "$": "\\$",
            "#": "\\#",
            "_": "\\_",
            "{": "\\{",
            "}": "\\}",
            "~": "\\textasciitilde{}",
            "^": "\\textasciicircum{}",
        }
        return mapping[ch]
    return _LATEX_SPECIAL.sub(_replace, value)
