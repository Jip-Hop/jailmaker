# Debian Docker Jail Template

## Setup

Check out the [config](./config) template file. You may provide it when asked during `jlmkr create` or, if you have the template file stored on your NAS, you may provide it directly by running `jlmkr create --start --config /mnt/tank/path/to/docker/config mydockerjail`. If you want the `nvidia-container-toolkit` to be installed, ensure you set `gpu_passthrough_nvidia=1` when creating the jail.