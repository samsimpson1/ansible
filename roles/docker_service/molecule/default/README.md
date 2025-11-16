# Docker Service Role Tests

This directory contains Molecule tests for the `docker_service` Ansible role.

## Overview

These tests verify that the `docker_service` role correctly:
- Creates systemd service units for Docker containers
- Configures network settings (single and multiple networks)
- Sets up port mappings
- Mounts volumes
- Configures environment variables
- Sets user and group permissions
- Enables privileged mode when requested
- Configures PID and cgroup namespaces
- Handles service state management (present/absent)
- Manages service enabling/disabling

## Prerequisites

Install Molecule and its dependencies:

```bash
pip install molecule molecule-docker ansible-lint docker
```

Install required Ansible collections:

```bash
ansible-galaxy collection install -r requirements.yml
```

## Running Tests

### Run all tests (converge + verify)
```bash
cd /home/user/ansible/roles/docker_service
molecule test
```

### Run individual test phases

**Converge (apply the role):**
```bash
molecule converge
```

**Verify (run verification tests):**
```bash
molecule verify
```

**Destroy test environment:**
```bash
molecule destroy
```

**Run full test cycle:**
```bash
molecule test
```

## Test Scenarios

The test suite includes the following scenarios:

1. **Basic Service** - Minimal configuration with default settings
2. **Single Network** - Service attached to one Docker network
3. **Multiple Networks** - Service attached to multiple Docker networks
4. **Port Mappings** - Service with exposed ports
5. **Volume Mounts** - Service with mounted volumes
6. **Environment Variables** - Service with environment variables
7. **User and Groups** - Service running as specific user/group
8. **Privileged Mode** - Service running in privileged mode
9. **PID Namespace** - Service with custom PID namespace
10. **Cgroup Namespace** - Service with custom cgroup namespace
11. **Custom Command** - Service with custom command arguments
12. **Disabled Service** - Service that is not enabled on boot
13. **Comprehensive** - Service with all options combined
14. **Service Removal** - Verification that services can be removed

## Verification Tests

The verify playbook checks:
- Service unit files are created in `/etc/systemd/system/`
- Service content includes correct Docker run commands
- Network, port, volume, and other configurations are present
- Services are running and in the correct state
- Disabled services are not enabled
- Removed services no longer exist

## Test Platform

Tests run on:
- Ubuntu 22.04 (geerlingguy/docker-ubuntu2204-ansible)
- Docker-in-Docker configuration for testing containerized services

## Troubleshooting

**Tests fail with "Docker not found":**
Ensure Docker is installed on your host system and the Molecule Docker driver is installed.

**Permission errors:**
The test container runs in privileged mode to allow Docker operations.

**Network errors:**
Ensure the Docker networks are created before services that use them.
