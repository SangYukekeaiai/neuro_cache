import os, sys, yaml, json
import numpy as np

from collections import OrderedDict
from typing import Union
from yamlordereddictloader import SafeDumper
from yamlordereddictloader import SafeLoader
from loguru import logger


class bcolors:
    """
    default color palette
    """
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    red = "#EF553B"
    orange = "#E58606"
    yellow = "#FABD2F"
    green = "#9CC424"
    cyan = '#6FD19F'
    blue = "#FABD2F"
    purple = "#AB82FF"
    gray = "#CCCCCC"
    gray2 = "#999999"
    gray3 = "#666666"
    gray4 = "#333333"

    
    ResetAll = "\033[0m"
    Bold       = "\033[1m"
    Dim        = "\033[2m"
    Underlined = "\033[4m"
    Blink      = "\033[5m"
    Reverse    = "\033[7m"
    Hidden     = "\033[8m"

    ResetBold       = "\033[21m"
    ResetDim        = "\033[22m"
    ResetUnderlined = "\033[24m"
    ResetBlink      = "\033[25m"
    ResetReverse    = "\033[27m"
    ResetHidden     = "\033[28m"

    Default      = "\033[39m"
    Black        = "\033[30m"
    Red          = "\033[31m"
    Green        = "\033[32m"
    Yellow       = "\033[33m"
    Blue         = "\033[34m"
    Magenta      = "\033[35m"
    Cyan         = "\033[36m"
    LightGray    = "\033[37m"
    DarkGray     = "\033[90m"
    LightRed     = "\033[91m"
    LightGreen   = "\033[92m"
    LightYellow  = "\033[93m"
    LightBlue    = "\033[94m"
    LightMagenta = "\033[95m"
    LightCyan    = "\033[96m"
    White        = "\033[97m"

    BackgroundDefault      = "\033[49m"
    BackgroundBlack        = "\033[40m"
    BackgroundRed          = "\033[41m"
    BackgroundGreen        = "\033[42m"
    BackgroundYellow       = "\033[43m"
    BackgroundBlue         = "\033[44m"
    BackgroundMagenta      = "\033[45m"
    BackgroundCyan         = "\033[46m"
    BackgroundLightGray    = "\033[47m"
    BackgroundDarkGray     = "\033[100m"
    BackgroundLightRed     = "\033[101m"
    BackgroundLightGreen   = "\033[102m"
    BackgroundLightYellow  = "\033[103m"
    BackgroundLightBlue    = "\033[104m"
    BackgroundLightMagenta = "\033[105m"
    BackgroundLightCyan    = "\033[106m"
    BackgroundWhite        = "\033[107m"


def strip_list(input_list: list) -> list:
    """
    strip leading and trailing spaces for each list item
    """
    l = []

    for e in input_list:
        e = e.strip()
        if e != '' and e != ' ':
            l.append(e)

    return l


def check_type(input, type) -> None:
    """
    check whether input is the required type
    """
    assert isinstance(input, type), logger.error(f'Invalid type <{type}>.')
    

def check_file_list(file_list: list) -> None:
    """
    check whether all files in the list exist
    """
    for file in file_list:
        assert os.path.exists(file), logger.error(f'Invalid file <{file}>.')


def clean_file_list(file_list: list) -> None:
    """
    delete files in the list, if they exist
    """
    for file in file_list:
        if os.path.exists(file):
            logger.warning(f'Delete file <{file}>.')
            os.remove(file)


def draw_event_graph(event_graph, output: str, fmt: str = None) -> None:
    """
    Render an ArchxGraph to a file using Graphviz.

    Parameters
    ----------
    event_graph : ArchxGraph
        The Rust-backed graph object.
    output : str
        Output file path. The extension determines the format unless `fmt`
        is given explicitly (e.g. 'pdf', 'png', 'svg').
    fmt : str, optional
        Override the output format. When omitted the format is inferred
        from the file extension; defaults to 'pdf' if there is no extension.
    """
    try:
        import graphviz
    except ImportError:
        logger.error(
            "graphviz package is not installed. "
            "Install it with:  conda install graphviz python-graphviz  "
            "or:  pip install graphviz  (also requires the graphviz system package)."
        )
        return

    output = os.path.abspath(output)
    root, ext = os.path.splitext(output)
    if fmt is None:
        fmt = ext.lstrip('.') if ext else 'pdf'

    # Graphviz renders to `root.fmt`; passing `output` can duplicate suffixes.
    dot = graphviz.Digraph(format=fmt)
    dot.attr(rankdir='TB', size='10,10')

    # Node styling: events (non-leaf) vs modules (leaf)
    for name in event_graph.get_all_node_names():
        if event_graph.is_leaf(name):
            dot.node(name, label=name, shape='box', style='filled', fillcolor='#AED6F1')
        else:
            dot.node(name, label=name, shape='ellipse', style='filled', fillcolor='#A9DFBF')

    # Edges: label with count, penwidth proportional to count
    for src in event_graph.get_all_node_names():
        for tgt in event_graph.get_out_neighbors(src):
            count = event_graph.get_edge_count(src, tgt)
            penwidth = max(0.5, min(count, 8.0))
            dot.edge(src, tgt, label=f'{count:g}', penwidth=str(penwidth))

    dot.render(root, cleanup=True)
    logger.success(f'Draw event graph to <{root}.{fmt}>.')


def create_dir(directory: str) -> None:
    """
    Checks the existence of a directory, if does not exist, create a new one
    :param directory: path to directory under concern
    :return: None
    """
    try:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logger.success(f'Create directory <{directory}>.')
    except OSError:
        logger.error(f'Create directory <{directory}>.')
        sys.exit()
    

def create_subdir(path: str, subdir_list: list) -> None:
    for subdir in subdir_list:
        subdir_path = os.path.join(path, subdir.strip('/'))
        if not os.path.exists(subdir_path):
            create_dir(subdir_path)

    
def read_yaml(file: str) -> OrderedDict:
    return yaml.load(open(file), Loader=SafeLoader)


def write_yaml(file: str, content: str) -> None:
    """
    if file exists at filepath, overwite the file, if not, create a new file
    :param filepath: string that specifies the destination file path
    :param content: yaml string that needs to be written to the destination file
    :return: None
    """
    if os.path.exists(file):
        os.remove(file)
    create_dir(os.path.dirname(file))
    out_file = open(file, 'a')
    out_file.write(yaml.dump( content, default_flow_style= False, Dumper=SafeDumper))


def check_repeated_key(full_dict: OrderedDict, key:str, val: OrderedDict) -> tuple:
    key_index = list(full_dict.keys()).index(key)
    key_list = list(full_dict.keys())[0 : key_index]
    for key in key_list:
        if full_dict[key] == val:
            return True, key
    return False, None
    

# the following interpolate_oneD_linear and interpolate_oneD_quadratic are adapted from accelergy
# ===============================================================
# useful helper functions that are commonly used in estimators
# ===============================================================
def interpolate_oneD_linear(desired_x, known):
    """
    utility function that performs 1D linear interpolation with a known energy value
    :param desired_x: integer value of the desired attribute/argument
    :param known: list of dictionary [{x: <value>, y: <energy>}]
    :return energy value with desired attribute/argument
    """
    # assume E = ax + c where x is a hardware attribute
    ordered_list = []
    if known[1]['x'] < known[0]['x']:
        ordered_list.append(known[1])
        ordered_list.append(known[0])
    else:
        ordered_list = known

    slope = (known[1]['y'] - known[0]['y']) / (known[1]['x'] - known[0]['x'])
    desired_energy = slope * (desired_x - ordered_list[0]['x']) + ordered_list[0]['y']
    return desired_energy


def interpolate_oneD_quadratic(desired_x, known):
    """
    utility function that performs 1D linear interpolation with a known energy value
    :param desired_x: integer value of the desired attribute/argument
    :param known: list of dictionary [{x: <value>, y: <energy>}]
    :return energy value with desired attribute/argument
    """
    # assume E = ax^2 + c where x is a hardware attribute
    ordered_list = []
    if known[1]['x'] < known[0]['x']:
        ordered_list.append(known[1])
        ordered_list.append(known[0])
    else:
        ordered_list = known

    slope = (known[1]['y'] - known[0]['y']) / (known[1]['x']**2 - known[0]['x']**2)
    desired_energy = slope * (desired_x**2 - ordered_list[0]['x']**2) + ordered_list[0]['y']
    return desired_energy


def get_input_tuple(input: Union[tuple, int], size: int=2) -> tuple:
    if isinstance(input, tuple):
        assert len(input) == size, logger.error(f'Invalid size <{str(len(input))}> != <{str(size)}>.')
        return input
    else:
        output = (input, ) * size
        return output


def get_path(path: str, check_exist: bool=True) -> str:
    path = os.path.abspath(path)
    path = os.path.realpath(path)
    if check_exist:
        assert os.path.exists(path), logger.error(f'Invalid path <{path}>')
    return path


def uniquify_list(sequence: list) -> list:
    seen = set()
    return [x for x in sequence if not (x in seen or seen.add(x))]


def get_dict(input_dict: OrderedDict) -> OrderedDict:
    return json.loads(json.dumps(input_dict))


def check_dict_in_list(input_dict: OrderedDict, input_list: list) -> OrderedDict:
    return get_dict(input_dict) in input_list


def check_dict_equal(input_dict0: OrderedDict, input_dict1: OrderedDict) -> bool:
    return get_dict(input_dict0) == get_dict(input_dict1)


def get_prod(input_array: np.ndarray) -> np.ndarray:
    return np.prod(np.array(input_array))

