"""Generate realistic-looking sample CSVs for the pipelines.

Produces:
    data/samples/legal_documents.csv    (~5,000 rows)
    data/samples/counterparties.csv     (~500 rows)
    data/samples/contracts.csv          (~1,500 rows)
    data/samples/transactions.csv       (~20,000 rows)

Run: python scripts/seed_data.py
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from faker import Faker

fake = Faker("en_US")
Faker.seed(42)
random.seed(42)

OUT_DIR = Path("data/samples")
OUT_DIR.mkdir(parents=True, exist_ok=True)

JURISDICTIONS = ["US-NY", "US-CA", "UK", "DE", "FR", "ES", "BR", "MX"]
DOC_TYPES = ["JUDGMENT", "REGULATION", "CONTRACT", "NOTICE", "FILING", "DECREE"]
TXN_TYPES = ["INVOICE", "PAYMENT", "REFUND", "ADJUSTMENT", "FEE"]
CURRENCIES = ["USD", "EUR", "GBP", "BRL", "MXN"]
COUNTRIES = ["US", "GB", "DE", "FR", "ES", "BR", "MX"]


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"wrote {len(rows):,} rows → {path}")


def legal_documents(n: int = 5000) -> None:
    rows = []
    for i in range(n):
        d = fake.date_between(start_date=date(2022, 1, 1), end_date=date.today())
        rows.append([
            f"DOC-{i:06d}",
            d.isoformat(),
            random.choice(["api:courts", "api:registry", "scraper:gov"]),
            random.choice(DOC_TYPES),
            fake.sentence(nb_words=8).rstrip("."),
            fake.paragraph(nb_sentences=3),
            random.choice(JURISDICTIONS),
        ])
    # Insert some invalid rows to exercise rejection path
    for _ in range(50):
        rows.append(["", "", "", "", "", "", ""])
    random.shuffle(rows)
    write_csv(
        OUT_DIR / "legal_documents.csv",
        ["doc_id", "date", "source_system", "type", "title", "content", "jurisdiction"],
        rows,
    )


def counterparties(n: int = 500) -> list[str]:
    ids = []
    rows = []
    for _ in range(n):
        ext_id = f"CP-{uuid4().hex[:12].upper()}"
        ids.append(ext_id)
        rows.append([
            ext_id,
            fake.company(),
            fake.ein(),
            random.choice(COUNTRIES),
            round(random.uniform(0, 100), 2),
        ])
    write_csv(
        OUT_DIR / "counterparties.csv",
        ["external_id", "name", "tax_id", "country_code", "risk_score"],
        rows,
    )
    return ids


def contracts(counterparty_ids: list[str], n: int = 1500) -> list[str]:
    numbers = []
    rows = []
    for i in range(n):
        contract_number = f"CT-{i:07d}"
        numbers.append(contract_number)
        start = fake.date_between(start_date=date(2023, 1, 1), end_date=date.today())
        end = start + timedelta(days=random.randint(90, 1095))
        rows.append([
            contract_number,
            random.choice(counterparty_ids),
            start.isoformat(),
            end.isoformat(),
            round(random.uniform(1000, 1_000_000), 2),
            random.choice(CURRENCIES),
            random.choice(["DRAFT", "ACTIVE", "EXPIRED"]),
        ])
    write_csv(
        OUT_DIR / "contracts.csv",
        ["contract_number", "counterparty_external_id", "start_date", "end_date",
         "total_value", "currency", "status"],
        rows,
    )
    return numbers


def transactions(
    contract_numbers: list[str], counterparty_ids: list[str], n: int = 20000
) -> None:
    rows = []
    for i in range(n):
        d = fake.date_between(start_date=date(2023, 1, 1), end_date=date.today())
        rows.append([
            d.isoformat(),
            random.choice(contract_numbers),
            random.choice(counterparty_ids),
            round(random.uniform(-5000, 50000), 2) or Decimal("1.00"),
            random.choice(CURRENCIES),
            random.choice(TXN_TYPES),
            f"TXN-{i:08d}",
            random.choice(["erp:sap", "erp:oracle", "bank:wire"]),
        ])
    write_csv(
        OUT_DIR / "transactions.csv",
        ["transaction_date", "contract_number", "counterparty_external_id", "amount",
         "currency", "transaction_type", "reference", "source_system"],
        rows,
    )


def main() -> None:
    legal_documents(5000)
    ids = counterparties(500)
    numbers = contracts(ids, 1500)
    transactions(numbers, ids, 20000)
    print("seed complete")


if __name__ == "__main__":
    main()
