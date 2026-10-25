"""Filtros e tags do design system para templates Django.

Uso: {% load conciliador_ds %}
  {{ item.cents|brl }}                 -> −R$ 250,90
  {{ item.cents|brl:"always" }}        -> +R$ 1.900,00 (verde)
  {{ item.cents|brl:"never,lg" }}      -> R$ 43.210,10 grande, sem sinal
  {{ cnpj|doc }}  {{ cpf|doc }}        -> CNPJ 12.345.678/0001-95 · CPF ***.222.333-**
  {% status_label item.status view item.direction %}
  {% icon "check" 16 %}

Dinheiro SEMPRE em centavos inteiros. Nunca float.
"""

import re

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

from conciliador_ui import vocab

register = template.Library()
MINUS = "\u2212"


def _split(cents: int) -> tuple[str, str]:
    a = abs(int(cents))
    return f"{a // 100:,}".replace(",", "."), f"{a % 100:02d}"


@register.filter
def brl(cents, opts: str = "auto"):
    """opts: "<sign>[,<size>][,<tone>][,nocur]" — sign: auto|always|never; size: sm|lg|xl; tone: neutral|muted|div|late."""
    if cents is None or cents == "":
        return ""
    cents = int(cents)
    parts = [p.strip() for p in str(opts).split(",") if p.strip()]
    sign = next((p for p in parts if p in ("auto", "always", "never")), "auto")
    size = next((p for p in parts if p in ("sm", "lg", "xl")), "")
    tone = next((p for p in parts if p in ("neutral", "muted", "div", "late")), "")
    nocur = "nocur" in parts
    i, d = _split(cents)
    s = (
        ""
        if sign == "never"
        else (MINUS if cents < 0 else ("+" if sign == "always" and cents > 0 else ""))
    )
    classes = ["amount"]
    if size:
        classes.append(f"amount--{size}")
    if tone:
        classes.append(f"amount--{tone}")
    elif sign == "always" and cents > 0:
        classes.append("amount--in")
    cur = "" if nocur else '<span class="amount__cur">R$</span>'
    return format_html(
        '<span class="{}">{}{}{}<span class="amount__dec">,{}</span></span>',
        " ".join(classes),
        s,
        format_html(cur),
        i,
        d,
    )


def _format_doc(raw: str, masked: bool) -> tuple[str, str]:
    v = re.sub(r"[^0-9A-Z]", "", str(raw).upper())
    if len(v) == 11:
        txt = f"***.{v[3:6]}.{v[6:9]}-**" if masked else f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}"
        return "CPF", txt
    if len(v) == 14:
        return "CNPJ", f"{v[:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:]}"
    return "Doc.", v


@register.filter
def doc(value, opts: str = ""):
    """CPF sai SEMPRE mascarado; opts "nokind" esconde o rótulo. Suporta CNPJ alfanumérico."""
    if not value:
        return ""
    kind, txt = _format_doc(value, masked=True)
    if "nokind" in str(opts):
        return format_html('<span class="doc">{}</span>', txt)
    return format_html('<span class="doc"><span class="doc__kind">{}</span>{}</span>', kind, txt)


@register.simple_tag
def status_label(status, view="dono", direction="in"):
    return vocab.status_label(status, view, direction)


@register.filter
def status_tone(status):
    return vocab.TONE.get(status, "cancel")


@register.filter
def node_icon(status):
    return vocab.NODE.get(status, ("arrow-left-right", True))[0]


@register.filter
def node_closed(status):
    return vocab.NODE.get(status, ("", False))[1]


@register.simple_tag
def icon(name, size=18, label=""):
    """Ícone do sprite Lucide local (static/icons/lucide-sprite.svg). Sem label = decorativo."""
    size_cls = f" icon--{size}" if int(size) in (14, 16, 20) else ""
    href = static("icons/lucide-sprite.svg") + "#" + name
    if label:
        return format_html(
            '<svg class="icon{}" role="img" aria-label="{}"><use href="{}"></use></svg>',
            size_cls,
            label,
            href,
        )
    return format_html(
        '<svg class="icon{}" aria-hidden="true"><use href="{}"></use></svg>', size_cls, href
    )
