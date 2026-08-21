# client preparation playbooks

Ansible playbooks that install everything lrcm needs on a client and make sure
cron is running. Run them once per machine, before lrcm itself.

| playbook | covers |
| --- | --- |
| [playbook-debian-family.yaml](playbook-debian-family.yaml) | Debian 12/13, Ubuntu 24.04/26.04 LTS, Linux Mint, LMDE, elementary OS |
| [playbook-fedora.yaml](playbook-fedora.yaml) | Fedora |

Both playbooks run against the local machine and need root:

```sh
sudo ansible-playbook -i localhost, -c local client-setup/playbook-debian-family.yaml
```

The package names are deliberately kept at `state: present` rather than
`state: latest` - keeping the system up to date is the distribution's job, not
lrcm's, and `latest` makes every run report a change.
