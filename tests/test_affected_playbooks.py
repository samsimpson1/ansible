from __future__ import annotations

import pathlib
import subprocess
import tempfile
import textwrap
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "bin" / "affected-playbooks"


class Repository:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()

    def write(self, path: str, content: str) -> None:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(textwrap.dedent(content).lstrip())

    def commit(self, message: str) -> None:
        self.git("add", ".")
        self.git("commit", "-m", message)

    def affected(self) -> list[str]:
        result = subprocess.run(
            [str(SCRIPT), "--base", "HEAD^", "--head", "HEAD"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.splitlines()


class AffectedPlaybooksTest(unittest.TestCase):
    def test_role_change_finds_direct_and_transitive_playbook_users(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-direct.play.yaml",
                """
                - hosts: direct
                  tasks:
                    - ansible.builtin.include_role:
                        name: shared
                """,
            )
            repo.write(
                "2-transitive.play.yaml",
                """
                - hosts: transitive
                  tasks:
                    - ansible.builtin.include_role:
                        name: wrapper
                """,
            )
            repo.write(
                "3-unrelated.play.yaml",
                """
                - hosts: unrelated
                  tasks: []
                """,
            )
            repo.write(
                "roles/wrapper/tasks/main.yaml",
                """
                - ansible.builtin.include_role:
                    name: shared
                """,
            )
            repo.write("roles/shared/tasks/main.yaml", "- debug: {msg: shared}\n")
            repo.write("roles/shared/templates/config.j2", "before\n")
            repo.commit("initial")

            repo.write("roles/shared/templates/config.j2", "after\n")
            repo.commit("change shared role")

            self.assertEqual(
                repo.affected(),
                ["1-direct.play.yaml", "2-transitive.play.yaml"],
            )

    def test_inventory_change_selects_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write("1-first.play.yaml", "- hosts: first\n  tasks: []\n")
            repo.write("2-second.play.yaml", "- hosts: second\n  tasks: []\n")
            repo.write("inventory.yaml", "all: {hosts: {first: {}}}\n")
            repo.commit("initial")

            repo.write("inventory.yaml", "all: {hosts: {first: {}, second: {}}}\n")
            repo.commit("change inventory")

            self.assertEqual(
                repo.affected(),
                ["1-first.play.yaml", "2-second.play.yaml"],
            )

    def test_ansible_config_change_selects_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write("1-first.play.yaml", "- hosts: first\n  tasks: []\n")
            repo.write("2-second.play.yaml", "- hosts: second\n  tasks: []\n")
            repo.write("ansible.cfg", "[defaults]\nforks = 5\n")
            repo.commit("initial")

            repo.write("ansible.cfg", "[defaults]\nforks = 10\n")
            repo.commit("change configuration")

            self.assertEqual(
                repo.affected(),
                ["1-first.play.yaml", "2-second.play.yaml"],
            )

    def test_shared_encrypted_secret_change_selects_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write("1-first.play.yaml", "- hosts: first\n  tasks: []\n")
            repo.write("2-second.play.yaml", "- hosts: second\n  tasks: []\n")
            repo.write(
                "group_vars/all/secret.yaml",
                "$ANSIBLE_VAULT;1.1;AES256\noldciphertext\n",
            )
            repo.commit("initial")

            repo.write(
                "group_vars/all/secret.yaml",
                "$ANSIBLE_VAULT;1.1;AES256\nnewciphertext\n",
            )
            repo.commit("change shared secret")

            self.assertEqual(
                repo.affected(),
                ["1-first.play.yaml", "2-second.play.yaml"],
            )

    def test_included_task_change_finds_every_including_runbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            for name in ("1-first.play.yaml", "2-second.play.yaml"):
                repo.write(
                    name,
                    """
                    - hosts: example
                      tasks:
                        - ansible.builtin.include_tasks: apps/shared.yaml
                    """,
                )
            repo.write("3-unrelated.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("apps/shared.yaml", "- debug: {msg: before}\n")
            repo.commit("initial")

            repo.write("apps/shared.yaml", "- debug: {msg: after}\n")
            repo.commit("change shared tasks")

            self.assertEqual(
                repo.affected(),
                ["1-first.play.yaml", "2-second.play.yaml"],
            )

    def test_plain_shared_variable_file_selects_its_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-consumer.play.yaml",
                """
                - hosts: consumer
                  tasks:
                    - ansible.builtin.include_role:
                        name: service
                """,
            )
            repo.write("2-unrelated.play.yaml", "- hosts: unrelated\n  tasks: []\n")
            repo.write(
                "roles/service/tasks/main.yaml",
                '- debug: {msg: "{{ container_images.service }}"}\n',
            )
            repo.write(
                "group_vars/all/container-images.yaml",
                "container_images:\n  service: example:v1\n",
            )
            repo.commit("initial")

            repo.write(
                "group_vars/all/container-images.yaml",
                "container_images:\n  service: example:v2\n",
            )
            repo.commit("change image")

            self.assertEqual(repo.affected(), ["1-consumer.play.yaml"])

    def test_explicit_vars_file_change_selects_its_runbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-consumer.play.yaml",
                """
                - hosts: consumer
                  vars_files:
                    - vars/service.yaml
                  tasks: []
                """,
            )
            repo.write("2-unrelated.play.yaml", "- hosts: unrelated\n  tasks: []\n")
            repo.write("vars/service.yaml", "service_version: v1\n")
            repo.commit("initial")

            repo.write("vars/service.yaml", "service_version: v2\n")
            repo.commit("change vars")

            self.assertEqual(repo.affected(), ["1-consumer.play.yaml"])

    def test_unknown_change_selects_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write("1-first.play.yaml", "- hosts: first\n  tasks: []\n")
            repo.write("2-second.play.yaml", "- hosts: second\n  tasks: []\n")
            repo.write("custom/config.txt", "before\n")
            repo.commit("initial")

            repo.write("custom/config.txt", "after\n")
            repo.commit("change unknown configuration")

            self.assertEqual(
                repo.affected(),
                ["1-first.play.yaml", "2-second.play.yaml"],
            )

    def test_unresolved_dynamic_include_selects_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-dynamic.play.yaml",
                """
                - hosts: dynamic
                  tasks:
                    - ansible.builtin.include_tasks: "{{ task_file }}"
                """,
            )
            repo.write("2-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("apps/dynamic.yaml", "- debug: {msg: before}\n")
            repo.commit("initial")

            repo.write("apps/dynamic.yaml", "- debug: {msg: after}\n")
            repo.commit("change dynamically included tasks")

            self.assertEqual(
                repo.affected(),
                ["1-dynamic.play.yaml", "2-other.play.yaml"],
            )

    def test_deleted_runbook_is_not_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write("1-deleted.play.yaml", "- hosts: deleted\n  tasks: []\n")
            repo.write("2-kept.play.yaml", "- hosts: kept\n  tasks: []\n")
            repo.commit("initial")

            (repo.root / "1-deleted.play.yaml").unlink()
            repo.commit("delete runbook")

            self.assertEqual(repo.affected(), [])

    def test_desktop_asset_change_falls_back_to_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write("0-user.play.yaml", "- hosts: all\n  tasks: []\n")
            repo.write("1-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("desktop/shell-ssh/files/key.pub", "before\n")
            repo.commit("initial")

            repo.write("desktop/shell-ssh/files/key.pub", "after\n")
            repo.commit("change shared desktop asset")

            self.assertEqual(
                repo.affected(),
                ["0-user.play.yaml", "1-other.play.yaml"],
            )

    def test_dynamic_include_fallback_wins_over_a_static_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-static.play.yaml",
                """
                - hosts: static
                  tasks:
                    - ansible.builtin.include_tasks: apps/shared.yaml
                """,
            )
            repo.write(
                "2-dynamic.play.yaml",
                """
                - hosts: dynamic
                  tasks:
                    - ansible.builtin.include_tasks: "{{ task_file }}"
                """,
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("apps/shared.yaml", "- debug: {msg: before}\n")
            repo.commit("initial")

            repo.write("apps/shared.yaml", "- debug: {msg: after}\n")
            repo.commit("change potentially dynamic tasks")

            self.assertEqual(
                repo.affected(),
                [
                    "1-static.play.yaml",
                    "2-dynamic.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_imported_playbook_change_selects_parent_and_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-parent.play.yaml",
                "- ansible.builtin.import_playbook: 2-child.play.yaml\n",
            )
            repo.write("2-child.play.yaml", "- hosts: child\n  tasks: []\n")
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.commit("initial")

            repo.write(
                "2-child.play.yaml",
                "- hosts: child\n  tasks:\n    - debug: {msg: changed}\n",
            )
            repo.commit("change imported playbook")

            self.assertEqual(
                repo.affected(),
                ["1-parent.play.yaml", "2-child.play.yaml"],
            )

    def test_unresolved_role_after_rename_selects_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            for name in ("1-updated.play.yaml", "2-stale.play.yaml"):
                repo.write(
                    name,
                    """
                    - hosts: example
                      tasks:
                        - ansible.builtin.include_role:
                            name: old
                    """,
                )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("roles/old/tasks/main.yaml", "- debug: {msg: old}\n")
            repo.commit("initial")

            (repo.root / "roles/old").rename(repo.root / "roles/new")
            repo.write(
                "1-updated.play.yaml",
                """
                - hosts: example
                  tasks:
                    - ansible.builtin.include_role:
                        name: new
                """,
            )
            repo.commit("partially rename role")

            self.assertEqual(
                repo.affected(),
                [
                    "1-updated.play.yaml",
                    "2-stale.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_unresolved_task_after_rename_selects_all_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            for name in ("1-updated.play.yaml", "2-stale.play.yaml"):
                repo.write(
                    name,
                    """
                    - hosts: example
                      tasks:
                        - ansible.builtin.include_tasks: apps/old.yaml
                    """,
                )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("apps/old.yaml", "- debug: {msg: old}\n")
            repo.commit("initial")

            (repo.root / "apps/old.yaml").rename(repo.root / "apps/new.yaml")
            repo.write(
                "1-updated.play.yaml",
                """
                - hosts: example
                  tasks:
                    - ansible.builtin.include_tasks: apps/new.yaml
                """,
            )
            repo.commit("partially rename task file")

            self.assertEqual(
                repo.affected(),
                [
                    "1-updated.play.yaml",
                    "2-stale.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_unparseable_runbook_selects_all_for_analyzed_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-static.play.yaml",
                """
                - hosts: static
                  tasks:
                    - ansible.builtin.include_tasks: apps/shared.yaml
                """,
            )
            repo.write("2-broken.play.yaml", "- hosts: broken\n  tasks: [\n")
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("apps/shared.yaml", "- debug: {msg: before}\n")
            repo.commit("initial")

            repo.write("apps/shared.yaml", "- debug: {msg: after}\n")
            repo.commit("change tasks with uncertain consumer")

            self.assertEqual(
                repo.affected(),
                [
                    "1-static.play.yaml",
                    "2-broken.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_explicit_encrypted_vars_file_selects_only_its_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-backup.play.yaml",
                """
                - hosts: backup
                  vars_files:
                    - vars/backup.yaml
                  tasks: []
                """,
            )
            repo.write("2-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write(
                "vars/backup.yaml",
                "backup_password: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n  AAAA\n",
            )
            repo.commit("initial")

            repo.write(
                "vars/backup.yaml",
                "backup_password: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n  BBBB\n",
            )
            repo.commit("rotate backup secret")

            self.assertEqual(repo.affected(), ["1-backup.play.yaml"])

    def test_dynamic_playbook_import_falls_back_on_playbook_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-dynamic.play.yaml",
                "- ansible.builtin.import_playbook: '{{ target_playbook }}'\n",
            )
            repo.write("2-child.play.yaml", "- hosts: child\n  tasks: []\n")
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.commit("initial")

            repo.write(
                "2-child.play.yaml",
                "- hosts: child\n  tasks:\n    - debug: {msg: changed}\n",
            )
            repo.commit("change potentially imported playbook")

            self.assertEqual(
                repo.affected(),
                [
                    "1-dynamic.play.yaml",
                    "2-child.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_unsupported_vars_directory_include_falls_back_to_all(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-direct.play.yaml",
                "- hosts: direct\n  vars_files: [vars/shared.yaml]\n  tasks: []\n",
            )
            repo.write(
                "2-directory.play.yaml",
                """
                - hosts: directory
                  tasks:
                    - ansible.builtin.include_vars:
                        dir: vars
                """,
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("vars/shared.yaml", "shared_value: before\n")
            repo.commit("initial")

            repo.write("vars/shared.yaml", "shared_value: after\n")
            repo.commit("change possibly directory-included vars")

            self.assertEqual(
                repo.affected(),
                [
                    "1-direct.play.yaml",
                    "2-directory.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_dynamic_variable_lookup_falls_back_for_shared_vars_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-direct.play.yaml",
                "- hosts: direct\n  tasks:\n    - debug: {msg: '{{ shared_value }}'}\n",
            )
            repo.write(
                "2-dynamic.play.yaml",
                """
                - hosts: dynamic
                  tasks:
                    - debug:
                        msg: "{{ lookup('vars', variable_name) }}"
                """,
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("group_vars/all/shared.yaml", "shared_value: before\n")
            repo.commit("initial")

            repo.write("group_vars/all/shared.yaml", "shared_value: after\n")
            repo.commit("change dynamically accessible shared var")

            self.assertEqual(
                repo.affected(),
                [
                    "1-direct.play.yaml",
                    "2-dynamic.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_renaming_inventory_into_ignored_path_selects_all(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write("0-one.play.yaml", "- hosts: one\n  tasks: []\n")
            repo.write("1-two.play.yaml", "- hosts: two\n  tasks: []\n")
            repo.write("inventory.yaml", "all: {hosts: {}}\n")
            repo.commit("initial")

            (repo.root / "tests").mkdir()
            (repo.root / "inventory.yaml").rename(repo.root / "tests/inventory.yaml")
            repo.commit("move inventory")

            self.assertEqual(
                repo.affected(),
                ["0-one.play.yaml", "1-two.play.yaml"],
            )

    def test_role_external_task_reference_is_traversed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-role.play.yaml",
                """
                - hosts: role
                  tasks:
                    - ansible.builtin.include_role:
                        name: consumer
                """,
            )
            repo.write(
                "2-direct.play.yaml",
                """
                - hosts: direct
                  tasks:
                    - ansible.builtin.include_tasks: apps/shared.yaml
                """,
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write(
                "roles/consumer/tasks/main.yaml",
                "- ansible.builtin.include_tasks: apps/shared.yaml\n",
            )
            repo.write("apps/shared.yaml", "- debug: {msg: before}\n")
            repo.commit("initial")

            repo.write("apps/shared.yaml", "- debug: {msg: after}\n")
            repo.commit("change role-external tasks")

            self.assertEqual(
                repo.affected(),
                ["1-role.play.yaml", "2-direct.play.yaml"],
            )

    def test_inline_vault_in_dependency_source_falls_back_to_all(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-vault.play.yaml",
                """
                - hosts: vault
                  vars:
                    secret: !vault |
                      $ANSIBLE_VAULT;1.1;AES256
                      AAAA
                  tasks:
                    - ansible.builtin.include_tasks: apps/shared.yaml
                """,
            )
            repo.write(
                "2-direct.play.yaml",
                """
                - hosts: direct
                  tasks:
                    - ansible.builtin.include_tasks: apps/shared.yaml
                """,
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("apps/shared.yaml", "- debug: {msg: before}\n")
            repo.commit("initial")

            repo.write("apps/shared.yaml", "- debug: {msg: after}\n")
            repo.commit("change tasks with opaque consumer")

            self.assertEqual(
                repo.affected(),
                [
                    "1-vault.play.yaml",
                    "2-direct.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_other_indirect_shared_variable_forms_fall_back_to_all(self) -> None:
        for expression in (
            "q('vars', variable_name)",
            "vars.get(variable_name)",
            "vars | dict2items",
            "{'sentinel': true} | combine(vars)",
            "{'outer': {'inner': true}} | combine(vars)",
            "q('varnames', variable_pattern)",
        ):
            with (
                self.subTest(expression=expression),
                tempfile.TemporaryDirectory() as directory,
            ):
                repo = Repository(pathlib.Path(directory))
                repo.write(
                    "1-direct.play.yaml",
                    "- hosts: direct\n  tasks:\n    - debug: {msg: '{{ shared_value }}'}\n",
                )
                repo.write(
                    "2-dynamic.play.yaml",
                    f'- hosts: dynamic\n  tasks:\n    - debug: {{msg: "{{{{ {expression} }}}}"}}\n',
                )
                repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
                repo.write("group_vars/all/shared.yaml", "shared_value: before\n")
                repo.commit("initial")

                repo.write("group_vars/all/shared.yaml", "shared_value: after\n")
                repo.commit("change dynamically accessible shared var")

                self.assertEqual(
                    repo.affected(),
                    [
                        "1-direct.play.yaml",
                        "2-dynamic.play.yaml",
                        "3-other.play.yaml",
                    ],
                )

    def test_wrapped_hostvars_condition_falls_back_for_shared_vars_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-direct.play.yaml",
                "- hosts: direct\n  tasks:\n    - debug: {msg: '{{ shared_value }}'}\n",
            )
            repo.write(
                "2-dynamic.play.yaml",
                """
                - hosts: dynamic
                  tasks:
                    - debug: {msg: dynamic}
                      when: "({'snapshot': hostvars})['snapshot'][inventory_hostname]['shared_value'] is defined"
                """,
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("group_vars/all/shared.yaml", "shared_value: before\n")
            repo.commit("initial")

            repo.write("group_vars/all/shared.yaml", "shared_value: after\n")
            repo.commit("change indirectly accessed shared var")

            self.assertEqual(
                repo.affected(),
                [
                    "1-direct.play.yaml",
                    "2-dynamic.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_with_varnames_falls_back_for_shared_vars_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-direct.play.yaml",
                "- hosts: direct\n  tasks:\n    - debug: {msg: '{{ shared_value }}'}\n",
            )
            repo.write(
                "2-dynamic.play.yaml",
                """
                - hosts: dynamic
                  tasks:
                    - debug: {msg: "{{ item }}"}
                      with_varnames: '^shared_'
                """,
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("group_vars/all/shared.yaml", "shared_value: before\n")
            repo.commit("initial")

            repo.write("group_vars/all/shared.yaml", "shared_value: after\n")
            repo.commit("change dynamically enumerated shared var")

            self.assertEqual(
                repo.affected(),
                [
                    "1-direct.play.yaml",
                    "2-dynamic.play.yaml",
                    "3-other.play.yaml",
                ],
            )

    def test_action_dependency_form_falls_back_to_all(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(pathlib.Path(directory))
            repo.write(
                "1-direct.play.yaml",
                "- hosts: direct\n  tasks:\n    - include_tasks: apps/shared.yaml\n",
            )
            repo.write(
                "2-action.play.yaml",
                "- hosts: action\n  tasks:\n    - action: include_tasks apps/shared.yaml\n",
            )
            repo.write("3-other.play.yaml", "- hosts: other\n  tasks: []\n")
            repo.write("apps/shared.yaml", "- debug: {msg: before}\n")
            repo.commit("initial")

            repo.write("apps/shared.yaml", "- debug: {msg: after}\n")
            repo.commit("change action-included tasks")

            self.assertEqual(
                repo.affected(),
                [
                    "1-direct.play.yaml",
                    "2-action.play.yaml",
                    "3-other.play.yaml",
                ],
            )


if __name__ == "__main__":
    unittest.main()
