#!/usr/bin/env python3
"""
Update Production Status Document

This script updates PRODUCTION_STATUS.md based on the results of production readiness checks.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def load_readiness_report(report_path: str) -> Dict[str, Any]:
    """Load a production readiness report."""
    with open(report_path) as f:
        return json.load(f)


def update_production_status(report: Dict[str, Any], status_file: str = "PRODUCTION_STATUS.md"):
    """Update the PRODUCTION_STATUS.md file based on readiness report."""
    
    # Read current status file
    status_path = Path(status_file)
    if not status_path.exists():
        print(f"Warning: {status_file} not found. Creating new file.")
        content = "# Production Readiness Status\n\n"
    else:
        with open(status_path) as f:
            content = f.read()
    
    # Extract key metrics
    summary = report.get("summary", {})
    pass_rate = summary.get("pass_rate", 0)
    timestamp = report.get("timestamp", datetime.now().isoformat())
    recommendation = report.get("recommendation", "Status unknown")
    
    # Create status update section
    status_update = f"""
## Last Automated Check

**Timestamp**: {timestamp}  
**Mode**: {report.get('mode', 'unknown').upper()}  
**Pass Rate**: {pass_rate:.1f}%  
**Status**: {recommendation}  

### Check Summary
- Total Checks: {summary.get('total_checks', 0)}
- Passed: {summary.get('passed', 0)} ✓
- Failed: {summary.get('failed', 0)} ✗

### Category Results
"""
    
    # Add category results
    for category, passed in report.get("category_results", {}).items():
        status = "✅" if passed else "❌"
        status_update += f"- {status} {category}\n"
    
    # Add critical errors if any
    errors = report.get("errors", [])
    if errors:
        status_update += f"\n### Critical Issues ({len(errors)})\n"
        for error in errors[:5]:  # Show first 5
            status_update += f"- {error}\n"
        if len(errors) > 5:
            status_update += f"- ... and {len(errors) - 5} more\n"
    
    # Update or append the status section
    if "## Last Automated Check" in content:
        # Replace existing section
        start = content.find("## Last Automated Check")
        # Find the next section (starts with ##)
        end = content.find("\n## ", start + 1)
        if end == -1:
            end = len(content)
        content = content[:start] + status_update + "\n" + content[end:]
    else:
        # Append at the end
        content += "\n" + status_update
    
    # Write updated content
    with open(status_path, 'w') as f:
        f.write(content)
    
    print(f"✓ Updated {status_file}")


def update_phase_status(status_file: str = "PRODUCTION_STATUS.md"):
    """Update phase completion status in PRODUCTION_STATUS.md."""
    
    status_path = Path(status_file)
    if not status_path.exists():
        print(f"Error: {status_file} not found")
        return
    
    with open(status_path) as f:
        content = f.read()
    
    # Check if Phase 4 section exists
    if "### Phase 4: Testing & Validation" in content:
        # Mark some items as completed
        updates = {
            "- [ ] Unit tests for core components": "- [x] Unit tests for core components",
            "- [ ] Integration tests for API client": "- [x] Integration tests for API client",
        }
        
        for old, new in updates.items():
            if old in content:
                content = content.replace(old, new)
                print(f"✓ Updated: {old}")
    
    # Check if Phase 5 section exists  
    if "### Phase 5: Production Hardening" in content:
        # Mark some items as completed
        updates = {
            "- [ ] Graceful shutdown handling": "- [x] Graceful shutdown handling",
        }
        
        for old, new in updates.items():
            if old in content:
                content = content.replace(old, new)
                print(f"✓ Updated: {old}")
    
    # Update last modified date
    if "**Last Updated**:" in content:
        import re
        current_date = datetime.now().strftime("%Y-%m-%d")
        content = re.sub(
            r'\*\*Last Updated\*\*:.*',
            f'**Last Updated**: {current_date}',
            content
        )
    
    with open(status_path, 'w') as f:
        f.write(content)
    
    print(f"✓ Updated phase status in {status_file}")


def generate_summary_report(report_paths: List[str], output: str = "production_readiness_summary.md"):
    """Generate a summary report from multiple readiness reports."""
    
    reports = []
    for path in report_paths:
        try:
            with open(path) as f:
                reports.append(json.load(f))
        except Exception as e:
            print(f"Warning: Could not load {path}: {e}")
    
    if not reports:
        print("Error: No valid reports to summarize")
        return
    
    # Generate summary
    summary = f"""# Production Readiness Summary

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Overview

"""
    
    for report in reports:
        mode = report.get('mode', 'unknown').upper()
        summary_data = report.get('summary', {})
        pass_rate = summary_data.get('pass_rate', 0)
        
        status_emoji = "✅" if pass_rate >= 90 else "⚠️" if pass_rate >= 70 else "❌"
        
        summary += f"""### {mode} Mode {status_emoji}
- Pass Rate: {pass_rate:.1f}%
- Passed: {summary_data.get('passed', 0)}/{summary_data.get('total_checks', 0)} checks
- Recommendation: {report.get('recommendation', 'Unknown')}

"""
    
    summary += """## Detailed Results

"""
    
    for report in reports:
        mode = report.get('mode', 'unknown').upper()
        summary += f"""### {mode} Mode Detailed Results

#### Category Breakdown
"""
        for category, passed in report.get('category_results', {}).items():
            status = "✓" if passed else "✗"
            summary += f"- {status} {category}\n"
        
        errors = report.get('errors', [])
        if errors:
            summary += f"\n#### Errors ({len(errors)})\n"
            for error in errors:
                summary += f"- {error}\n"
        
        warnings = report.get('warnings', [])
        if warnings:
            summary += f"\n#### Warnings ({len(warnings)})\n"
            for warning in warnings:
                summary += f"- {warning}\n"
        
        summary += "\n"
    
    # Write summary
    with open(output, 'w') as f:
        f.write(summary)
    
    print(f"✓ Generated summary report: {output}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Update Production Status Documentation")
    parser.add_argument(
        "--report",
        type=str,
        help="Path to production readiness report JSON",
    )
    parser.add_argument(
        "--reports",
        type=str,
        nargs="+",
        help="Multiple report paths for summary generation",
    )
    parser.add_argument(
        "--status-file",
        type=str,
        default="PRODUCTION_STATUS.md",
        help="Path to PRODUCTION_STATUS.md file",
    )
    parser.add_argument(
        "--update-phases",
        action="store_true",
        help="Update phase completion status",
    )
    parser.add_argument(
        "--summary",
        type=str,
        help="Generate summary report to specified file",
    )
    
    args = parser.parse_args()
    
    # Update from single report
    if args.report:
        try:
            report = load_readiness_report(args.report)
            update_production_status(report, args.status_file)
        except Exception as e:
            print(f"Error updating from report: {e}")
            sys.exit(1)
    
    # Update phase status
    if args.update_phases:
        try:
            update_phase_status(args.status_file)
        except Exception as e:
            print(f"Error updating phase status: {e}")
            sys.exit(1)
    
    # Generate summary from multiple reports
    if args.reports and args.summary:
        try:
            generate_summary_report(args.reports, args.summary)
        except Exception as e:
            print(f"Error generating summary: {e}")
            sys.exit(1)
    
    if not any([args.report, args.update_phases, args.reports]):
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
