#!/usr/bin/env python3
"""
Upstream Sync Analysis Script

Analyzes differences between fork and upstream repository to identify
potential merge conflicts and generate a detailed report.
"""

import subprocess
import sys
import os
from datetime import datetime
from typing import NamedTuple


class SyncAnalysis(NamedTuple):
    fork_point: str
    fork_files: set[str]
    upstream_files: set[str]
    conflict_files: set[str]
    safe_upstream_files: set[str]
    safe_fork_files: set[str]
    upstream_commits: list[str]


def run_git(args: list[str]) -> str:
    """Run a git command and return output."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        check=False
    )
    return result.stdout.strip()


def get_fork_point() -> str:
    """Find the common ancestor between fork and upstream."""
    # Try merge-base first
    fork_point = run_git(["merge-base", "origin/main", "upstream/main"])
    if fork_point:
        return fork_point

    # Fallback: find first common commit
    # This handles cases where histories have diverged significantly
    upstream_commits = set(run_git(["rev-list", "upstream/main"]).split("\n"))
    for commit in run_git(["rev-list", "origin/main"]).split("\n"):
        if commit in upstream_commits:
            return commit

    # Last resort: use oldest commit
    return run_git(["rev-list", "--max-parents=0", "HEAD"])


def get_changed_files(from_ref: str, to_ref: str) -> set[str]:
    """Get list of files changed between two refs."""
    output = run_git(["diff", "--name-only", f"{from_ref}..{to_ref}"])
    if not output:
        return set()
    return set(output.split("\n"))


def get_commit_log(from_ref: str, to_ref: str, limit: int = 50) -> list[str]:
    """Get commit log between two refs."""
    output = run_git([
        "log", "--oneline", "--no-merges",
        f"-{limit}", f"{from_ref}..{to_ref}"
    ])
    if not output:
        return []
    return output.split("\n")


def get_file_diff(from_ref: str, to_ref: str, filepath: str, max_lines: int = 50) -> str:
    """Get diff for a specific file between two refs."""
    diff = run_git(["diff", f"{from_ref}..{to_ref}", "--", filepath])
    lines = diff.split("\n")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    return diff


def analyze_sync() -> SyncAnalysis:
    """Perform the sync analysis."""
    fork_point = get_fork_point()

    # Files changed in fork since fork point
    fork_files = get_changed_files(fork_point, "origin/main")

    # Files changed in upstream since fork point
    upstream_files = get_changed_files(fork_point, "upstream/main")

    # Files modified in both (potential conflicts)
    conflict_files = fork_files & upstream_files

    # Safe files (only changed in one place)
    safe_upstream_files = upstream_files - fork_files
    safe_fork_files = fork_files - upstream_files

    # Recent upstream commits
    upstream_commits = get_commit_log(fork_point, "upstream/main")

    return SyncAnalysis(
        fork_point=fork_point,
        fork_files=fork_files,
        upstream_files=upstream_files,
        conflict_files=conflict_files,
        safe_upstream_files=safe_upstream_files,
        safe_fork_files=safe_fork_files,
        upstream_commits=upstream_commits
    )


def generate_report(analysis: SyncAnalysis) -> str:
    """Generate markdown report from analysis."""
    date = datetime.now().strftime("%Y-%m-%d")

    # Check if there's anything to report
    force_report = os.environ.get("FORCE_REPORT", "false").lower() == "true"
    if not analysis.upstream_files and not force_report:
        return ""  # No changes, no report needed

    lines = [
        f"# Upstream Sync Report - {date}",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Your customized files | {len(analysis.fork_files)} |",
        f"| Upstream changed files | {len(analysis.upstream_files)} |",
        f"| Potential conflicts | {len(analysis.conflict_files)} |",
        f"| Safe to merge | {len(analysis.safe_upstream_files)} |",
        "",
        f"**Fork point:** `{analysis.fork_point[:8]}`",
        "",
    ]

    # Conflicts section
    if analysis.conflict_files:
        lines.extend([
            "## Potential Conflicts",
            "",
            "These files were modified in **BOTH** your fork AND upstream.",
            "You will need to manually review and merge these changes.",
            "",
        ])

        for i, filepath in enumerate(sorted(analysis.conflict_files), 1):
            diff = get_file_diff(analysis.fork_point, "upstream/main", filepath)
            lines.extend([
                f"### {i}. `{filepath}`",
                "",
                "<details>",
                "<summary>View upstream changes</summary>",
                "",
                "```diff",
                diff if diff else "(no diff available)",
                "```",
                "",
                "</details>",
                "",
            ])
    else:
        lines.extend([
            "## No Conflicts Detected",
            "",
            "None of the upstream changes affect files you've customized.",
            "",
        ])

    # Safe upstream updates
    if analysis.safe_upstream_files:
        lines.extend([
            "## Safe Upstream Updates",
            "",
            "These upstream changes don't affect your customizations:",
            "",
            "<details>",
            "<summary>View all safe updates ({} files)</summary>".format(len(analysis.safe_upstream_files)),
            "",
        ])
        for filepath in sorted(analysis.safe_upstream_files):
            lines.append(f"- `{filepath}`")
        lines.extend([
            "",
            "</details>",
            "",
        ])

    # Your customizations
    if analysis.safe_fork_files:
        lines.extend([
            "## Your Customizations (untouched by upstream)",
            "",
            "These files you've modified are not affected by upstream changes:",
            "",
            "<details>",
            "<summary>View your customizations ({} files)</summary>".format(len(analysis.safe_fork_files)),
            "",
        ])
        for filepath in sorted(analysis.safe_fork_files):
            lines.append(f"- `{filepath}`")
        lines.extend([
            "",
            "</details>",
            "",
        ])

    # Recent upstream commits
    if analysis.upstream_commits:
        lines.extend([
            "## Recent Upstream Commits",
            "",
            "<details>",
            "<summary>View recent commits ({} shown)</summary>".format(len(analysis.upstream_commits)),
            "",
            "```",
        ])
        lines.extend(analysis.upstream_commits)
        lines.extend([
            "```",
            "",
            "</details>",
            "",
        ])

    # Recommended actions
    lines.extend([
        "## Recommended Actions",
        "",
    ])

    if analysis.conflict_files:
        lines.extend([
            "1. **Review conflicts** listed above carefully",
            "2. **Create backup branch:**",
            "   ```bash",
            "   git checkout -b backup-$(date +%Y%m%d)",
            "   git checkout main",
            "   ```",
            "3. **Fetch and merge upstream:**",
            "   ```bash",
            "   git fetch upstream",
            "   git merge upstream/main",
            "   ```",
            "4. **Resolve conflicts** in your editor",
            "5. **Complete merge:**",
            "   ```bash",
            "   git add .",
            "   git commit -m \"Merge upstream/main\"",
            "   ```",
            "6. **Test** your customizations still work",
            "7. **Push** to your fork:",
            "   ```bash",
            "   git push origin main",
            "   ```",
        ])
    else:
        lines.extend([
            "No conflicts detected! You can safely merge upstream:",
            "",
            "```bash",
            "git fetch upstream",
            "git merge upstream/main",
            "git push origin main",
            "```",
        ])

    lines.extend([
        "",
        "---",
        f"*Generated by Upstream Sync Monitor on {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}*",
    ])

    return "\n".join(lines)


def main():
    """Main entry point."""
    try:
        analysis = analyze_sync()
        report = generate_report(analysis)
        print(report)
    except Exception as e:
        print(f"Error during analysis: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
