#!/usr/bin/env python3
# /// script
# requires-python = ">3.12"
# ///

import subprocess
import sys
import json
import re
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def load_config(config_path="/srv/backups/config.json"):
    """Load backup configuration from JSON file."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file {config_path} not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file: {e}", file=sys.stderr)
        sys.exit(1)

def run_command(cmd):
    """Execute a shell command and return the output."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

def format_size(size_str):
    """Format a size string to 1 decimal place for better readability."""
    if not size_str or size_str == "N/A":
        return size_str
    
    # Extract number and unit from strings like "4.353 MiB" or "1.2G"
    match = re.match(r'^([0-9.]+)\s*([KMGTPE]?i?B?)$', size_str)
    if match:
        number = float(match.group(1))
        unit = match.group(2)
        return f"{number:.1f} {unit}"
    
    return size_str

def get_restic_stats(job_name):
    """Get statistics for a restic backup job."""
    stats_cmd = f'/srv/backups/restic-util.sh "{job_name}" stats --mode raw-data'
    stats_output = run_command(stats_cmd)
    
    # Parse total size - format: "              Total Size:  4.353 MiB"
    total_size = "N/A"
    size_match = re.search(r'Total Size:\s+([0-9.]+\s+[KMGTPE]iB)', stats_output)
    if size_match:
        total_size = size_match.group(1)
    
    # Parse snapshot count - format: "     Snapshots processed:  84"
    snapshot_count = "N/A"
    count_match = re.search(r'Snapshots processed:\s+(\d+)', stats_output)
    if count_match:
        snapshot_count = count_match.group(1)
    
    # Get last snapshot - format: "9fdb11ae  2025-08-13 14:18:03  little"
    snapshot_cmd = f'/srv/backups/restic-util.sh "{job_name}" snapshots --latest 1 --compact'
    snapshot_output = run_command(snapshot_cmd)
    last_snapshot = "N/A"
    
    lines = snapshot_output.split('\n')
    for line in lines:
        # Look for the data line (after header, before footer)
        if re.match(r'^[a-f0-9]{8}\s+', line):
            parts = line.split()
            if len(parts) >= 3:
                last_snapshot = f"{parts[1]} {parts[2]}"
            break
    
    return {
        'total_size': format_size(total_size),
        'snapshot_count': snapshot_count,
        'last_snapshot': last_snapshot
    }

def get_sync_size(job_name, backup_target):
    """Get disk usage for a sync backup job."""
    cmd = f'''sshpass -f /srv/backups/password \\
        ssh -p{backup_target.get('port', 23)} -o StrictHostKeyChecking=no \\
        "{backup_target['user']}@{backup_target['hostname']}" \\
        "du -sh {job_name}/" '''
    output = run_command(cmd)
    # Extract first field (size) from du output
    size = output.split()[0] if output and not output.startswith("Error") else "N/A"
    return format_size(size)

def get_total_disk_usage(backup_target):
    """Get total disk usage on backup target."""
    cmd = f'''sshpass -f /srv/backups/password \\
        ssh -p{backup_target.get('port', 23)} -o StrictHostKeyChecking=no \\
        "{backup_target['user']}@{backup_target['hostname']}" \\
        "du -sh ." '''
    output = run_command(cmd)
    # Extract first field (size) from du output
    size = output.split()[0] if output and not output.startswith("Error") else "N/A"
    return format_size(size)

def generate_plain_text_report(jobs_data, total_usage):
    """Generate plain text version of the report."""
    report_lines = []
    report_lines.append("=== Backup Report ===")
    report_lines.append("")
    
    for job in jobs_data:
        report_lines.append(f"=== Job: {job['name']} ===")
        report_lines.append(f"- Kind: {job['kind']}")
        
        if job['kind'] == 'restic':
            report_lines.append(f"- Total Size: {job['total_size']}")
            report_lines.append(f"- Snapshot Count: {job['snapshot_count']}")
            report_lines.append(f"- Last Snapshot: {job['last_snapshot']}")
        elif job['kind'] == 'sync':
            report_lines.append(f"- Disk Usage: {job['disk_usage']}")
        
        report_lines.append("-----------------------------")
        report_lines.append("")
    
    report_lines.append(f"=== Total Disk Usage: {total_usage} ===")
    
    return "\n".join(report_lines)

def generate_html_report(jobs_data, total_usage):
    """Generate HTML version of the report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Backup Report - {now}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #f8f9fa;
            font-weight: bold;
            color: #555;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .restic-row {{
            background-color: #e8f5e8;
        }}
        .sync-row {{
            background-color: #e8f0ff;
        }}
        .total-section {{
            background-color: #fff3cd;
            padding: 15px;
            border-radius: 5px;
            text-align: center;
            font-size: 1.2em;
            font-weight: bold;
            margin-top: 20px;
        }}
        .timestamp {{
            text-align: center;
            color: #666;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Backup Report</h1>
        <div class="timestamp">Generated on {now}</div>
        
        <table>
            <thead>
                <tr>
                    <th>Job Name</th>
                    <th>Type</th>
                    <th>Size/Usage</th>
                    <th>Snapshots</th>
                    <th>Last Backup</th>
                </tr>
            </thead>
            <tbody>"""
    
    for job in jobs_data:
        row_class = f"{job['kind']}-row"
        html += f"""
                <tr class="{row_class}">
                    <td><strong>{job['name']}</strong></td>
                    <td>{job['kind'].title()}</td>"""
        
        if job['kind'] == 'restic':
            html += f"""
                    <td>{job['total_size']}</td>
                    <td>{job['snapshot_count']}</td>
                    <td>{job['last_snapshot']}</td>"""
        elif job['kind'] == 'sync':
            html += f"""
                    <td>{job['disk_usage']}</td>
                    <td>-</td>
                    <td>-</td>"""
        
        html += """
                </tr>"""
    
    html += f"""
            </tbody>
        </table>
        
        <div class="total-section">
            Total Disk Usage: {total_usage}
        </div>
    </div>
</body>
</html>"""
    
    return html

def main():
    """Main function to generate and output the MIME multipart email."""
    # Load configuration from JSON file
    config = load_config()
    
    # Extract configuration values
    backup_target = config.get('backup_target', {})
    smtp_config = config.get('smtp_config', {})
    backup_jobs = config.get('backup_jobs', [])
    
    # Collect data for all backup jobs
    jobs_data = []
    
    for job in backup_jobs:
        job_name = job.get('name', 'unknown')
        job_op = job.get('op', 'unknown')
        
        if job_op == 'restic':
            # Restic job
            restic_stats = get_restic_stats(job_name)
            jobs_data.append({
                'name': job_name,
                'kind': 'restic',
                'total_size': restic_stats['total_size'],
                'snapshot_count': restic_stats['snapshot_count'],
                'last_snapshot': restic_stats['last_snapshot']
            })
        elif job_op == 'sync':
            # Sync job
            sync_size = get_sync_size(job_name, backup_target)
            jobs_data.append({
                'name': job_name,
                'kind': 'sync',
                'disk_usage': sync_size
            })
    
    # Get total disk usage
    total_usage = get_total_disk_usage(backup_target)
    
    # Generate both versions of the report
    plain_text = generate_plain_text_report(jobs_data, total_usage)
    html_content = generate_html_report(jobs_data, total_usage)
    
    # Create MIME multipart message
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = MIMEMultipart('alternative')
    msg['From'] = f"backups@{smtp_config.get('from_domain', 'localhost')}"
    msg['Subject'] = f"Backup Report {now}"
    
    # Attach both plain text and HTML versions
    msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    # Output the complete MIME message
    print(msg.as_string())

if __name__ == "__main__":
    main()