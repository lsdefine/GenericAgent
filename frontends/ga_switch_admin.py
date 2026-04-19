import os
import sys

script_dir = os.path.dirname(__file__)
if script_dir not in sys.path:
    sys.path.append(script_dir)
repo_dir = os.path.abspath(os.path.join(script_dir, ".."))
if repo_dir not in sys.path:
    sys.path.append(repo_dir)

from ga_switch_ui import render_admin_page, setup_switch_page

setup_switch_page("GA Switch Admin")
render_admin_page()
