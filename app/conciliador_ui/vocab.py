"""Vocabulário único da conciliação: um status, duas visões (dono / contador).

Fonte da verdade para rótulos de interface. Espelha components/feedback/StatusBadge.jsx.
"""

from typing import Literal

Status = Literal[
    "conciliado",
    "a_confirmar",
    "pendente",
    "atrasado",
    "nao_identificado",
    "divergencia",
    "classificado",
    "transferencia",
    "cancelado",
]
View = Literal["dono", "contador"]
Direction = Literal["in", "out"]

# tone -> sufixo de classe CSS (.badge--<tone>, .dot--<tone>)
TONE: dict[str, str] = {
    "conciliado": "ok",
    "a_confirmar": "confirm",
    "pendente": "pending",
    "atrasado": "late",
    "nao_identificado": "unid",
    "divergencia": "div",
    "classificado": "ok",
    "transferencia": "neutral",
    "cancelado": "cancel",
}

LABELS: dict[str, dict[str, str | dict[str, str]]] = {
    "conciliado": {"dono": {"in": "Recebido", "out": "Pago"}, "contador": "Conciliado"},
    "a_confirmar": {"dono": "Para confirmar", "contador": "Sugestão a confirmar"},
    "pendente": {"dono": "Pendente", "contador": "Só nos documentos · em aberto"},
    "atrasado": {"dono": "Atrasado", "contador": "Só nos documentos · vencido"},
    "nao_identificado": {"dono": "Não identificado", "contador": "Só no banco"},
    "divergencia": {
        "dono": {"in": "Recebido com diferença", "out": "Pago com diferença"},
        "contador": "Divergência",
    },
    "classificado": {
        "dono": {"in": "Recebido · sem documento", "out": "Pago · sem documento"},
        "contador": "Só no banco · classificado",
    },
    "transferencia": {"dono": "Transferência", "contador": "Transferência entre contas"},
    "cancelado": {"dono": "Cancelado", "contador": "Cancelado"},
}

# ícone Lucide do nó entre banco e documento; "fechado" = linha cheia
NODE: dict[str, tuple[str, bool]] = {
    "conciliado": ("check", True),
    "a_confirmar": ("arrow-left-right", True),
    "divergencia": ("equal-not", True),
    "pendente": ("clock", False),
    "atrasado": ("clock-alert", False),
    "nao_identificado": ("circle-help", False),
    "classificado": ("check", True),
    "transferencia": ("arrow-left-right", True),
    "cancelado": ("x", False),
}

# ordem de exibição no painel do dono
ORDER = [
    "a_confirmar",
    "atrasado",
    "nao_identificado",
    "pendente",
    "divergencia",
    "conciliado",
    "classificado",
    "transferencia",
    "cancelado",
]


def status_label(status: str, view: str = "dono", direction: str = "in") -> str:
    entry = LABELS.get(status)
    if entry is None:
        return status
    label = entry.get(view, entry["dono"])
    if isinstance(label, dict):
        return label.get(direction, label["in"])
    return label
