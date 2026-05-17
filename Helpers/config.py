"""Central identifiers and names for the Helpers add-in.

Keeping every Fusion id in one place makes them unique, consistent, and
easy to clean up on stop().
"""

ADDIN_NAME = 'Helpers'

# Prefix for every command/control id so they never collide with other
# add-ins or Fusion's own ids.
_PREFIX = 'FusionHelpers'

# Where the menu lives: Design workspace, UTILITIES tab, our own panel.
# (The UTILITIES tab's id is 'ToolsTab'.)
WORKSPACE_ID = 'FusionSolidEnvironment'
TAB_ID = 'ToolsTab'
PANEL_ID = f'{_PREFIX}_HelpersPanel'
PANEL_NAME = 'Helpers'

# Instruments sit directly in the panel (no nested dropdown — that made a
# "Helpers" menu inside the "Helpers" panel). This id is retained only so
# run() can delete a stale legacy dropdown left by an older session.
LEGACY_DROPDOWN_ID = f'{_PREFIX}_HelpersDropDown'


def cmd_id(short_name: str) -> str:
    """Return a globally-unique command id for an instrument."""
    return f'{_PREFIX}_{short_name}'
