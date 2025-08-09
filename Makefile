.PHONY: little edit-vault little-infra little-auth little-apps little-backup little-full

vault-edit:
	ansible-vault edit secret.yaml --vault-id ansible-vault@onepassword-client.sh

# Original monolithic playbook (kept for fallback)
little:
	ansible-playbook little.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-check:
	ansible-playbook little.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

# Split playbook components
little-infra:
	ansible-playbook little-infrastructure.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-auth:
	ansible-playbook little-auth.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-apps:
	ansible-playbook little-apps.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-backup:
	ansible-playbook little-backup.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

# Full deployment using split playbooks
little-full: little-infra little-auth little-apps little-backup

# Check targets for split playbooks
little-infra-check:
	ansible-playbook little-infrastructure.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-auth-check:
	ansible-playbook little-auth.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-apps-check:
	ansible-playbook little-apps.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-backup-check:
	ansible-playbook little-backup.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

garage-check:
	ansible-playbook garage.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

garage:
	ansible-playbook garage.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh
