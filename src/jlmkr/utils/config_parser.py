# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

import configparser
import io
import re

from donor.data import DEFAULT_CONFIG


# Used in parser getters to indicate the default behavior when a specific
# option is not found. Created to enable `None` as a valid fallback value.
_UNSET = object()


class KeyValueParser(configparser.ConfigParser):
    """Simple comment preserving parser based on ConfigParser.
    Reads a file containing key/value pairs and/or comments.
    Values can span multiple lines, as long as they are indented
    deeper than the first line of the value. Comments or keys
    must NOT be indented.
    """

    def __init__(self, *args, **kwargs):
        # Set defaults if not specified by user
        if "interpolation" not in kwargs:
            kwargs["interpolation"] = None
        if "allow_no_value" not in kwargs:
            kwargs["allow_no_value"] = True
        if "comment_prefixes" not in kwargs:
            kwargs["comment_prefixes"] = "#"

        super().__init__(*args, **kwargs)

        # Backup _comment_prefixes
        self._comment_prefixes_backup = self._comment_prefixes
        # Unset _comment_prefixes so comments won't be skipped
        self._comment_prefixes = ()
        # Starting point for the comment IDs
        self._comment_id = 0
        # Default delimiter to use
        delimiter = self._delimiters[0]
        # Template to store comments as key value pair
        self._comment_template = "#{0} " + delimiter + " {1}"
        # Regex to match the comment prefix
        self._comment_regex = re.compile(
            r"^#\d+\s*" + re.escape(delimiter) + r"[^\S\n]*"
        )
        # Regex to match cosmetic newlines (skips newlines in multiline values):
        # consecutive whitespace from start of line followed by a line not starting with whitespace
        self._cosmetic_newlines_regex = re.compile(r"^(\s+)(?=^\S)", re.MULTILINE)
        # Dummy section name
        self._section_name = "a"

    def _find_cosmetic_newlines(self, text):
        # Indices of the lines containing cosmetic newlines
        cosmetic_newline_indices = set()
        for match in re.finditer(self._cosmetic_newlines_regex, text):
            start_index = text.count("\n", 0, match.start())
            end_index = start_index + text.count("\n", match.start(), match.end())
            cosmetic_newline_indices.update(range(start_index, end_index))

        return cosmetic_newline_indices

    # TODO: can I create a solution which not depends on the internal _read method?
    def _read(self, fp, fpname):
        lines = fp.readlines()
        cosmetic_newline_indices = self._find_cosmetic_newlines("".join(lines))
        # Preprocess config file to preserve comments
        for i, line in enumerate(lines):
            if i in cosmetic_newline_indices or line.startswith(
                self._comment_prefixes_backup
            ):
                # Store cosmetic newline or comment with unique key
                lines[i] = self._comment_template.format(self._comment_id, line)
                self._comment_id += 1

        # Convert to in-memory file and prepend a dummy section header
        lines = io.StringIO(f"[{self._section_name}]\n" + "".join(lines))
        # Feed preprocessed file to original _read method
        return super()._read(lines, fpname)

    def read_default_string(self, string, source="<string>"):
        # Ignore all comments when parsing default key/values
        string = "\n".join(
            [
                line
                for line in string.splitlines()
                if not line.startswith(self._comment_prefixes_backup)
            ]
        )
        # Feed preprocessed file to original _read method
        return super()._read(io.StringIO("[DEFAULT]\n" + string), source)

    def write(self, fp, space_around_delimiters=False):
        # Write the config to an in-memory file
        with io.StringIO() as sfile:
            super().write(sfile, space_around_delimiters)
            # Start from the beginning of sfile
            sfile.seek(0)

            line = sfile.readline()
            # Throw away lines until we reach the dummy section header
            while line.strip() != f"[{self._section_name}]":
                line = sfile.readline()

            lines = sfile.readlines()

        for i, line in enumerate(lines):
            # Remove the comment id prefix
            lines[i] = self._comment_regex.sub("", line, 1)

        fp.write("".join(lines).rstrip())

    # Set value for specified option key
    def my_set(self, option, value):
        if isinstance(value, bool):
            value = str(int(value))
        elif isinstance(value, list):
            value = str("\n    ".join(value))
        elif not isinstance(value, str):
            value = str(value)

        super().set(self._section_name, option, value)

    # Return value for specified option key
    def my_get(self, option, fallback=_UNSET):
        return super().get(self._section_name, option, fallback=fallback)

    # Return value converted to boolean for specified option key
    def my_getboolean(self, option, fallback=_UNSET):
        return super().getboolean(self._section_name, option, fallback=fallback)


class ExceptionWithParser(Exception):
    def __init__(self, parser, message):
        self.parser = parser
        self.message = message
        super().__init__(message)


def parse_config_file(jail_config_path):
    config = KeyValueParser()
    # Read default config to fallback to default values
    # for keys not found in the jail_config_path file
    config.read_default_string(DEFAULT_CONFIG)
    try:
        with open(jail_config_path, "r") as fp:
            config.read_file(fp)
        return config
    except FileNotFoundError:
        eprint(f"Unable to find config file: {jail_config_path}.")
        return
