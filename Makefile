.PHONY: little edit-vault

vault-edit:
	ansible-vault edit secret.yaml --vault-id ansible-vault@onepassword-client.sh

little:
	ansible-playbook little.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

little-check:
	ansible-playbook little.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

garage-check:
	ansible-playbook garage.yaml --check --diff -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh

garage:
	ansible-playbook garage.yaml -i inventory.yaml --vault-id ansible-vault@onepassword-client.sh
