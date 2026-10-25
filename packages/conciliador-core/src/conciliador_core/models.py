"""Modelos de domínio. Dinheiro sempre em centavos inteiros."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Direction(StrEnum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


class Source(StrEnum):
    NFE = "nfe"
    NFSE = "nfse"
    CSV = "csv"
    MANUAL = "manual"


class ItemStatus(StrEnum):
    OPEN = "open"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BankAccountRef:
    bank_id: str
    branch: str | None
    account_number: str


@dataclass(frozen=True)
class BankTransaction:
    fitid: str | None
    posted_on: date
    amount_cents: int
    memo: str = field(repr=False)  # pode conter nome e CPF/CNPJ: fora do repr
    documents: tuple[str, ...] = field(repr=False)
    dedup_key: str

    @property
    def direction(self) -> Direction:
        return Direction.INFLOW if self.amount_cents > 0 else Direction.OUTFLOW


@dataclass(frozen=True)
class Statement:
    account: BankAccountRef
    start: date | None
    end: date | None
    ledger_balance_cents: int | None
    transactions: tuple[BankTransaction, ...]


@dataclass(frozen=True)
class ExpectedItem:
    id: str
    source: Source
    direction: Direction
    amount_cents: int  # líquido, sempre positivo
    due_on: date
    issued_on: date | None
    counterpart_doc: str | None = field(repr=False)  # dado pessoal: fora do repr
    counterpart_name: str | None = field(repr=False)
    document_number: str | None
    gross_cents: int | None = None
    withholdings: tuple[tuple[str, int], ...] = ()
    branch_cnpj: str | None = None
    status: ItemStatus = ItemStatus.OPEN

    def __post_init__(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError("amount_cents deve ser positivo (valor líquido em centavos)")
