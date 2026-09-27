# Nginx and application sites

Run `nginx` to install the shared proxy, then use `nginx_site` from each
application's tasks. The application creates its Docker networks and content
directories and supplies its own routing, network and mount requirements:

```yaml
- name: Register the application's site
  ansible.builtin.include_role:
    name: nginx_site
  vars:
    nginx_site_name: example
    nginx_site_server_names: [example.internal.test]
    nginx_site_certificate: internal.test
    nginx_site_upstream: http://example:8080
    nginx_site_networks: [example]
```

Sites default to internal access. Use `nginx_site_kind: external` for the
external listeners. Certificates must already exist in
`/srv/certificates/<certificate group>/{fullchain,key}.pem`.

Each site owns three files under `/srv/app/nginx`: `sites/<name>.conf`,
`network/<name>.list` and `mount/<name>.list`. They persist across separate
playbook runs. The startup script collects and deduplicates all sites' networks
and mounts whenever it creates the container. Shared requirements remain until
the last site referencing them is removed.

To remove a site, call `nginx_site` with its name and `nginx_site_state: absent`.
This deletes all three files. No central network or mount list is needed.

## Applying changes

Each role validates configuration in a normal task and owns its restart handler.
The site role uses the installed `start` script and systemd service; it does not
include tasks from the infrastructure role:

1. Run `nginx -t` in a temporary container with the collected networks and mounts.
2. If validation succeeds and files changed, notify the role's restart handler.
3. Flush handlers to restart the service before returning.

The roles do not wait for HTTP readiness. Integration tests retry their HTTP
requests after a restart.

Rejected configurations do not queue a restart. A caller can correct the input
and retry within the same play.

Every configuration, network or mount change takes this path. Brief downtime
and interrupted requests during updates are expected. Unchanged files do not
trigger a restart, but their configuration is still validated. Check mode
previews file changes and skips activation.

There is no automatic rollback. If validation fails, the running container is
not restarted, but the edited files remain on disk. Fix the input and rerun the
role before rebooting or restarting nginx. If startup fails after validation,
inspect the service journal, fix the cause and restart the service.

## Certificates and lifecycle

Certificate issuance and installation belong to ACME. After installing a
renewed certificate, `/srv/app/nginx/reload` validates and reloads the running
nginx container. To validate staged certificates first, run
`/srv/app/nginx/start test /path/to/staged-certificates`.

`nginx_state: absent` removes the service and its base network, retaining the
site registrations and certificate files. Application networks belong to the
applications. Remove sites before removing the proxy service or deleting their
networks or mounted content.

The opt-in live checks are in `tests/integration/nginx.play.yaml`. They use
temporary ports and fixtures and require `nginx_live_test=true`.
