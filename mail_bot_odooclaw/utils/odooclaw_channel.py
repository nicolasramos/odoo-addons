# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Channel model naming, wire contract versus runtime model.

The engine is version-agnostic and always names chat targets
``discuss.channel`` in webhook payloads and reply calls. Odoo 16 calls that
model ``mail.channel`` (``discuss.channel`` arrived in 17). Translate at the
boundary: keep the wire value stable for the engine, use the runtime name for
every ``env[...]`` lookup and every ``mail.message.model`` comparison.
"""

# What the engine sees, on every Odoo version.
ODOOCLAW_CHANNEL_WIRE = "discuss.channel"

# What this Odoo version calls the model.
CHANNEL_MODEL = "mail.channel"


def channel_runtime_model(model):
    """Wire name -> runtime model name (identity for other models)."""
    return CHANNEL_MODEL if model == ODOOCLAW_CHANNEL_WIRE else model


def channel_wire_model(model):
    """Runtime model name -> wire name (identity for other models)."""
    return ODOOCLAW_CHANNEL_WIRE if model == CHANNEL_MODEL else model
