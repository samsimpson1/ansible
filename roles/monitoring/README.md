# Monitoring Role

Simple Ansible role for monitoring disk status and service status with email alerts via sSMTP.

## Features

- **Disk Monitoring**: Checks disk usage, SMART status, and critical mount points
- **Service Monitoring**: Monitors systemd services and detects restart loops
- **Email Alerts**: Sends notifications via sSMTP when issues are detected
- **Rate Limiting**: Prevents email spam with configurable rate limiting
- **Cron Integration**: Runs monitoring checks every 15 minutes

## Requirements

- sSMTP role must be configured for email functionality
- `main_email` variable must be defined for alert destination

## Usage

### Basic Usage

```yaml
- hosts: all
  roles:
    - ssmtp
    - monitoring
```

### Custom Configuration

```yaml
- hosts: all
  roles:
    - ssmtp
    - monitoring
  vars:
    disk_usage_critical: 85
    monitored_services:
      - ssh
      - nginx
      - docker
    service_restart_threshold: 5
```

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `monitoring_enabled` | `true` | Enable/disable monitoring |
| `monitoring_interval` | `"*/15"` | Cron schedule (every 15 minutes) |
| `monitoring_email` | `"{{ main_email }}"` | Email address for alerts |
| `disk_usage_critical` | `90` | Disk usage percentage threshold |
| `monitored_services` | `["ssh", "cron"]` | List of services to monitor |
| `service_restart_threshold` | `3` | Alert if service restarts exceed this in 1 hour |
| `alert_rate_limit_minutes` | `60` | Minimum time between same alert types |

## Files Created

- `/opt/monitoring/monitor-disk.sh` - Disk monitoring script
- `/opt/monitoring/monitor-services.sh` - Service monitoring script
- `/opt/monitoring/alert-email.sh` - Email notification handler
- `/opt/monitoring/monitor-main.sh` - Main orchestrator script
- `/opt/monitoring/monitoring.log` - Monitoring activity log
- `/opt/monitoring/alerts.log` - Alert history log

## Example Playbook

```yaml
---
- name: Setup monitoring
  hosts: home
  become: yes
  vars:
    main_email: "admin@example.com"
    smtp_hostname: "smtp.gmail.com"
    smtp_port: 587
    smtp_username: "your-email@gmail.com"
    smtp_password: "your-app-password"
    smtp_from_domain: "example.com"
    smtp_tls: "starttls"
    
    # Monitoring configuration
    monitored_services:
      - ssh
      - cron
      - docker
    disk_usage_critical: 85
    
  roles:
    - ssmtp
    - monitoring