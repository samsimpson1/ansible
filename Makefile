.PHONY: little edit-vault little-infra little-auth little-apps little-backup little-full

vault-edit:
	ansible-vault edit secret.yaml

# Original monolithic playbook (kept for fallback)
little:
	ansible-playbook little.yaml -i inventory.yaml

little-check:
	ansible-playbook little.yaml --check --diff -i inventory.yaml

# Split playbook components
little-infra:
	ansible-playbook little-infrastructure.yaml -i inventory.yaml

little-auth:
	ansible-playbook little-auth.yaml -i inventory.yaml

little-apps:
	ansible-playbook little-apps.yaml -i inventory.yaml

little-backup:
	ansible-playbook little-backup.yaml -i inventory.yaml

# Full deployment using split playbooks
little-full: little-infra little-auth little-apps little-backup

# Check targets for split playbooks
little-infra-check:
	ansible-playbook little-infrastructure.yaml --check --diff -i inventory.yaml

little-auth-check:
	ansible-playbook little-auth.yaml --check --diff -i inventory.yaml

little-apps-check:
	ansible-playbook little-apps.yaml --check --diff -i inventory.yaml

little-backup-check:
	ansible-playbook little-backup.yaml --check --diff -i inventory.yaml

garage-check:
	ansible-playbook garage.yaml --check --diff -i inventory.yaml

garage:
	ansible-playbook garage.yaml -i inventory.yaml
