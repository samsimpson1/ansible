---
description: Remove all resources managed by tasks in the currently open file
---

Analyze the currently open file and reverse all Ansible operations defined in it.

For each task in the file:
1. Identify role inclusions and resource definitions
2. Create reversal operations using the repository's patterns

Key reversal patterns:
- **Custom roles** (docker_service, caddy, oauth2_proxy, backup, etc.): Add `state: absent` to the role vars
- **Built-in modules**: Change `state: present` → `state: absent`, `state: started` → `state: stopped` then `absent`
- **Files/directories**: Use `state: absent`
- **Packages**: Use `state: absent`
- **Users/groups**: Use `state: absent`

Output a complete Ansible tasks file that:
- Processes tasks in reverse order (bottom to top)
- Adds `state: absent` to all custom role inclusions
- Reverses all built-in module operations
- Includes comments explaining what each reversal does
- Is idempotent and safe to run multiple times
- Handles dependencies correctly (e.g., stop services before removing config)

The output should be a ready-to-run Ansible tasks file that can clean up all resources.
