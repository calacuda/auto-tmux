"""
auto-tmux

cli to allow for the automation and creation of tmux sesisons all organized in human readable yaml


By: Calacuda | MIT License | Epoch Jume 6, 2023

TODO:
- make async
"""


import yaml
import asyncio
import libtmux
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
from os.path import expanduser, isfile
from logging import info, error, critical, debug, basicConfig, INFO, DEBUG, getLogger


class StringWrapper(str):
    def __init__(self, s):
        super().__init__()
        self.str = s

    def format(self, *args, **kwargs):        
        """over rides the default string format method to put squarbrackets around "levlename" before appllying padding"""
        if kwargs.get("levelname"):    
            kwargs["levelname"] = f"[{kwargs['levelname']}]:"
            kwargs["levelname"] = "{0:11} | ".format(kwargs["levelname"])
       
        pos_args = args if len(args) == 3 else [None, None, None]
        res = self.str.format(*pos_args, **kwargs)
        
        if "\n" in res:
            header = ' ' * 12 + "| "
            res = "\n".join(line if not i else f"{header}{line}" for i, line in enumerate(res.split("\n")))
        
        return res


LOG = getLogger(__name__)
basicConfig(
    level=INFO,
    style="{",
    format=StringWrapper("{levelname:11}{message}"),
)
layout_dir = expanduser("~/.config/auto-tmux/layouts/")


def is_full_path(f_name):
    """
    used to check if `f_name` is all ready a usable path. 
    usable paths include full paths or files in the current directory.
    """
    from os import listdir
    from os.path import isfile
    
    # files in currnet directory
    cur_dir_files = [f for f in listdir('.') if isfile(f) and (f.endswith(".yaml") or f.endswith(".yml"))] 

    return "/" in f_name or f_name in cur_dir_files

def is_know_layout(f_name):
    """checks if the file name is in the layout_dir directory, returns the layout name if is exists."""
    from os import listdir
    from os.path import isfile
    
    # files in currnet directory
    known_layouts = [f for f in listdir(layout_dir) if isfile(layout_dir + f) and (f.endswith(".yaml") or f.endswith(".yml"))]  
    selected_names = {f_name, f_name + ".yaml", f_name + ".yml"}

    for layout in known_layouts:
        if layout in selected_names:
            return layout

    return ""


def get_full_path(f_name):
    """returns the full file path"""
    path = layout_dir
    known_layout = is_know_layout(f_name)

    if known_layout:
        path += known_layout
    elif not is_full_path(f_name):
        path += f_name
    else:
        path = f_name

    if isfile(path):
        return path
    else:
        critical(f"the suplied file_name: \"{f_name}\", assumed to be located at: \"{path}\", does not exists.")
        exit(1)


def parse_layout(layout_path):
    """parses the yaml file"""
    with open(layout_path, "r") as layout_text:
        return yaml.safe_load(layout_text)


async def run_cmd(thing, cmd):
    """runs a command (cmd) in a window/pane (thing)"""
    await asyncio.sleep(0.75)
    thing.send_keys(cmd, enter=True)


async def setup_pane(pane_conf, tmux_window):
    valid_directions = ["hori", "vert", "vertical", "horizontal"]

    if not pane_conf.get("direction").lower() in valid_directions:
        # window_name = tmux_window.get('name') if tmux_window.get('name') else "undefined-name"
        LOG.error(f"confing value for key 'direction' is invalid; must be one of {valid_directions}." "\n"
                  f"could not set up the pane with config: {pane_conf}, in window: {window_name}")
        return 1

    tmux_pane = tmux_window.split_window(
        vertical=pane_conf.get("direction").lower().startswith("v"),
        # shell=pane_conf.get("cmd"),
        percent=pane_conf.get("percent")
    )

    await run_cmd(tmux_pane, pane_conf.get("cmd"))

    return 0

async def setup_window(window, tmux_session):
    """sets up a tmux window in tmux_session"""
    tmux_window = tmux_session.new_window(
        attach=False,
        window_name=window.get("name"),
        start_directory=window.get("dir"),
        # pane_start_command=window.get("cmd")
    )
    
    if window.get("cmd"):
        await run_cmd(tmux_window.panes[0], window.get("cmd"))

    ec = 0

    if window.get("panes"):
        ec += sum(await asyncio.gather(*[ setup_pane(pane_conf, tmux_window) for pane_conf in window.get("panes") ])) 

    return ec

    
async def setup_session(session, server) -> (str, bool):
    """sets up a list of sessions"""
    session_name = session.get("name")
    
    try:
        server.sessions.get(session_name=session_name)
    except libtmux._internal.query_list.ObjectDoesNotExist:
        pass
    else:
        LOG.error(f"a session named {session_name} already exists. reconfiguring existing" "\n" 
                   "sessions is not yet implemented but, is planned for the future.")
        return 1

    tmux_session = server.new_session(session_name)
    # tmux_session = server.sessions.get(session_name=session.get("name"))
    
    n_errors = sum(await asyncio.gather(*[ setup_window(window, tmux_session) for window in session.get("windows") ]))
    tmux_session.windows[0].kill_window()
    
    if n_errors != 0:
        LOG.error(f"encountered {n_errors} while setting up session named: {session_name}.")

    return n_errors


async def load_layout(layout_path, progress_bar=False):
    """loads the layout located at `layout_path`"""
    info(f"loading layout config from \"{layout_path}\"...")
    layout = parse_layout(layout_path)
    server = libtmux.Server()
    # echo = tqdm.write if progress_bar else print
    iter = tqdm(layout) if progress_bar else layout

    # if progress_bar:
    #     n_errors = sum([setup_session(session, tqdm.write) for session in tqdm(layout)])
    # else:
    #     n_errors = sum([setup_session(session, print) for session in layout]) 
    n_errors = sum(await asyncio.gather(*[ setup_session(session, server) for session in iter ]))

    if n_errors != 0:
        LOG.error(f"encountered {n_errors} errors while seting up the \"{layout_path}\" layout.")
    
    LOG.info(f"layout config from \"{layout_path}\" has been loaded.")

    return layout

def _get_cmd_args():
    """uses argparse to get command line arguments"""
    import argparse

    # TODO: add an "--exclude" arg to exclude certain windows
    # TODO: add an "--include" arg to only include certain windows (should be mutually exclusive with "--enclude")

    parser = argparse.ArgumentParser(
        prog='auto-tmux',
        description='automate the creation of tmux sessions',
    )
    parser.add_argument(
        "session",
        # dest="session",
        type=str,
        help="the sessison layout to load"
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action='store_true',
        help="turns off the progress bar",
    )
    parser.add_argument(
        "-t",
        "--target",
        dest='target',
        const=False,
        default=True,
        action='store',
        nargs='?',
        type=str,
        help="(optional) defines a session to attach to after the sessions are loaded."
    )
    parser.add_argument(
        "-d",
        dest="no_connect",
        action='store_true',
        help="dont autoconnect. (by default the current terminal will be autoconnected to either the session specified by the '--target' flag or tmux's best guess)",
    )

    return parser.parse_args()


async def _run_cli():
    """main function that runs the cli"""
    with logging_redirect_tqdm():
        args = _get_cmd_args()
        LOG.debug(f"args: {args}")

        layout_path = get_full_path(args.session)
        # LOG.debug(f"path to layout file: {layout_path}")
        layout = await load_layout(layout_path, not args.quiet)
        
        if not args.no_connect:
            from os import system
            session = None
            
            if type(args.target) != bool:
                session = args.target
            elif len(layout) == 1 and layout[0].get("name"): 
                session = layout[0].get("name")
            elif len(layout) == 1 and not layout[0].get("name"):
                session = ""
            else:
                LOG.info(f"the '--traget' flag was not passed a value and there is more then one session in" "\n" 
                          "the layout in the config, letting tmux guess.")
                session = ""

            LOG.info(f"attaching to session: \"{session if session else 'TMUX BEST GUESS'}\"")
            system(f"tmux attach {'-t ' + session if session else ''}")


def run_cli():
    """runs the async cli"""
    asyncio.run(_run_cli())


if __name__ == "__main__":
    run_cli()