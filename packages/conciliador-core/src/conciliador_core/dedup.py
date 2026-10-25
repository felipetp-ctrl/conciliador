"""Chave de deduplicação de lançamentos bancários."""

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date

from conciliador_core.models import BankAccountRef, BankTransaction

_SPACES = re.compile(r"\s+")


def normalize_memo(memo: str) -> str:
    """Maiúsculas, sem acentos e com espaços colapsados."""
    decomposed = unicodedata.normalize("NFKD", memo.upper())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACES.sub(" ", plain).strip()


def encode_fields(fields: Sequence[str]) -> str:
    # Prefixo de tamanho: um "|" dentro de um campo não muda a divisão dos campos.
    return "|".join(f"{len(f)}:{f}" for f in fields)


def compute_dedup_keys(account: BankAccountRef, txns: Sequence[tuple[date, int, str]]) -> list[str]:
    """Calcula a chave (SHA-256) de cada lançamento ``(data, centavos, histórico)``.

    A chave combina banco, agência (``None`` vira ``""``), conta, data ISO, valor,
    histórico normalizado e um ordinal (1, 2, ...) entre os lançamentos do MESMO
    arquivo com a mesma data, o mesmo valor e o mesmo histórico normalizado. Assim,
    lançamentos idênticos no mesmo dia continuam distintos.

    Limitação entre arquivos: como o ordinal conta apenas dentro de um arquivo,
    extratos sobrepostos geram as mesmas chaves quando cobrem os dias inteiros. Se um
    arquivo cortar um dia no meio, os ordinais podem divergir.
    """
    seen: Counter[tuple[date, int, str]] = Counter()
    keys: list[str] = []
    for posted_on, amount_cents, memo in txns:
        triple = (posted_on, amount_cents, normalize_memo(memo))
        seen[triple] += 1
        raw = encode_fields(
            [
                account.bank_id,
                account.branch or "",
                account.account_number,
                posted_on.isoformat(),
                str(amount_cents),
                triple[2],
                str(seen[triple]),
            ]
        )
        keys.append(hashlib.sha256(raw.encode("utf-8")).hexdigest())
    return keys


def deduplicate_transactions(
    existing: Iterable[BankTransaction], incoming: Iterable[BankTransaction]
) -> list[BankTransaction]:
    """Devolve só os lançamentos novos de ``incoming``, na ordem de entrada.

    É duplicado quem tem o mesmo ``fitid`` não vazio ou a mesma ``dedup_key`` de um
    lançamento existente (``fitid`` vazio ou só com espaços e ``dedup_key`` vazia
    contam como ausentes). Os itens de ``incoming`` não são comparados entre si.

    ``existing`` e ``incoming`` devem pertencer à MESMA conta: o ``fitid`` é comparado
    globalmente e ``BankTransaction`` não guarda a conta, então quem chama deve filtrar
    ``existing`` por conta antes.
    """
    fitids: set[str] = set()
    keys: set[str] = set()
    for tx in existing:
        if tx.fitid and tx.fitid.strip():
            fitids.add(tx.fitid.strip())
        if tx.dedup_key:
            keys.add(tx.dedup_key)

    def is_duplicate(tx: BankTransaction) -> bool:
        fitid = (tx.fitid or "").strip()
        return (bool(fitid) and fitid in fitids) or (bool(tx.dedup_key) and tx.dedup_key in keys)

    return [t for t in incoming if not is_duplicate(t)]
