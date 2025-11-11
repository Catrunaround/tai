#!/usr/bin/env python3
"""
Script to restructure CS 61A files based on groundtruth folder structure.

The groundtruth folder contains empty .txt files with filenames that represent
the actual file structure. This script:
1. Scans the groundtruth directory for .txt files
2. Extracts the original filename by removing .txt extension
3. Searches for matching files in the source directory
4. Copies them to the corresponding location in the output directory
"""

import os
import shutil
import re
from pathlib import Path
from typing import Dict, List, Tuple
import argparse


class FileRestructurer:
    def __init__(self, source_dir: str, groundtruth_dir: str, output_dir: str):
        self.source_dir = Path(source_dir)
        self.groundtruth_dir = Path(groundtruth_dir)
        self.output_dir = Path(output_dir)
        self.file_index: Dict[str, List[Path]] = {}
        self.stats = {
            'total_groundtruth': 0,
            'found': 0,
            'not_found': 0,
            'copied': 0,
            'errors': 0
        }

    def build_source_file_index(self):
        """Build an index of all files in the source directory for fast lookup."""
        print(f"Building file index from {self.source_dir}...")
        for file_path in self.source_dir.rglob('*'):
            if file_path.is_file():
                filename = file_path.name
                if filename not in self.file_index:
                    self.file_index[filename] = []
                self.file_index[filename].append(file_path)
        print(f"Indexed {len(self.file_index)} unique filenames")

    def extract_original_filename(self, txt_filename: str) -> str:
        """Extract original filename by removing .txt extension and (1), (2), etc. patterns."""
        if txt_filename.endswith('.txt'):
            filename = txt_filename[:-4]
        else:
            filename = txt_filename

        # Remove patterns like (1), (2), (10), etc. from filename
        # Pattern matches: space + parenthesis + digits + parenthesis before file extension
        filename = re.sub(r'\s*\(\d+\)(?=\.[^.]+$|$)', '', filename)

        return filename

    def find_source_file(self, original_filename: str, groundtruth_rel_path: Path) -> Path | None:
        """
        Find the source file that matches the original filename.
        Uses relative path context to disambiguate when multiple files exist.
        """
        if original_filename not in self.file_index:
            return None

        candidates = self.file_index[original_filename]

        # If only one candidate, return it
        if len(candidates) == 1:
            return candidates[0]

        # Multiple candidates - try to match based on relative path context
        # Extract directory structure from groundtruth path
        gt_parts = str(groundtruth_rel_path.parent).split(os.sep)

        best_match = None
        best_score = -1

        for candidate in candidates:
            # Get relative path from source directory
            rel_path = candidate.relative_to(self.source_dir)
            candidate_parts = str(rel_path.parent).split(os.sep)

            # Score based on matching directory names
            score = sum(1 for part in gt_parts if part in candidate_parts)

            if score > best_score:
                best_score = score
                best_match = candidate

        return best_match

    def process_groundtruth_file(self, gt_file_path: Path) -> Tuple[bool, str]:
        """
        Process a single groundtruth .txt file.
        Returns (success, message) tuple.
        """
        # Get relative path from groundtruth directory
        rel_path = gt_file_path.relative_to(self.groundtruth_dir)

        # Extract original filename
        original_filename = self.extract_original_filename(gt_file_path.name)

        # Find matching source file
        source_file = self.find_source_file(original_filename, rel_path)

        if source_file is None:
            return False, f"Not found: {original_filename}"

        # Create output path (same relative structure, but with original filename)
        output_path = self.output_dir / rel_path.parent / original_filename

        # Create parent directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the file
        try:
            shutil.copy2(source_file, output_path)
            return True, f"Copied: {original_filename}"
        except Exception as e:
            return False, f"Error copying {original_filename}: {str(e)}"

    def restructure(self, dry_run: bool = False):
        """Main restructuring process."""
        print(f"\n{'=' * 80}")
        print(f"CS 61A File Restructuring")
        print(f"{'=' * 80}")
        print(f"Source:      {self.source_dir}")
        print(f"Groundtruth: {self.groundtruth_dir}")
        print(f"Output:      {self.output_dir}")
        print(f"Mode:        {'DRY RUN' if dry_run else 'LIVE'}")
        print(f"{'=' * 80}\n")

        # Build file index
        self.build_source_file_index()

        # Find all .txt files in groundtruth directory
        print(f"\nScanning groundtruth directory for .txt files...")
        groundtruth_files = list(self.groundtruth_dir.rglob('*.txt'))
        self.stats['total_groundtruth'] = len(groundtruth_files)
        print(f"Found {self.stats['total_groundtruth']} files to process\n")

        if dry_run:
            print("DRY RUN MODE - No files will be copied\n")

        # Process each groundtruth file
        not_found_files = []
        error_files = []

        for i, gt_file in enumerate(groundtruth_files, 1):
            success, message = self.process_groundtruth_file(gt_file)

            if success:
                self.stats['found'] += 1
                if not dry_run:
                    self.stats['copied'] += 1
                if i % 100 == 0:
                    print(f"Progress: {i}/{self.stats['total_groundtruth']} ({i*100//self.stats['total_groundtruth']}%)")
            else:
                if "Not found" in message:
                    self.stats['not_found'] += 1
                    not_found_files.append(message)
                else:
                    self.stats['errors'] += 1
                    error_files.append(message)

        # Print summary
        self.print_summary(not_found_files, error_files, dry_run)

    def print_summary(self, not_found_files: List[str], error_files: List[str], dry_run: bool):
        """Print processing summary."""
        print(f"\n{'=' * 80}")
        print(f"SUMMARY")
        print(f"{'=' * 80}")
        print(f"Total groundtruth files: {self.stats['total_groundtruth']}")
        print(f"Found in source:         {self.stats['found']}")
        print(f"Not found:               {self.stats['not_found']}")
        print(f"Errors:                  {self.stats['errors']}")
        if not dry_run:
            print(f"Successfully copied:     {self.stats['copied']}")
        print(f"{'=' * 80}\n")

        if not_found_files:
            print(f"\nFiles not found ({len(not_found_files)}):")
            print("-" * 80)
            for msg in not_found_files[:20]:  # Show first 20
                print(f"  {msg}")
            if len(not_found_files) > 20:
                print(f"  ... and {len(not_found_files) - 20} more")

        if error_files:
            print(f"\nErrors ({len(error_files)}):")
            print("-" * 80)
            for msg in error_files[:20]:  # Show first 20
                print(f"  {msg}")
            if len(error_files) > 20:
                print(f"  ... and {len(error_files) - 20} more")

        if dry_run:
            print("\nThis was a DRY RUN. No files were actually copied.")
            print("Run without --dry-run to perform the actual restructuring.")


def main():
    parser = argparse.ArgumentParser(
        description="Restructure CS 61A files based on groundtruth folder structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would happen
  python restructure_cs61a.py --dry-run

  # Actual restructuring with custom paths
  python restructure_cs61a.py \\
    --source "/path/to/CS 61A" \\
    --groundtruth "/path/to/CS61A_full_emptied_groundtruth" \\
    --output "/path/to/CS61A_restructured"
        """
    )

    parser.add_argument(
        '--source',
        default='/home/bot/bot/yk/YK_final/courses/CS 61A',
        help='Source directory containing CS 61A files (default: /home/bot/bot/yk/YK_final/courses/CS 61A)'
    )

    parser.add_argument(
        '--groundtruth',
        default='/home/bot/bot/yk/YK_final/CS61A_full_emptied_groundtruth',
        help='Groundtruth directory with .txt file structure (default: /home/bot/bot/yk/YK_final/CS61A_full_emptied_groundtruth)'
    )

    parser.add_argument(
        '--output',
        default='/home/bot/bot/yk/YK_final/CS61A_restructured',
        help='Output directory for restructured files (default: /home/bot/bot/yk/YK_final/CS61A_restructured)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Perform a dry run without actually copying files'
    )

    args = parser.parse_args()

    # Validate paths
    source_path = Path(args.source)
    groundtruth_path = Path(args.groundtruth)

    if not source_path.exists():
        print(f"Error: Source directory does not exist: {source_path}")
        return 1

    if not groundtruth_path.exists():
        print(f"Error: Groundtruth directory does not exist: {groundtruth_path}")
        return 1

    # Create restructurer and run
    restructurer = FileRestructurer(
        source_dir=str(source_path),
        groundtruth_dir=str(groundtruth_path),
        output_dir=args.output
    )

    try:
        restructurer.restructure(dry_run=args.dry_run)
        return 0
    except Exception as e:
        print(f"\nFatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
