#!/usr/bin/env python3
"""
One-time script to compress CSV files to gzip format.

This compresses all CSV files in the results directory to .csv.gz files,
achieving ~60-70x compression on k6 output data.

Usage:
    python compress_results.py

After running, commit the .csv.gz files and add *.csv to .gitignore.
"""

import gzip
import shutil
from pathlib import Path


def compress_csv_files(results_dir: Path = Path("results")):
    """Compress all CSV files in results directory to gzip format."""
    csv_files = list(results_dir.glob("**/*.csv"))

    if not csv_files:
        print("No CSV files found in results directory.")
        return

    print(f"Found {len(csv_files)} CSV files to compress.\n")

    total_original = 0
    total_compressed = 0

    for csv_path in csv_files:
        gz_path = csv_path.with_suffix(".csv.gz")

        # Get original size
        original_size = csv_path.stat().st_size
        total_original += original_size

        # Compress the file
        with open(csv_path, "rb") as f_in:
            with gzip.open(gz_path, "wb", compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Get compressed size
        compressed_size = gz_path.stat().st_size
        total_compressed += compressed_size

        ratio = original_size / compressed_size if compressed_size > 0 else 0
        print(
            f"{csv_path.name}: "
            f"{original_size / 1024 / 1024:.1f} MB -> "
            f"{compressed_size / 1024 / 1024:.1f} MB "
            f"({ratio:.0f}x compression)"
        )

    print(f"\n{'='*60}")
    print(f"Total: {total_original / 1024 / 1024:.1f} MB -> {total_compressed / 1024 / 1024:.1f} MB")
    print(f"Overall compression ratio: {total_original / total_compressed:.0f}x")
    print(f"\nCompressed files saved alongside originals (.csv.gz)")
    print(f"You can now:")
    print(f"  1. Add 'results/**/*.csv' to .gitignore")
    print(f"  2. Run: git add results/**/*.csv.gz")
    print(f"  3. Commit and push to GitHub")


if __name__ == "__main__":
    compress_csv_files()
