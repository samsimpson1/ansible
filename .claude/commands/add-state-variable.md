# Add State Variable to Role

Implement the state variable pattern for an Ansible role to support both `present` and `absent` states, following the pattern established in GitHub issue #38.

## Usage

```
/add-state-variable <role_name>
```

Example: `/add-state-variable my_new_role`

If no role name is provided, ask the user which role to update.

## Instructions

For the specified role (from parameter or user input):

1. **Add state variable to defaults/main.yaml**
   - If the file doesn't exist, create it
   - Add `<role_name>_state: present` as the default value

2. **Update tasks/main.yaml with conditional logic**

   **For `state: present`:**
   - Add `when: <role_name>_state == 'present'` to all resource creation tasks
   - This includes:
     - Package installations
     - User/group creation
     - Directory creation
     - File/template creation
     - Service starts/enables
     - Cron job creation
     - Any other resource creation tasks

   **For `state: absent`:**
   - Add removal tasks at the end of the file
   - Remove resources in reverse order (cron jobs → scripts → files → directories → services → users/groups)
   - Add `when: <role_name>_state == 'absent'` to all removal tasks
   - Removal tasks should include:
     - Remove cron jobs (use `state: absent`)
     - Remove scripts and config files
     - Remove directories (with `state: absent` - automatically recursive)
     - Stop and disable services
     - Remove users (with `remove: true` to delete home directory)
     - Remove groups
   - **Do NOT remove system packages** (they may be used by other roles)

3. **Handle nested role calls**
   - If the role calls other roles (e.g., `docker_service`, `oauth2_proxy`), pass the state variable down:
     ```yaml
     vars:
       nested_role_state: "{{ parent_role_state }}"
     ```

4. **Add default filters for facts used only in present state**
   - If setting facts/variables that are only defined when `state: present`, add `| default([])` or `| default({})` filters when using them
   - This prevents undefined variable errors when `state: absent`

## Examples

### Example 1: Simple role with cron job

**defaults/main.yaml:**
```yaml
my_role_state: present
```

**tasks/main.yaml:**
```yaml
- name: Install packages
  ansible.builtin.package:
    name: my-package
    state: present
  when: my_role_state == 'present'

- name: Create script
  ansible.builtin.template:
    src: script.sh.j2
    dest: /opt/my-script.sh
    mode: '0755'
  when: my_role_state == 'present'

- name: Create cron job
  ansible.builtin.cron:
    name: "My scheduled job"
    job: "/opt/my-script.sh"
    minute: "0"
    hour: "2"
  when: my_role_state == 'present'

# Removal tasks
- name: Remove cron job
  ansible.builtin.cron:
    name: "My scheduled job"
    state: absent
  when: my_role_state == 'absent'

- name: Remove script
  ansible.builtin.file:
    path: /opt/my-script.sh
    state: absent
  when: my_role_state == 'absent'
```

### Example 2: Role that calls docker_service

**defaults/main.yaml:**
```yaml
app_role_state: present
```

**tasks/main.yaml:**
```yaml
- name: Create data directory
  ansible.builtin.file:
    path: /srv/app/data
    state: directory
  when: app_role_state == 'present'

- name: App service
  ansible.builtin.include_role:
    name: docker_service
  vars:
    docker_service_id: "my-app"
    docker_service_image: "my-app:latest"
    docker_service_state: "{{ app_role_state }}"  # Pass state down

# Removal tasks
- name: Remove data directory
  ansible.builtin.file:
    path: /srv/app/data
    state: absent
  when: app_role_state == 'absent'
```

## Notes

- The state variable makes roles idempotent and reversible
- Always use `state: absent` for file removal (works for both files and directories)
- Directories are removed recursively automatically
- User removal should use `remove: true` to delete home directory
- System packages should generally NOT be removed (they may be shared)
- When in doubt, follow the pattern from existing roles: `docker_service`, `oauth2_proxy`, `acme_manager`, `acme_client`, `backup`, `caddy`, `docker_host`

## Implementation Steps

1. Read the role's tasks/main.yaml to understand what resources it manages
2. Create or update defaults/main.yaml with the state variable
3. Add `when: <role>_state == 'present'` to all creation tasks
4. Add removal tasks at the end for `when: <role>_state == 'absent'`
5. Test the changes mentally by walking through both states
6. Report what resources will be created (present) and removed (absent)
