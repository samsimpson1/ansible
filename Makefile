.PHONY: little edit-vault little-infra little-auth little-apps little-backup little-full

vault-edit:
	ansible-vault edit secret.yaml

# Original monolithic playbook (kept for fallback)
little:
	ansible-playbook little.yaml

little-check:
	ansible-playbook little.yaml --check --diff

# Split playbook components
little-infra:
	ansible-playbook little-infrastructure.yaml

little-auth:
	ansible-playbook little-auth.yaml

little-apps:
	ansible-playbook little-apps.yaml

little-backup:
	ansible-playbook little-backup.yaml

# Full deployment using split playbooks
little-full: little-infra little-auth little-apps little-backup

# Check targets for split playbooks
little-infra-check:
	ansible-playbook little-infrastructure.yaml --check --diff

little-auth-check:
	ansible-playbook little-auth.yaml --check --diff

little-apps-check:
	ansible-playbook little-apps.yaml --check --diff

little-backup-check:
	ansible-playbook little-backup.yaml --check --diff

garage-check:
	ansible-playbook garage.yaml --check --diff

garage:
	ansible-playbook garage.yaml
