Create a jail
`jlmkr create JAILNAME`

Start a jail
`jlmkr start JAILNAME`

Stop a jail
`jlmkr stop JAILNAME`

Check jail status
`jlmkr status JAILNAME`

Delete a jail and remove it's files (requires confirmation)
`jlmkr remove JAILNAME`

See list of jails (including running, non running, distro, startup state, and IP)
`jlmkr list`

See list of running jails
`machinectl list`

Execute a command inside a jail from the TrueNAS shell
`jlmkr exec JAILNAME COMMAND`

Execute a bash command inside a jail from the TrueNAS shell
`jlmkr exec JAILNAME bash -c 'BASHCOMMAND'`

Switch into the jail's shell
`machinectl shell JAILNAME`

View a jail's logs
`jlmkr log JAILNAME`

Edit a jail's config
`jlmkr edit JAILNAME`
