# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an Ansible infrastructure-as-code repository for managing home lab infrastructure for the `little` host. The setup includes container services, backups, SSO authentication, and various self-hosted applications.

## Key Commands

### Running Playbooks

#### Split Playbooks (Recommended)
- `make little-infra` - Deploy base infrastructure (Tailscale, Docker, sSMTP)
- `make little-auth` - Deploy authentication services (Pocket ID)
- `make little-apps` - Deploy applications (ECG notify, Karakeep, FreshRSS, Arr apps, Firefly III)
- `make little-backup` - Deploy backup configuration
- `make little-full` - Deploy all components in sequence

#### Check Targets
- `make little-infra-check` - Dry-run infrastructure changes
- `make little-auth-check` - Dry-run authentication changes  
- `make little-apps-check` - Dry-run application changes
- `make little-backup-check` - Dry-run backup changes

### Vault Management
- `make vault-edit` - Edit encrypted secrets using 1Password CLI integration

All commands use 1Password CLI for vault password retrieval via `onepassword-client.sh`. The inventory file and vault configuration are specified in `ansible.cfg`.

## Architecture

### Host Structure
- **little** (10.0.0.191) - Main application host running containerized services

### Key Roles

#### docker_service
Central role for managing containerized services via systemd. Creates systemd unit files that run Docker containers with configurable:
- Network settings
- Port mappings  
- Volume mounts
- Environment variables
- User/group settings

#### backup
Comprehensive backup system supporting:
- **Restic** - Encrypted backups to remote storage
- **Sync operations** - Direct rsync/ssh transfers
- **Automated reporting** - Email reports every 2 days
- **Scheduled jobs** - Cron-based backup scheduling

#### caddy
Reverse proxy and web server role that builds custom Caddy images with DNS plugins:
- **Custom Docker image** - Builds Caddy with Cloudflare DNS plugin using xcaddy
- **Configurable instances** - Supports multiple Caddy instances with unique IDs
- **Automatic TLS** - Built-in HTTPS with Let's Encrypt integration
- **Service integration** - Uses docker_service role for systemd management

### Authentication
Uses **Pocket ID** as SSO provider with OAuth2 integration across services. Applications like FreshRSS and Firefly III are configured with OIDC authentication.

### Application Categories
- **Media Management** - Arr stack (Prowlarr, Radarr, Sonarr)
- **Personal Finance** - Firefly III with OAuth2 proxy and data importer
- **Knowledge Management** - Karakeep with Meilisearch backend
- **RSS/Feed Reading** - FreshRSS with OIDC

### Infrastructure Services
- **Tailscale** - Mesh networking
- **Docker** - Container runtime
- **sSMTP** - Mail relay configuration

## Important Patterns

### Service Definitions
Services follow a consistent pattern using the `docker_service` role:
```yaml
- name: Service Name
  ansible.builtin.include_role:
    name: docker_service
  vars:
    id: "service-name"
    description: "Service Description"
    image: "image:tag"
    network: "network_name"
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

### Secrets Management
- Encrypted variables stored in `secret.yaml` using ansible-vault
- 1Password CLI integration for vault password retrieval
- Sensitive configuration like API keys, passwords, and tokens are vaulted

## File Structure Notes
- **Playbooks**: `little-infrastructure.yaml`, `little-auth.yaml`, `little-apps.yaml`, `little-backup.yaml`
- **Application-specific tasks**: `apps/` directory
- **Reusable roles**: `roles/` directory
- **Configuration**: `ansible.cfg` (inventory path, vault settings)
- **Host inventory**: `inventory.yaml`
- **Encrypted secrets**: `secret.yaml`

## Development Workflow
1. **For faster iterations**: Use split playbooks (`make little-apps` for app changes, `make little-infra` for system changes)
2. **Test changes**: Use appropriate check targets (`make little-apps-check`) before applying
3. **For full deployments**: Use `make little-full` or individual components in sequence
4. **Use fully qualified Ansible module names** (e.g., `ansible.builtin.include_role`)
5. **Vault integration** requires 1Password CLI (`op`) to be configured
6. **Service configurations** should leverage the `docker_service` role for consistency

## Split Playbook Dependencies
- **little-infrastructure.yaml**: Must run first (provides Docker, networking)
- **little-auth.yaml**: Requires infrastructure (provides SSO for apps)
- **little-apps.yaml**: Requires infrastructure and auth
- **little-backup.yaml**: Independent, can run anytime after infrastructure