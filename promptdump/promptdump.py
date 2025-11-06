import fnmatch
import os
import sys
import argparse
from collections.abc import Iterable


def parse_exclusion_file(file_path: str) -> set[str]:
    patterns = set()
    if file_path and os.path.exists(file_path):
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.add(line)
    patterns.add(".git")
    patterns.add(".vscode")
    return patterns


def is_excluded(path: str, exclusion_patterns: set[str]) -> bool:
    path_parts = path.split(os.sep)
    
    for pattern in exclusion_patterns:
        if pattern.startswith("/") and pattern.endswith("/"):
            # Pattern like "/dir/" - matches only at root level
            dir_name = pattern[1:-1]
            if path.startswith(dir_name + os.sep) or path == dir_name:
                return True
        elif pattern.endswith("/"):
            # Pattern like "dir/" - matches directory at any level
            dir_name = pattern[:-1]
            if dir_name in path_parts:
                return True
        elif pattern.startswith("/"):
            # Pattern like "/file" - matches only at root level
            file_name = pattern[1:]
            if path == file_name or path.startswith(file_name + os.sep):
                return True
        else:
            # Pattern without slashes - use fnmatch for files/dirs at any level
            if fnmatch.fnmatch(path, pattern) or any(fnmatch.fnmatch(part, pattern) for part in path_parts):
                return True
    return False


def print_directory_structure(start_path: str, exclusion_patterns: set[str]) -> str:
    def _generate_tree(dir_path: str, prefix: str = "") -> list[str]:
        try:
            entries = os.listdir(dir_path)
        except (PermissionError, OSError):
            return []

        # Filter and sort entries
        filtered_entries = []
        for entry in entries:
            full_path = os.path.join(dir_path, entry)
            rel_path = os.path.relpath(full_path, start_path)
            if not is_excluded(rel_path, exclusion_patterns):
                filtered_entries.append(entry)

        filtered_entries.sort(key=lambda x: (not os.path.isdir(os.path.join(dir_path, x)), x.lower()))

        tree = []
        for i, entry in enumerate(filtered_entries):
            full_path = os.path.join(dir_path, entry)
            rel_path = os.path.relpath(full_path, start_path)
            is_last = i == len(filtered_entries) - 1

            if is_last:
                connector = "└── "
                new_prefix = prefix + "    "
            else:
                connector = "├── "
                new_prefix = prefix + "│   "

            if os.path.isdir(full_path):
                tree.append(f"{prefix}{connector}{rel_path}")
                tree.extend(_generate_tree(full_path, new_prefix))
            else:
                tree.append(f"{prefix}{connector}{rel_path}")
        return tree

    tree = ["/ "] + _generate_tree(start_path)
    return "\n".join(tree)


def process_file(file_path: str, rel_path: str, output: list[str], args: argparse.Namespace) -> None:
    """Process a single file and add its content to the output."""
    if args.verbose:
        print(f"Processing: {rel_path!r}", file=sys.stderr)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                output.append(f"### FILE {rel_path!r} IS EMPTY\n")
                return

            # Add file header with path and size
            file_size = os.path.getsize(file_path)
            output.append(f"### START OF FILE {rel_path!r}: {file_size:,d} bytes\n\n")

            # Add language identifier for syntax highlighting if the file type is known
            ext = os.path.splitext(rel_path)[1].lower()
            output.append(f"```{ext[1:]}")
            output.append(content)
            output.append("```")
            output.append(f"\n### END OF FILE {rel_path!r}")  # Add spacing between files

    except Exception as e:
        output.append(f"### ERROR READING FILE {rel_path!r}: {str(e)}")


def find_files_by_name(directory: str, filenames: Iterable[str]) -> list[str]:
    """Find all files in directory that match any of the given filenames."""
    matches = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file in filenames:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, directory)
                matches.append(rel_path)
    return matches


def make_prompt(args: argparse.Namespace) -> str:
    # Convert to absolute path
    start_path = os.path.abspath(args.directory)
    if not os.path.isdir(start_path):
        print(f"Error: Directory not found: {start_path}", file=sys.stderr)
        sys.exit(1)

    # Process exclusions
    exclusion_file = args.exclude if os.path.isfile(args.exclude) else None
    exclusion_patterns = parse_exclusion_file(exclusion_file) if exclusion_file else set()

    if args.verbose:
        print(f"Scanning directory: {start_path}", file=sys.stderr)
        if exclusion_file:
            print(f"Using exclusion patterns from: {exclusion_file}", file=sys.stderr)
        print(
            f"Including files with extensions: {', '.join(args.extensions) if args.extensions else 'all'}",
            file=sys.stderr,
        )
        if args.files:
            print(f"Including specific files: {', '.join(args.files)}", file=sys.stderr)

    # Process files
    output: list[str] = []

    # Add project header
    output.append(f"# Project: {os.path.basename(os.path.abspath(start_path))}\n")

    # Add directory structure
    output.append("## Directory Structure\n")
    output.append("```")
    output.append(print_directory_structure(start_path, exclusion_patterns))
    output.append("```\n")

    # Track which files we've already processed
    processed_files: set[str] = set()

    # Process specific files first
    output.append("## File contents\n")
    if args.files:
        for filename in args.files:
            # Handle direct file path
            if os.path.isfile(os.path.join(start_path, filename)):
                file_path = os.path.join(start_path, filename)
                rel_path = os.path.relpath(file_path, start_path)
                if not is_excluded(rel_path, exclusion_patterns):
                    process_file(file_path, rel_path, output, args)
                    processed_files.add(rel_path)
            else:
                # Search for files with this name in the directory tree
                for rel_path in find_files_by_name(start_path, [filename]):
                    if not is_excluded(rel_path, exclusion_patterns) and rel_path not in processed_files:
                        file_path = os.path.join(start_path, rel_path)
                        process_file(file_path, rel_path, output, args)
                        processed_files.add(rel_path)

    # Process files by extension
    if args.extensions:
        for root, _, files in os.walk(start_path):
            rel_path = os.path.relpath(root, start_path)
            if is_excluded(rel_path, exclusion_patterns):
                continue

            for file in files:
                file_rel_path = os.path.join(rel_path, file)

                # Skip if we've already processed this file or it's excluded
                if (
                    file_rel_path in processed_files
                    or is_excluded(file_rel_path, exclusion_patterns)
                    or not any(file.endswith(ext) for ext in args.extensions)
                ):
                    continue

                file_path = os.path.join(root, file)
                process_file(file_path, file_rel_path, output, args)
                processed_files.add(file_rel_path)

    # Join all output
    result = "\n".join(output)

    return result
