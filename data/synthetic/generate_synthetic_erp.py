"""
data/synthetic/generate_synthetic_erp.py

Generates realistic synthetic ERP invoice data for development and testing.

Features:
- Realistic procurement patterns (seasonal variance, repeat suppliers)
- Supplier name variants (intentional duplicates for ER testing)
- Geographic distribution
- Multiple commodity categories
- Configurable volume

Usage:
    python data/synthetic/generate_synthetic_erp.py \
        --num-suppliers 50 \
        --num-invoices 500 \
        --output data/raw/erp_invoices/synthetic_invoices.csv \
        --seed 42
"""

import argparse
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Configuration
COMPANIES = [
    "Apple Inc",
    "Microsoft Corporation",
    "Samsung Electronics",
    "NVIDIA Corporation",
    "H&M Group",
    "Tesla Inc",
    "Google/Alphabet",
    "Intel Corporation",
]

COMMODITIES = {
    "Electronics": {
        "avg_price": 5000,
        "std_price": 2000,
        "suppliers": ["Taiwan Semiconductor", "SK Hynix", "Micron Tech"],
    },
    "Steel": {
        "avg_price": 15000,
        "std_price": 5000,
        "suppliers": ["ArcelorMittal", "POSCO", "Nippon Steel", "Global Steel"],
    },
    "Chemicals": {
        "avg_price": 8000,
        "std_price": 3000,
        "suppliers": ["BASF", "Dow Chemical", "LyondellBasell"],
    },
    "Textiles": {
        "avg_price": 3000,
        "std_price": 1500,
        "suppliers": ["Huntsman", "Archroma", "DyStar"],
    },
    "Energy": {
        "avg_price": 20000,
        "std_price": 8000,
        "suppliers": ["Shell", "BP", "Exxon Mobil", "Saudi Aramco"],
    },
}

COUNTRIES = {
    "China": {"weight": 0.35, "cost_factor": 0.8},
    "India": {"weight": 0.15, "cost_factor": 0.75},
    "Vietnam": {"weight": 0.15, "cost_factor": 0.8},
    "USA": {"weight": 0.15, "cost_factor": 1.2},
    "Germany": {"weight": 0.1, "cost_factor": 1.15},
    "Japan": {"weight": 0.1, "cost_factor": 1.1},
}

MONTHS_PATTERN = {
    1: 0.8,
    2: 0.75,
    3: 0.9,
    4: 0.95,
    5: 1.0,
    6: 1.05,
    7: 1.1,
    8: 1.15,
    9: 1.1,
    10: 1.05,
    11: 1.2,
    12: 1.3,  # Holiday season
}


class SupplierGenerator:
    """
    Generates realistic supplier names with intentional variants
    for entity resolution testing.
    """

    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        self.variants_cache = {}

    def generate_supplier_base_names(self, count: int) -> List[str]:
        """Generate base supplier names from commodity data."""
        base_names = []
        for commodity, data in COMMODITIES.items():
            base_names.extend(data["suppliers"])

        # Generate additional random names
        suffixes = ["Corp", "Ltd", "Inc", "Group", "Industries", "Manufacturing"]
        prefixes = ["Global", "Euro", "Asian", "Pacific", "North", "South"]

        while len(base_names) < count:
            prefix = random.choice(prefixes)
            suffix = random.choice(suffixes)
            category = random.choice(list(COMMODITIES.keys()))
            name = f"{prefix} {category} {suffix}"
            if name not in base_names:
                base_names.append(name)

        return base_names[:count]

    def generate_supplier_variants(self, base_name: str, num_variants: int = 2) -> List[str]:
        """
        Generate realistic variants of a supplier name.
        
        Examples:
            "Global Steel Ltd" → ["GlobalSteel_Ltd", "Global Steel Corporation"]
        """
        if base_name in self.variants_cache:
            return self.variants_cache[base_name]

        variants = [base_name]

        # Variant 1: Remove spaces, add underscore
        variants.append(base_name.replace(" ", "_"))

        # Variant 2: Abbreviate
        words = base_name.split()
        if len(words) >= 2:
            abbrev = "".join(w[0].upper() for w in words)
            variants.append(abbrev)

        # Variant 3: Alternative name
        if "Ltd" in base_name:
            variants.append(base_name.replace("Ltd", "Limited"))
        elif "Inc" in base_name:
            variants.append(base_name.replace("Inc", "Incorporated"))
        elif "Corp" in base_name:
            variants.append(base_name.replace("Corp", "Corporation"))

        # Variant 4: Add location suffix
        country = random.choice(list(COUNTRIES.keys()))
        if random.random() > 0.5:
            variants.append(f"{base_name} {country}")

        variants = list(dict.fromkeys(variants))[:num_variants]  # Deduplicate
        self.variants_cache[base_name] = variants
        return variants


class InvoiceGenerator:
    """
    Generates realistic invoices with proper temporal and commodity distribution.
    """

    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        self.supplier_gen = SupplierGenerator(seed)
        self.invoice_counter = 0

    def generate_invoices(
        self,
        num_invoices: int,
        num_suppliers: int,
        date_start: str = "2023-01-01",
        date_end: str = "2024-12-31",
    ) -> pd.DataFrame:
        """
        Generate invoice dataframe.

        Args:
            num_invoices: Total invoices to generate
            num_suppliers: Number of unique suppliers
            date_start: Start date for invoices
            date_end: End date for invoices

        Returns:
            pd.DataFrame with columns: invoice_id, invoice_date, buyer_id, buyer_name,
                                      supplier_id, supplier_name, commodity_category,
                                      volume_usd, invoice_qty, unit_of_measure, country
        """
        logger.info(
            f"Generating {num_invoices} invoices from {num_suppliers} suppliers"
        )

        # Generate supplier base names and variants
        supplier_bases = self.supplier_gen.generate_supplier_base_names(
            num_suppliers
        )

        # Create supplier mapping with variants
        supplier_mapping = {}
        canonical_supplier_id = 1
        for base_name in supplier_bases:
            variants = self.supplier_gen.generate_supplier_variants(
                base_name, num_variants=random.randint(1, 3)
            )
            for variant in variants:
                supplier_mapping[variant] = {
                    "id": f"SUP_{canonical_supplier_id:06d}",
                    "base_name": base_name,
                    "country": random.choices(
                        list(COUNTRIES.keys()),
                        weights=[
                            COUNTRIES[c]["weight"]
                            for c in COUNTRIES.keys()
                        ],
                    )[0],
                }
            canonical_supplier_id += 1

        # Parse dates
        start_date = datetime.strptime(date_start, "%Y-%m-%d")
        end_date = datetime.strptime(date_end, "%Y-%m-%d")
        date_range = (end_date - start_date).days

        invoices = []
        supplier_names = list(supplier_mapping.keys())

        for i in range(num_invoices):
            # Random date within range
            random_days = random.randint(0, date_range)
            invoice_date = start_date + timedelta(days=random_days)

            # Seasonal adjustment
            seasonal_factor = MONTHS_PATTERN.get(invoice_date.month, 1.0)

            # Pick commodity category
            commodity = random.choice(list(COMMODITIES.keys()))
            commodity_data = COMMODITIES[commodity]

            # Pick supplier (with bias toward repeat customers)
            if random.random() < 0.6 and i > 50:
                # Reuse previous supplier (create repeat orders)
                supplier_name = random.choice(supplier_names[:min(i, 20)])
            else:
                supplier_name = random.choice(supplier_names)

            supplier_info = supplier_mapping[supplier_name]

            # Calculate amount with realistic variance
            base_amount = np.random.normal(
                commodity_data["avg_price"],
                commodity_data["std_price"],
            )
            base_amount = max(100, base_amount)  # Minimum $100
            cost_factor = COUNTRIES[supplier_info["country"]]["cost_factor"]
            invoice_amount = base_amount * seasonal_factor * cost_factor

            # Determine unit of measure
            unit_of_measure = (
                "tonnes"
                if commodity
                in ["Steel", "Chemicals"]
                else "units"
            )
            quantity = invoice_amount / (100 if unit_of_measure == "tonnes" else 10)

            # Pick buyer company
            buyer_name = random.choice(COMPANIES)
            buyer_id = f"BUY_{hash(buyer_name) % 10000:06d}"

            invoices.append(
                {
                    "invoice_id": f"INV_{self.invoice_counter:08d}",
                    "invoice_date": invoice_date.strftime("%Y-%m-%d"),
                    "buyer_id": buyer_id,
                    "buyer_name": buyer_name,
                    "supplier_id": supplier_info["id"],
                    "supplier_name": supplier_name,
                    "commodity_category": commodity,
                    "volume_usd": round(invoice_amount, 2),
                    "invoice_qty": round(quantity, 2),
                    "unit_of_measure": unit_of_measure,
                    "country": supplier_info["country"],
                }
            )
            self.invoice_counter += 1

        df = pd.DataFrame(invoices)
        logger.info(f"✅ Generated {len(df)} invoices")
        return df

    def validate_dataframe(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """
        Validate generated invoice dataframe.

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        # Check required columns
        required_cols = [
            "invoice_id",
            "invoice_date",
            "buyer_id",
            "buyer_name",
            "supplier_id",
            "supplier_name",
            "commodity_category",
            "volume_usd",
            "invoice_qty",
            "unit_of_measure",
            "country",
        ]
        missing_cols = set(required_cols) - set(df.columns)
        if missing_cols:
            errors.append(f"Missing columns: {missing_cols}")

        # Check data types
        if "invoice_date" in df.columns:
            try:
                pd.to_datetime(df["invoice_date"])
            except Exception as e:
                errors.append(f"Invalid dates: {e}")

        if "volume_usd" in df.columns:
            if (df["volume_usd"] <= 0).any():
                errors.append("Found non-positive invoice amounts")

        # Check for duplicates
        if df.duplicated(subset=["invoice_id"]).any():
            errors.append("Duplicate invoice IDs found")

        # Check uniqueness ratios
        unique_suppliers = df["supplier_name"].nunique()
        unique_buyers = df["buyer_name"].nunique()
        logger.info(
            f"Data quality: {unique_suppliers} unique suppliers, "
            f"{unique_buyers} unique buyers"
        )

        return len(errors) == 0, errors


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic ERP invoice data for testing"
    )
    parser.add_argument(
        "--num-suppliers",
        type=int,
        default=50,
        help="Number of unique suppliers",
    )
    parser.add_argument(
        "--num-invoices",
        type=int,
        default=500,
        help="Number of invoices to generate",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/erp_invoices/synthetic_invoices.csv"),
        help="Output CSV path",
    )
    parser.add_argument(
        "--date-start",
        default="2023-01-01",
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--date-end",
        default="2024-12-31",
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate output after generation",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
    )

    # Create output directory
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Generate invoices
    generator = InvoiceGenerator(seed=args.seed)
    df = generator.generate_invoices(
        num_invoices=args.num_invoices,
        num_suppliers=args.num_suppliers,
        date_start=args.date_start,
        date_end=args.date_end,
    )

    # Validate if requested
    if args.validate:
        is_valid, errors = generator.validate_dataframe(df)
        if not is_valid:
            logger.error("Validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            return 1

    # Save
    df.to_csv(args.output, index=False)
    logger.info(f"Saved to {args.output}")

    # Print summary
    print(f"\n Generation Summary")
    print(f"  Invoices: {len(df)}")
    print(f"  Unique suppliers: {df['supplier_name'].nunique()}")
    print(f"  Unique buyers: {df['buyer_name'].nunique()}")
    print(f"  Date range: {df['invoice_date'].min()} to {df['invoice_date'].max()}")
    print(f"  Total USD: ${df['volume_usd'].sum():,.2f}")
    print(f"\n Output: {args.output}")

    return 0


if __name__ == "__main__":
    exit(main())