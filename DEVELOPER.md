# Developer notes

## Building Jailmaker

No external dependencies are needed to perform a simple build from the project directory.

    python3 -m scripts.build

Anything beyond this is *completely optional…*

## Development mode

Jailmaker's user-facing design and important safety features tend to get in the way of rapid development. To run directly from the editable source code, create an external configuration file.

    mkdir -p ~/.local/share
    cat <<EOF >~/.local/share/jailmaker.conf
    [DEFAULT]
    ignore_owner = 1
    jailmaker_dir = /mnt/pool/jailmaker
    EOF

If present, this file will override traditional self-detection of the Jailmaker directory.

## Code quality tooling

Additional tools for testing, coverage, and code quality review are available through [Hatch][1]. Install them in a self-contained, disposable virtual environment.

    python3 -m venv --without-pip .venv
    curl -OL https://bootstrap.pypa.io/pip/pip.pyz
    .venv/bin/python3 pip.pyz install pip hatch
    rm pip.pyz

Activate a session inside the virtual environment. (For more information see the `venv` [tutorial][2].)

    source .venv/bin/activate

Use `hatch` to build, test, lint, etc.

    hatch build

## Integration testing

See [`test/README.md`](./test/README.md).

[1]: https://hatch.pypa.io/
[2]: https://docs.python.org/3/tutorial/venv.html
