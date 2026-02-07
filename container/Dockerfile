FROM ubuntu:24.04

RUN apt-get update && apt-get install -y curl gnupg sudo && \
    curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
    gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" | \
    tee /etc/apt/sources.list.d/1password.list

RUN apt-get update && apt-get install -y git openssh-client python3-pip 1password-cli

RUN pip install --break-system-packages ansible ansible-lint requests python-dateutil

LABEL org.opencontainers.image.source="https://github.com/samsimpson1/ansible"