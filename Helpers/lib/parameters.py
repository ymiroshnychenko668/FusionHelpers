"""User parameter helpers."""

import adsk.core
import adsk.fusion


def ensure_user_parameter(design: adsk.fusion.Design, name: str,
                          default_value, units: str = 'mm'
                          ) -> adsk.fusion.UserParameter:
    """Return the user parameter ``name``, creating it if absent.

    An existing parameter is returned untouched so its current value and
    expression are preserved. A new one is created from ``default_value``,
    which may be either a number (interpreted in ``units``) or an
    expression string such as ``"2 mm"`` (units are taken from the string).
    """
    existing = design.userParameters.itemByName(name)
    if existing:
        return existing
    expr = default_value if isinstance(default_value, str) \
        else f'{default_value} {units}'
    value = adsk.core.ValueInput.createByString(expr)
    return design.userParameters.add(name, value, units, '')
