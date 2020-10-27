# =============================================================================
# Minet CLI Utils
# =============================================================================
#
# Miscellaneous helpers used by the CLI tools.
#
import csv
import sys
import codecs
import yaml
from glob import iglob
from os.path import join, expanduser, isfile
from collections import namedtuple
from tqdm import tqdm


def print_err(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def die(msg):
    if not isinstance(msg, list):
        msg = [msg]

    for m in msg:
        print_err(m)

    sys.exit(1)


def safe_index(l, e):
    try:
        return l.index(e)
    except ValueError:
        return None


def custom_reader(f, target_header):

    reader = csv.reader(f)

    headers = next(reader, None)

    if headers[0].startswith(codecs.BOM_UTF8.decode()):
        headers[0] = headers[0][1:]

    if isinstance(target_header, tuple):
        HeaderPositions = namedtuple('HeaderPositions', target_header)
        position = HeaderPositions(**{t: safe_index(headers, t) for t in target_header})
    else:
        position = safe_index(headers, target_header)

    return headers, position, reader


class DummyTqdmFile(object):
    """
    Dummy file-like that will write to tqdm. Taken straight from the lib's
    documentation: https://github.com/tqdm/tqdm but modified for minet use
    case regarding stdout piping.
    """
    file = None

    def __init__(self, file=sys.stdout):
        self.file = file
        self.cursor = 0

    def write(self, x):
        self.cursor += 1
        # Avoid print() second call (useless \n)
        tqdm.write(x, file=self.file, end='')

    def flush(self):
        return self.file.flush()

    def tell(self):
        return self.cursor

    def close(self):
        pass


def open_output_file(output, flag='w'):
    if output is None:
        return DummyTqdmFile(sys.stdout)

    return open(output, flag)


WorkerPayload = namedtuple(
    'WorkerPayload',
    ['line', 'headers', 'path', 'encoding', 'content', 'args']
)


def create_report_iterator(namespace, args=None, loading_bar=None):
    input_headers, pos, reader = custom_reader(namespace.report, ('status', 'filename', 'encoding', 'raw_content'))

    indexed_headers = {h: p for p, h in enumerate(input_headers)}

    for line in reader:
        status = int(line[pos.status]) if line[pos.status] else None
        filename = line[pos.filename]

        if status is None or status >= 400 or not filename:
            if loading_bar is not None:
                loading_bar.update()
            continue

        if pos.raw_content is not None:
            yield WorkerPayload(
                line=line,
                headers=indexed_headers,
                path=None,
                encoding=line[pos.encoding],
                content=line[pos.raw_content],
                args=args
            )

            continue

        path = join(namespace.input_directory, filename)
        encoding = line[pos.encoding].strip() or 'utf-8'

        yield WorkerPayload(
            line=line,
            headers=indexed_headers,
            path=path,
            encoding=encoding,
            content=None,
            args=args
        )


def create_glob_iterator(namespace, args):
    for p in iglob(namespace.glob, recursive=True):
        yield WorkerPayload(
            line=None,
            headers=None,
            path=p,
            encoding='utf-8',
            content=None,
            args=args
        )


class LazyLineDict(object):
    def __init__(self, headers, line):
        self.headers = headers
        self.line = line

    def __getitem__(self, key):
        return self.line[self.headers[key]]


class LoadingBarContext(object):
    __slots__ = ('loading_bar',)

    def __init__(self, loading_bar):
        self.loading_bar = loading_bar

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.loading_bar.update()


def get_rcfile(rcfile_path=None):
    home = expanduser('~')

    files = [
        rcfile_path,
        '.minetrc',
        '.minetrc.yml',
        '.minetrc.yaml',
        '.minetrc.json',
        join(home, '.minetrc'),
        join(home, '.minetrc.yml'),
        join(home, '.minetrc.yaml'),
        join(home, '.minetrc.json')
    ]

    for p in files:
        if p is None or not isfile(p):
            continue

        with open(p) as f:
            return yaml.load(f, Loader=yaml.Loader)

    return None
