# GitHub Actions Setup

## Required Secrets

To use the GitHub Actions workflow for deploying to the `little` host, configure these repository secrets:

### Tailscale Access
- `TAILSCALE_OAUTH_CLIENT_ID` - OAuth client ID from Tailscale admin console
- `TAILSCALE_OAUTH_SECRET` - OAuth secret from Tailscale admin console

**Setup Instructions:**
1. Go to [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth)
2. Generate a new OAuth client with the `devices:write` scope
3. Tag the client with `tag:github-actions` 
4. Add the client ID and secret to GitHub repository secrets

### 1Password CLI Access
- `OP_SERVICE_ACCOUNT_TOKEN` - Service account token for accessing the Infrastructure vault

**Setup Instructions:**
1. Create a service account in your 1Password Business account
2. Grant access to the "Infrastructure" vault
3. Generate a service account token
4. Add the token to GitHub repository secrets

## Workflow Features

The current workflow:
- ✅ Connects to Tailscale network
- ✅ Installs and configures 1Password CLI
- ✅ Installs Ansible
- ✅ Tests vault password retrieval
- ✅ Verifies connectivity to little host (10.0.0.191)

## Future Enhancements

The workflow is designed to be extended with:
- SSH key configuration for Ansible host access
- Ansible playbook execution (little-full deployment)
- Deployment status reporting
- Rollback capabilities