# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an Ansible infrastructure-as-code repository for managing home lab infrastructure across multiple hosts (`little` and `box`). The setup includes container services, CI/CD, backups, SSO authentication, high-availability proxy, and various self-hosted applications.

## Key Commands

### Running Playbooks

Playbooks use a numbered naming convention (`N-*.play.yaml`) indicating execution order dependencies.

#### Direct Playbook Execution
- `ansible-playbook 0-ha-proxy.play.yaml` - Deploy HA Proxy with Keepalived on both hosts
- `ansible-playbook 1-little-infrastructure.play.yaml` - Deploy little host infrastructure (Tailscale, Docker, SSMTP, Caddy, Pocket ID, Monitoring, Vault)
- `ansible-playbook 1-box.play.yaml` - Deploy box host infrastructure (Docker, Concourse CI, Tandoor, Pocket ID secondary)
- `ansible-playbook 2-little-apps.play.yaml` - Deploy little host applications (Wiki, Karakeep, FreshRSS, Home Assistant, Catbot, Samba, Stonks)
- `ansible-playbook 2-little-media.play.yaml` - Deploy media services (Arr stack, Downloaders, Plex, Jellyfin, Audiobookshelf, etc.)
- `ansible-playbook 3-monitoring.play.yaml` - Deploy monitoring exporters across home host group
- `ansible-playbook 3-little-backup.play.yaml` - Deploy little host backup configuration
- `ansible-playbook 3-box-backup.play.yaml` - Deploy box host backup configuration

#### Desktop Playbooks
Desktop playbooks run locally (`connection: local`) from the repository root:
- `ansible-playbook desktop/play-work-mac.yaml` - Full macOS workstation setup (packages, shell, AWS)
- `ansible-playbook desktop/play-work-mac-packages.yaml` - macOS package installation only
- `ansible-playbook desktop/play-secure-boot.yaml` - Arch Linux Secure Boot setup
- `ansible-playbook desktop/shell/playbook.yaml` - Shell configuration (zsh, starship)
- `ansible-playbook desktop/shell-ssh/playbook.yaml` - SSH and Git signing with YubiKey
- `ansible-playbook desktop/shell-aws/playbook.yaml` - AWS CLI and work shell setup
- `ansible-playbook desktop/backup-linux/playbook.yaml` - Linux desktop backup via Restic

#### Dry-run (Check Mode)
Add `--check` flag to any playbook command for dry-run mode:
- `ansible-playbook 1-little-infrastructure.play.yaml --check`
- `ansible-playbook 2-little-apps.play.yaml --check`

#### Install Requirements
- `ansible-galaxy role install -r requirements.yaml` - Install required Ansible roles
- `ansible-galaxy collection install -r requirements.yaml` - Install required Ansible collections

### Vault Management
- `ansible-vault edit secret.yaml` - Edit encrypted secrets (uses 1Password CLI via onepassword-client.sh)

All commands use 1Password CLI for vault password retrieval via `onepassword-client.sh`. The inventory file and vault configuration are specified in `ansible.cfg`.

## Architecture

### Host Structure
- **little** (10.0.0.191) - Main application host running containerized services
- **box** (10.0.0.202) - Secondary host running CI/CD (Concourse), recipes (Tandoor)
- **home** (group) - Both hosts for shared configurations like monitoring exporters

HA Proxy with Keepalived provides failover between hosts.

### Key Roles

#### Infrastructure Roles

##### docker_host
Sets up Docker daemon on target hosts.

##### docker_service
Central role for managing containerized services via systemd. Creates systemd unit files that run Docker containers with configurable:
- Network settings
- Port mappings
- Volume mounts
- Environment variables
- User/group settings
- Device mappings (`docker_service_devices`)
- Privileged mode (`docker_service_privileged`)
- PID namespace (`docker_service_pid`)

##### ha_proxy
High-availability proxy with Keepalived for failover between hosts. Configured via host_vars with MASTER/BACKUP states and priorities.

##### tailscale
Mesh networking setup for secure inter-host communication.

##### ssmtp
Mail relay configuration for system notifications.

#### Reverse Proxy & TLS Roles

##### caddy
Reverse proxy and web server role that builds custom Caddy images with DNS plugins:
- **Custom Docker image** - Builds Caddy with Cloudflare DNS plugin using xcaddy
- **Configurable instances** - Supports multiple Caddy instances with unique IDs
- **Automatic TLS** - Built-in HTTPS with Let's Encrypt integration
- **Service integration** - Uses docker_service role for systemd management

##### acme_manager / acme_client
ACME certificate management with Cloudflare DNS integration.

#### Authentication & Security Roles

##### pocket_id
SSO provider supporting both primary and secondary roles for HA setups.

##### oauth2_proxy
Reusable OAuth2 proxy role for SSO integration with applications:
- **Service isolation** - Creates `{id}-oauth2-proxy` service and data directory to avoid conflicts
- **Flexible configuration** - Configurable upstreams, skip auth routes, and OIDC settings
- **Pocket ID integration** - Pre-configured for Pocket ID SSO provider
- **Template-based config** - Generates oauth2-proxy.cfg from Jinja2 template

##### vault
HashiCorp Vault for secrets management.

#### CI/CD Roles

##### concourse_web / concourse_worker
Concourse CI server and worker for automation pipelines.

#### Monitoring Roles

##### monitoring_server
Prometheus, Grafana, and Alertmanager stack.

##### monitoring_exporters
Node exporter, smartctl exporter, and pushgateway for metrics collection.

#### Backup Roles

##### backup
Comprehensive backup system supporting:
- **Restic** - Encrypted backups to remote storage
- **Sync operations** - Direct rsync/ssh transfers
- **Discord reporting** - Backup status notifications
- **Scheduled jobs** - Cron-based backup scheduling

##### offline_backup
Offline backup management for air-gapped storage.

#### Application Roles

##### tandoor
Recipe management application.

##### samba_server
Samba file sharing server.

### Authentication
Uses **Pocket ID** as SSO provider with OAuth2 integration across services. Applications like FreshRSS and Karakeep are configured with OIDC authentication.

### Application Categories
- **Media Management** - Arr stack (Prowlarr, Radarr, Sonarr), Komga, Overseerr, Pinchflat
- **Media Playback** - Plex, Jellyfin, Audiobookshelf, LMS (Lyrion), Navidrome
- **Downloads** - qBittorrent, SABnzbd, Unpackerr, Slskd
- **Knowledge Management** - Karakeep with Meilisearch backend, Wiki
- **RSS/Feed Reading** - FreshRSS with OIDC
- **Home Automation** - Home Assistant with Zigbee USB device support
- **Recipes** - Tandoor (on box host)
- **Monitoring** - Prometheus, Grafana, Alertmanager, Node Exporter
- **Communication** - Catbot Discord bot with timezone support
- **File Management** - Samba

### Infrastructure Services
- **Tailscale** - Mesh networking
- **Docker** - Container runtime
- **sSMTP** - Mail relay configuration
- **HA Proxy** - High-availability proxy with Keepalived
- **Concourse CI** - CI/CD automation
- **Vault** - Secrets management

## Desktop Configuration

The `desktop/` directory contains playbooks for configuring local developer workstations. Unlike server playbooks, these run locally (`connection: local`, `hosts: 127.0.0.1`) and do not use custom roles — tasks are defined inline.

### Top-level Playbooks

- **play-work-mac.yaml** - Main macOS orchestrator; imports package installation, shell, and shell-aws playbooks
- **play-work-mac-packages.yaml** - Installs macOS packages via Homebrew (1Password, Firefox, Ghostty, VS Code, etc.) and configures Ghostty terminal with Catppuccin theme
- **play-secure-boot.yaml** - Arch Linux Secure Boot: installs signing tools, creates a MOK signing script, and registers a pacman hook to auto-sign kernel and bootloader on updates

### Modular Sub-playbooks

These are reusable across macOS and Linux and can be run independently:

- **shell/** - Zsh environment with fzf, syntax highlighting, autosuggestions, and Starship prompt. OS-aware plugin path configuration (macOS Homebrew vs Arch system paths).
- **shell-ssh/** - SSH and Git signing with YubiKey support. Deploys key handles for two YubiKeys, a detection script that selects the correct signing key based on which YubiKey is plugged in, SSH client config with shortcuts for `little` and `box`, and OS-specific ssh-agent startup (macOS uses ssh-askpass).
- **shell-aws/** - AWS CLI for work environments. Configures multiple accounts and roles, installs awsume with YubiKey and 1Password MFA plugins, and provides shell shortcuts for role assumption and session recording.
- **backup-linux/** - Restic-based desktop backup via systemd user timer (every 2 hours). Backs up to the `little` host over SFTP, excludes caches and large media, and pushes metrics to Prometheus pushgateway.

## Important Patterns

### Service Definitions
Services follow a consistent pattern using the `docker_service` role:
```yaml
- name: Service Name
  ansible.builtin.include_role:
    name: docker_service
  vars:
    docker_service_id: "service-name"
    docker_service_description: "Service Description"
    docker_service_image: "image:tag"
    docker_service_network: "network_name"
    # ... other service-specific configuration
```

### Backup Job Configuration
Backup jobs are defined with operation type (`restic` or `sync`), paths, and cron scheduling:
```yaml
backup_jobs:
  - name: service-name
    op: restic
    path: /path/to/data
    cron:
      minute: "15"
      hour: "*/4"
```

### Caddy Configuration
Caddy instances are configured with customizable IDs and Caddyfile content:
```yaml
- name: Deploy Caddy
  ansible.builtin.include_role:
    name: caddy
  vars:
    caddy_id: "my-proxy"
    caddy_version: "2.10"
    caddy_caddyfile: |
      example.com {
        reverse_proxy localhost:8080
      }
    caddy_ports:
      - "80:80"
      - "443:443"
    caddy_env_vars:
      CLOUDFLARE_API_TOKEN: "{{ vault_cloudflare_token }}"
```

### OAuth2 Proxy Configuration
OAuth2 proxies are configured using the reusable `oauth2_proxy` role:
```yaml
- name: Service OAuth2 Proxy
  ansible.builtin.include_role:
    name: oauth2_proxy
  vars:
    oauth2_proxy_id: "service-name"
    oauth2_proxy_upstreams:
      - "http://service-name:8080"
    oauth2_proxy_skip_auth_routes:
      - "^/api"
    oauth2_proxy_client_id: "{{ sso_clients.service_name.id }}"
    oauth2_proxy_client_secret: "{{ sso_clients.service_name.secret }}"
    oauth2_proxy_cookie_secret: "{{ service_name.cookie_secret }}"
```

### Secrets Management
- Encrypted variables stored in `secret.yaml` using ansible-vault
- 1Password CLI integration for vault password retrieval
- Sensitive configuration like API keys, passwords, and tokens are vaulted

### Container Image Versions
- Container image versions are centrally managed in `group_vars/all/container-images.yaml`
- Reference images using `{{ container_images.service_name }}` in playbooks
- Currently managed: Caddy, Prometheus, Grafana, Alertmanager, Node Exporter, Smartctl Exporter, Pushgateway, Concourse, Vault, Tandoor, Litestream, Pocket ID, Copyparty

## File Structure Notes
- **Playbooks**: `0-ha-proxy.play.yaml`, `1-little-infrastructure.play.yaml`, `1-box.play.yaml`, `2-little-apps.play.yaml`, `2-little-media.play.yaml`, `3-monitoring.play.yaml`, `3-little-backup.play.yaml`, `3-box-backup.play.yaml`
- **Application-specific tasks**: `apps/` directory
- **Reusable roles**: `roles/` directory (22 roles)
- **Configuration**: `ansible.cfg` (inventory path, vault settings)
- **Host inventory**: `inventory.yaml`
- **Host variables**: `host_vars/` (little.yaml, box.yaml for HA Proxy configuration)
- **Group variables**: `group_vars/all/` (container-images.yaml, sites.yaml, secret.yaml)
- **Playbook variables**: `vars/` (backup.yaml, concourse.yaml, tandoor.yaml)
- **Desktop playbooks**: `desktop/` directory (local workstation setup for macOS and Linux, see Desktop Configuration section)

## Development Workflow
1. **For faster iterations**: Use split playbooks (e.g., `ansible-playbook 2-little-apps.play.yaml` for app changes, `ansible-playbook 1-little-infrastructure.play.yaml` for system changes)
2. **Test changes**: Use `--check` flag before applying (e.g., `ansible-playbook 2-little-apps.play.yaml --check`)
3. **Use fully qualified Ansible module names** (e.g., `ansible.builtin.include_role`)
4. **Vault integration** requires 1Password CLI (`op`) to be configured
5. **Service configurations** should leverage the `docker_service` role for consistency

## CI/CD
- GitHub Actions runs ansible-lint on all pushes to validate playbook syntax
- Workflow file: `.github/workflows/ansible-lint.yaml`
- Uses 1Password service account for vault password during linting

## Playbook Dependencies (Execution Order)
The numbered prefix indicates execution order:
- **0-ha-proxy.play.yaml**: HA Proxy setup (can run independently)
- **1-little-infrastructure.play.yaml**: Must run first for little host (provides Docker, networking, Caddy, Pocket ID, Monitoring, Vault)
- **1-box.play.yaml**: Must run first for box host (provides Docker, Concourse, Tandoor, Pocket ID secondary)
- **2-little-apps.play.yaml**: Requires little infrastructure
- **2-little-media.play.yaml**: Requires little infrastructure
- **3-monitoring.play.yaml**: Requires infrastructure on both hosts (deploys exporters)
- **3-little-backup.play.yaml**: Requires little infrastructure
- **3-box-backup.play.yaml**: Requires box infrastructure

# Style Requirements

- Ansible YAML files must always end in a new line
- Ansible task names should always start with an upper case letter
- Tasks in Ansible task lists should be separated by an empty line
# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
