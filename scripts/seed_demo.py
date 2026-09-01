"""Generate plausible demo data, so the dashboard can be looked at before real receipts exist.

Writes directly to the database - it does not call the extraction engine and costs nothing.
Every row it creates is tagged `source="demo"`, and `--clear` removes exactly those rows
again, so this can be run against a live database and cleanly undone.

    python scripts/seed_demo.py --yes
    python scripts/seed_demo.py --clear
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Category, ExtractionAttempt, LineKind, Merchant, Product, ProductAlias,
    Receipt, ReceiptItem, ReceiptStatus,
)
from app.services.catalog import resolve_merchant  # noqa: E402
from app.services.seed import seed_categories  # noqa: E402

SHOPS = ("TESCO-GLOBAL ÁRUHÁZAK ZRT. 2040 BUDAÖRS", "LIDL MAGYARORSZÁG KFT. 1103 BUDAPEST",
         "SPAR MAGYARORSZÁG KFT. 1097 BUDAPEST")

# (canonical name, receipt text, category slug, base price Ft, VAT %, monthly drift %)
BASKET = (
    ("Tej 2,8% 1 l", "TEJ 2,8% 1L UHT", "tejtermek", 379, 18, 1.4),
    ("Fehér kenyér 1 kg", "FEHER KENYER 1KG", "pekaru", 549, 18, 1.9),
    ("Trappista sajt", "TRAPPISTA SAJT SZELET", "tejtermek", 899, 18, 1.1),
    ("Tojás M 10 db", "TOJAS M 10DB", "alapveto-elelmiszer", 899, 5, 1.6),
    ("Őrölt kávé 250 g", "KAVE OROLT 250G", "kave-es-tea", 1499, 27, 0.8),
    ("Alma Idared", "ALMA IDARED", "zoldseg-es-gyumolcs", 599, 5, 2.2),
    ("Csirkemell filé", "CSIRKEMELL FILE", "hus-es-hal", 2199, 5, 1.2),
    ("Ásványvíz 1,5 l", "ASVANYVIZ 1,5L", "asvanyviz", 199, 27, 0.9),
    ("Mosogatószer 1 l", "MOSOGATOSZER 1L", "tisztitoszer", 899, 27, 0.7),
    ("Toalettpapír 8 tekercs", "TOALETTPAPIR 8 TEKERCS", "papiraru", 1299, 27, 1.0),
)

# Each shop's price level relative to the base, so the basket comparison has something to say.
SHOP_FACTOR = {"Tesco": 1.00, "Lidl": 0.94, "Spar": 1.07}


async def clear() -> None:
    async with SessionLocal() as session:
        receipts = (await session.scalars(select(Receipt).where(Receipt.source == "demo"))).all()
        for receipt in receipts:
            await session.delete(receipt)
        await session.execute(delete(ProductAlias))
        await session.execute(delete(Product))
        await session.commit()
        print(f"removed {len(receipts)} demo receipts and the demo product catalogue")


async def generate(months: int, seed: int) -> None:
    random.seed(seed)

    async with SessionLocal() as session:
        await seed_categories(session)
        categories = {c.slug: c for c in (await session.scalars(select(Category))).all()}

        products: dict[str, Product] = {}
        for name, raw_name, slug, *_ in BASKET:
            product = await session.scalar(select(Product).where(Product.canonical_name == name))
            if product is None:
                product = Product(
                    canonical_name=name,
                    category_id=categories[slug].id if slug in categories else None,
                )
                session.add(product)
                await session.flush()
            products[raw_name] = product

        merchants: dict[str, Merchant] = {}
        for shop in SHOPS:
            merchant = await resolve_merchant(session, shop)
            merchants[shop] = merchant
            for _, raw_name, *_ in BASKET:
                session.add(
                    ProductAlias(
                        product_id=products[raw_name].id,
                        merchant_id=merchant.id,
                        raw_name=raw_name,
                    )
                )
        await session.flush()

        now = datetime.now(timezone.utc)
        created = 0

        for month_offset in range(months, 0, -1):
            for _ in range(random.randint(3, 6)):
                shop = random.choice(SHOPS)
                merchant = merchants[shop]
                factor = SHOP_FACTOR.get(merchant.name, 1.0)
                age_months = month_offset - 1
                purchased_at = now - timedelta(
                    days=age_months * 30 + random.randint(0, 27),
                    hours=random.randint(8, 20),
                )

                receipt = Receipt(
                    id=uuid.uuid4(),
                    image_path="(demo)",
                    image_sha256=uuid.uuid4().hex + uuid.uuid4().hex[:0].ljust(0, "0"),
                    image_bytes=0,
                    source="demo",
                    merchant_id=merchant.id,
                    merchant_raw_name=shop,
                    purchased_at=purchased_at,
                    currency="HUF",
                    payment_method=random.choice(["cash", "card", "card"]),
                    status=ReceiptStatus.CONFIRMED.value,
                    confidence=round(random.uniform(0.88, 0.99), 2),
                    parsed_at=purchased_at,
                    confirmed_at=purchased_at,
                )
                session.add(receipt)
                await session.flush()

                total = Decimal("0.00")
                chosen = random.sample(BASKET, random.randint(3, 7))

                for line_no, (_, raw_name, slug, base, vat, drift) in enumerate(chosen, start=1):
                    # Prices drift upwards as the months approach the present.
                    inflated = base * (1 + drift / 100) ** (months - age_months)
                    unit_price = Decimal(
                        str(round(inflated * factor * random.uniform(0.97, 1.03), 0))
                    )
                    quantity = Decimal(str(random.choice([1, 1, 1, 2, 2, 3])))
                    gross = (unit_price * quantity).quantize(Decimal("0.01"))
                    total += gross

                    session.add(
                        ReceiptItem(
                            receipt_id=receipt.id,
                            line_no=line_no,
                            raw_name=raw_name,
                            quantity=quantity,
                            unit="db",
                            unit_price=unit_price,
                            gross_amount=gross,
                            vat_rate=Decimal(str(vat)),
                            kind=LineKind.ITEM.value,
                            product_id=products[raw_name].id,
                            category_id=categories[slug].id if slug in categories else None,
                            confidence=round(random.uniform(0.85, 0.99), 2),
                        )
                    )

                rounding = Decimal("0.00")
                if receipt.payment_method == "cash":
                    remainder = int(total) % 5
                    rounding = Decimal(str(-remainder if remainder <= 2 else 5 - remainder))
                    session.add(
                        ReceiptItem(
                            receipt_id=receipt.id, line_no=len(chosen) + 1, raw_name="KEREKÍTÉS",
                            gross_amount=rounding, kind=LineKind.ROUNDING.value, confidence=0.99,
                        )
                    )

                receipt.total_gross = (total + rounding).quantize(Decimal("0.01"))
                receipt.rounding = rounding
                receipt.discount_total = Decimal("0.00")

                session.add(
                    ExtractionAttempt(
                        receipt_id=receipt.id, extractor="claude", model="claude-opus-5",
                        succeeded=True, input_tokens=random.randint(2600, 3400),
                        output_tokens=random.randint(900, 1600),
                        cache_read_tokens=1300,
                        cost_usd=Decimal(str(round(random.uniform(0.035, 0.06), 6))),
                        latency_ms=random.randint(3500, 9000),
                        created_at=purchased_at,
                    )
                )
                created += 1

        await session.commit()
        print(f"created {created} demo receipts across {months} months")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--clear", action="store_true", help="remove demo data and exit")
    parser.add_argument("--yes", action="store_true", help="required, to avoid an accidental run")
    args = parser.parse_args()

    if args.clear:
        asyncio.run(clear())
        return
    if not args.yes:
        parser.error("this writes to the database; pass --yes if you mean it")
    asyncio.run(generate(args.months, args.seed))


if __name__ == "__main__":
    main()
