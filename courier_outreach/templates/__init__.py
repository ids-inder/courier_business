"""Preset outreach email templates (no AI).

Plain-text `.txt` files with `{merge_field}` placeholders, rendered per lead.
The sequence is first_touch -> followup_1 -> followup_2. Edit the wording in the
.txt files freely; the merge fields come from the lead + your BusinessProfile.
"""

from .renderer import (  # noqa: F401
    RenderedEmail,
    SEQUENCE,
    render,
    template_for_status,
)
