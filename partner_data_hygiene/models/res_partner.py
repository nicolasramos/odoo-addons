# © 2026 Nicolás Ramos — LGPL-3
"""Normaliza teléfonos y correos de los contactos al guardarlos.

Los teléfonos llegan escritos de mil maneras ("612 34 56 78", "+34 922-28-94-51",
"0034612345678", "(922) 289 451"). Se guardan en formato internacional legible
"+34 612 34 56 78".

La normalización es propia y determinista a propósito: ``phone_validation``
devuelve el número tal cual cuando ya es válido en formato nacional, así que no
sirve para canonicalizar lo que llega sucio.

Los correos se recortan y se pasan a minúsculas. Un correo que no encaja en el
patrón NO se modifica ni se borra: se deja tal cual y se anota un aviso, porque
rechazar el dato en silencio sería peor que guardarlo sucio.
"""

import logging
import re

from odoo import api, models

_logger = logging.getLogger(__name__)

_NOT_PHONE = re.compile(r"[^0-9+]")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Un número con menos dígitos que esto no es un teléfono: puede ser un
# identificador interno o una extensión, y normalizarlo lo estropearía.
_MIN_DIGITS = 6

# Prefijo por defecto cuando el contacto no tiene país: el cliente es canario y
# sus contactos son españoles casi siempre.
DEFAULT_PREFIX = "34"

# Plan de numeración español: 9 dígitos que empiezan por 6 (móvil), 7 (móvil) o
# 9 (fijo).
_ES_MOBILE_OR_FIXED = re.compile(r"^[679]\d{8}$")


def clean_phone(raw):
    """Deja solo dígitos y un '+' inicial. ``0034...`` pasa a ``+34...``.

    Devuelve False si no queda nada usable.
    """
    if not raw:
        return False
    text = _NOT_PHONE.sub("", str(raw))
    if text.startswith("00"):
        text = "+" + text[2:]
    if text.startswith("+"):
        return "+" + text[1:].replace("+", "")
    return text.replace("+", "")


def _split_prefix(number, country_code=None):
    """Separa el prefijo internacional del resto de dígitos de un '+NN...'."""
    digits = number.lstrip("+")
    code = str(country_code or "").lstrip("+")
    if code and digits.startswith(code):
        return code, digits[len(code):]
    # Sin país conocido: los prefijos reales tienen 1, 2 o 3 dígitos. Se prueba
    # de más largo a más corto y se acepta el primero que deja un número con
    # longitud plausible.
    for size in (3, 2, 1):
        if len(digits) - size >= _MIN_DIGITS:
            return digits[:size], digits[size:]
    return code or DEFAULT_PREFIX, digits


def format_phone(raw, country_code=None):
    """Devuelve el teléfono en formato internacional legible, o False."""
    cleaned = clean_phone(raw)
    if not cleaned:
        return False

    digits = cleaned.lstrip("+")
    if len(digits) < _MIN_DIGITS:
        # No parece un teléfono: se devuelve tal cual para no perder el dato.
        return str(raw).strip()

    if cleaned.startswith("+"):
        prefix, rest = _split_prefix(cleaned, country_code)
    else:
        code = str(country_code or "").lstrip("+")
        if not code and _ES_MOBILE_OR_FIXED.match(digits):
            code = DEFAULT_PREFIX
        if code and digits.startswith(code) and len(digits) - len(code) >= 9:
            prefix, rest = code, digits[len(code):]
        elif code:
            prefix, rest = code, digits
        else:
            prefix, rest = DEFAULT_PREFIX, digits

    if prefix == DEFAULT_PREFIX and len(rest) == 9:
        # 612 34 56 78
        return f"+{prefix} {rest[:3]} {rest[3:5]} {rest[5:7]} {rest[7:]}"
    # 6123456789 -> 612 345 6789 (agrupación genérica de 3)
    grouped = " ".join(rest[i : i + 3] for i in range(0, len(rest), 3))
    return f"+{prefix} {grouped}".strip()


def clean_email(raw):
    """Recorta espacios y pasa a minúsculas."""
    if not raw:
        return raw
    return str(raw).strip().lower()


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _hygiene_phone(self, number, country=None):
        code = str(country.phone_code) if country and country.phone_code else None
        return format_phone(number, code)

    @api.model
    def _hygiene_vals(self, vals, country=None):
        """Normaliza ``email``, ``phone`` y ``mobile`` dentro de ``vals``."""
        if vals.get("email"):
            email = clean_email(vals["email"])
            if not _EMAIL.match(email):
                _logger.info("Correo con formato dudoso en el contacto: %r", email)
            vals["email"] = email

        if country is None:
            country_id = vals.get("country_id") or self.env.context.get(
                "default_country_id"
            )
            if country_id:
                country = self.env["res.country"].browse(country_id)

        for field in ("phone", "mobile"):
            if vals.get(field):
                vals[field] = self._hygiene_phone(vals[field], country)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._hygiene_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if any(f in vals for f in ("email", "phone", "mobile")):
            country = self.country_id if len(self) == 1 else None
            vals = self._hygiene_vals(vals, country)
        return super().write(vals)
