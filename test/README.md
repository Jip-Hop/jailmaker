# Jailmaker Testing

This readme documents the [test-jlmkr](./test-jlmkr) script.

The script has 2 optional parameter invocation sets:
* `<jail type>` [`<jail name>`]
* `<template/path>` `<jail name>`

If the script is invoked without arguments, it will use the default configuration and name the test jail `default-jail`.

Legend:
| Arg name | Description |
|-|-|
| `<jail type>` | The template dir-name in `$JLMKR_PATH/templates` (it will load the `config` file within it) |
| `<jail name>`\* | The name of the jail that will be created and destroyed during the testing. <br/> If not supplied, the default is `<jail type>-test` |
| `<template/path>` | relative or absolute path to a config template. (`<jail name>` must be supplied) |

> PRE-REQUISITE:   
> \* WARNING: If `<jail name>` exists, it will be removed.

Environment variables control the test behavior:
| Variable name | Default |Description |
|-|:-:|-|
|`JLMKR_PATH`|optional - see description|When unspecified, and `SCALE_POOL_ROOT` is defined, it will check if `$SCALE_POOL_ROOT/jailmaker` contians the `jlmkr.py` script. Otherwise, it will use `${PWD:-.}` instead (the local dir)|
|`SCALE_POOL_ROOT`|optional|Used to define `JLMKR_PATH`, it should point to the root of the ZFS dataset hosting the `jailmaker` script dir. |
|`STOP`|0| `0` - perform all non-blocking tests<br/>`l` - only list and images, nothing else<br/>`i` - interactive test, includ console-blocking waiting for input tests (edit and shell)|
|`FULL_TEST`|0|`0` - perform a single run<br/>`1`* - perform a full-test|

> \* `FULL_TEST=1` will perform a full run ONLY when passing a `<jail type>` (will not work with `<template/path>`)

## Type of Run

In `STOP=0` (the default) all steps, with the interactive steps manipulated to run without prompting.
The interactive steps are steps which prompt the user for input. These are `shell` and `edit`.
In `STOP=i` all steps will be performed, and interactive steps will wait for user input.

A special shorthand option exists `STOP=l` which will just run `list` and `images`, this is to test basic invocation of the script regardless of specific jails. This is also the only non-destructive mode.

## Single Run

By default, a single run in non-interactive mode will run, it runs from whatever CWD path the shell is in.

## Full Test

The Full test, starts with the single run (whether interactive or not), if successful, it continues to perform non-interactive tests with the following parameters:

| S | F | CWD | Path to template |
|:-:|:-:|-|-|
|+|+|`$JLMKR_PATH`|`./templates/$JAIL_TYPE/config`|
||+|`JLMKR_PATH`|`templates/$JAIL_TYPE/config`|
||+|`JLMKR_PATH`|`$SCALE_POOL_ROOT/jailmaker/$JAIL_CONFIG`|
||+| ~ |`JLMKR_PATH/$JAIL_CONFIG`|
||+| ~ | a _temporary file_, it's contents will be copied form the `<jail type>`'s config file. |

> S - Single Run | F - Full Test

### Example invocation:
Single run, interactive mode, `nixos` jail type:

```bash
cd ${SCALE_POOL_ROOT:?must define this before running}/jailmaker \
&& sudo STOP=i SCALE_POOL_ROOT=$SCALE_POOL_ROOT $SCALE_POOL_ROOT/jailmaker/test/test-jlmkr nixos
```

Full test, default settings, `nixos` jail type:

```bash
cd ${JLMKR_PATH:?must define this before running} \
&& sudo FULL_TEST=1 ./test/test-jlmkr nixos
```

### What to expect
A full non-interactive test run with `nixos` (which is rather lean, yet tests both pre hook and init scripts) ran for ~260 seconds.

The report summary outputs what type of run it was with CWD and path to config file and for each step, a green checkmark indicating ✅ Success, a red X symbol following the exit code❌(`<error code>`) for erros. Both follow the command executed.
In the case a step wasn't performed, a blank checkbox 🔳 followed by the name of the step will be listed.
The report is always listed in alphabetic order (although the steps are performed in an order that allows testing as much as possible while taking into account dependent steps.