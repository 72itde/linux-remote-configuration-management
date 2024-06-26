# changelog


## 0.6.0

- Add logging to (remote) Loki. Authentication has to be done via basic auth for now.

## 0.5.2

- Switch back from `SafeConfigParser` to `ConfigParser` because `SafeConfigParser` is deprecated in Python 3.12
- add LOGGING-section and url-parameter for Loki as logging target. I assume authentication is always mandatory and credentials are the same as for Gitlab

## 0.5.1

- remove config file, add demo-config-file

## 0.5

- Add new variable `delay_before_start_random_max_seconds` (default: 60) for a random delay.
- Implement functionality for variables `delay_before_start_seconds` and `delay_before_start_random_max_seconds`
- switch from `ConfigParser` to `SafeConfigParser`
- add defaults for `delay_before_start_seconds`, `delay_before_start_random_max_seconds`, `branch`, `playbook`, `authentication_required`, `reboot_cronjob`, `hourly_cronjob`, `daily_cronjob`, `pidfile` so no breaking changes to v0.4
- fix wrong version in package build
- add changelog file
