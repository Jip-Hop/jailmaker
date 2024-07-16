#!/usr/bin/env python3
# SPDX-FileCopyrightText: © 2024 Jip-Hop and the Jailmakers <https://github.com/Jip-Hop/jailmaker>
#
# SPDX-License-Identifier: LGPL-3.0-only

if __name__ == "__main__":
    import subprocess
    import sys
    import os

    # Get the path of the currently running script
    current_path = os.path.realpath(__file__)

    # Define the relative path you want to resolve
    relative_path = "src/jlmkr"

    # Resolve the relative path
    script_path = os.path.join(os.path.dirname(current_path), relative_path)
    
    # Get the arguments passed to the current script
    args = sys.argv[1:]

    # Pass all arguments to the other script using subprocess
    subprocess.run(["python3", script_path] + args, check=True)
    
