import os
import sys

script_dir = os.path.dirname(__file__)
frontends_dir = os.path.abspath(os.path.join(script_dir, ".."))
repo_dir = os.path.abspath(os.path.join(frontends_dir, ".."))
if frontends_dir not in sys.path:
    sys.path.append(frontends_dir)
if repo_dir not in sys.path:
    sys.path.append(repo_dir)

from ga_switch_ui import render_admin_page, setup_switch_page

setup_switch_page("GA Switch Admin")
render_admin_page()
