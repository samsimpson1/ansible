# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an Ansible infrastructure-as-code repository for managing home lab infrastructure for the `little` host. The setup includes container services, backups, SSO authentication, and various self-hosted applications.

## Key Commands

### Running Playbooks

#### Direct Playbook Execution
- `ansible-playbook play-little-infrastructure.yaml` - Deploy base infrastructure (Tailscale, Docker, sSMTP, Caddy)
- `ansible-playbook play-little-auth.yaml` - Deploy authentication services (Pocket ID)
- `ansible-playbook play-little-apps.yaml` - Deploy applications (ECG notify, Karakeep, FreshRSS, Arr apps, Firefly III, Home Assistant, Monitoring stack)
- `ansible-playbook play-little-backup.yaml` - Deploy backup configuration

#### Dry-run (Check Mode)
Add `--check` flag to any playbook command for dry-run mode:
- `ansible-playbook play-little-infrastructure.yaml --check`
- `ansible-playbook play-little-auth.yaml --check`
- `ansible-playbook play-little-apps.yaml --check`
- `ansible-playbook play-little-backup.yaml --check`

#### Install Requirements
- `ansible-galaxy role install -r requirements.yaml` - Install required Ansible roles
- `ansible-galaxy collection install -r requirements.yaml` - Install required Ansible collections

### Vault Management
- `ansible-vault edit secret.yaml` - Edit encrypted secrets (uses 1Password CLI via onepassword-client.sh)

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
- Device mappings (`docker_service_devices`)
- Privileged mode (`docker_service_privileged`)
- PID namespace (`docker_service_pid`)

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

#### oauth2_proxy
Reusable OAuth2 proxy role for SSO integration with applications:
- **Service isolation** - Creates `{id}-oauth2-proxy` service and data directory to avoid conflicts
- **Flexible configuration** - Configurable upstreams, skip auth routes, and OIDC settings
- **Pocket ID integration** - Pre-configured for Pocket ID SSO provider
- **Template-based config** - Generates oauth2-proxy.cfg from Jinja2 template

### Authentication
Uses **Pocket ID** as SSO provider with OAuth2 integration across services. Applications like FreshRSS and Firefly III are configured with OIDC authentication.

### Application Categories
- **Media Management** - Arr stack (Prowlarr, Radarr, Sonarr), Komga, Overseerr, Pinchflat
- **Downloads** - qBittorrent, SABnzbd, Unpackerr, Slskd
- **Personal Finance** - Firefly III with OAuth2 proxy and data importer
- **Knowledge Management** - Karakeep with Meilisearch backend, Wiki
- **RSS/Feed Reading** - FreshRSS with OIDC
- **Home Automation** - Home Assistant with Zigbee USB device support
- **Monitoring** - Prometheus, Grafana, Node Exporter
- **Communication** - Catbot Discord bot with timezone support

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
- Container image versions are centrally managed in `container-images.yaml`
- Reference images using `{{ container_images.service_name }}` in playbooks
- Currently managed: Caddy, Renovate

## File Structure Notes
- **Playbooks**: `play-little-infrastructure.yaml`, `play-little-auth.yaml`, `play-little-apps.yaml`, `play-little-backup.yaml`
- **Application-specific tasks**: `apps/` directory
- **Reusable roles**: `roles/` directory
- **Configuration**: `ansible.cfg` (inventory path, vault settings)
- **Host inventory**: `inventory.yaml`
- **Encrypted secrets**: `secret.yaml`
- **Container versions**: `container-images.yaml`

## Development Workflow
1. **For faster iterations**: Use split playbooks (e.g., `ansible-playbook play-little-apps.yaml` for app changes, `ansible-playbook play-little-infrastructure.yaml` for system changes)
2. **Test changes**: Use `--check` flag before applying (e.g., `ansible-playbook play-little-apps.yaml --check`)
3. **Use fully qualified Ansible module names** (e.g., `ansible.builtin.include_role`)
4. **Vault integration** requires 1Password CLI (`op`) to be configured
5. **Service configurations** should leverage the `docker_service` role for consistency

## Automated Deployment
- GitHub Actions automatically deploys all playbooks (`play-*.yaml`) on push to main branch
- Uses self-hosted runner with 1Password service account for secrets
- Workflow file: `.github/workflows/deploy-ansible.yaml`

## Split Playbook Dependencies
- **play-little-infrastructure.yaml**: Must run first (provides Docker, networking, Caddy)
- **play-little-auth.yaml**: Requires infrastructure (provides SSO for apps)
- **play-little-apps.yaml**: Requires infrastructure and auth
- **play-little-backup.yaml**: Independent, can run anytime after infrastructure

# Style Requirements

- Ansible YAML files must always end in a new line
- Ansible task names should always start with an upper case letter
# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

<!-- BACKLOG.MD MCP GUIDELINES START -->

<CRITICAL_INSTRUCTION>

## BACKLOG WORKFLOW INSTRUCTIONS

This project uses Backlog.md MCP for all task and project management activities.

**CRITICAL GUIDANCE**

- If your client supports MCP resources, read `backlog://workflow/overview` to understand when and how to use Backlog for this project.
- If your client only supports tools or the above request fails, call `backlog.get_workflow_overview()` tool to load the tool-oriented overview (it lists the matching guide tools).

- **First time working here?** Read the overview resource IMMEDIATELY to learn the workflow
- **Already familiar?** You should have the overview cached ("## Backlog.md Overview (MCP)")
- **When to read it**: BEFORE creating tasks, or when you're unsure whether to track work

These guides cover:
- Decision framework for when to create tasks
- Search-first workflow to avoid duplicates
- Links to detailed guides for task creation, execution, and completion
- MCP tools reference

You MUST read the overview resource to understand the complete workflow. The information is NOT summarized here.

</CRITICAL_INSTRUCTION>

<!-- BACKLOG.MD MCP GUIDELINES END -->
