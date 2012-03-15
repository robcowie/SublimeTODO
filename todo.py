# -*- coding: utf-8 -*-

## TODO: Implement TODO_IGNORE setting (http://mdeering.com/posts/004-get-your-textmate-todos-and-fixmes-under-control)
## TODO: Make the output clickable (å la find results)
## TODO: Occasional NoneType bug
## todo: Make the sections foldable (define them as regions?)

""""""

from collections import namedtuple
from datetime import datetime
import functools
import fnmatch
from itertools import groupby
import logging
from os import path, walk
import re
import threading

import sublime
import sublime_plugin


DEBUG = False

DEFAULT_SETTINGS = {
    'result_title': 'TODO Results',

    'core_patterns': {
        'TODO': r'TODO[\s]*?:+(?P<todo>.*)$',
        'NOTE': r'NOTE[\s]*?:+(?P<note>.*)$',
        'FIXME': r'FIX ?ME[\s]*?:+(?P<fixme>.*)$',
        'CHANGED': r'CHANGED[\s]*?:+(?P<changed>.*)$'
    },

    'patterns': {}
}

Message = namedtuple('Message', 'type, msg')

## LOGGING SETUP
try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def handle(self, record):
            pass

        def emit(self, record):
            pass

        def createLock(self):
            self.lock = None

log = logging.getLogger('SublimeTODO')
log.handlers = [] ## hack to prevent extraneous handlers on ST2 auto-reload
log.addHandler(NullHandler())
log.setLevel(logging.INFO)
if DEBUG:
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.DEBUG)


def do_when(conditional, callback, *args, **kwargs):
    if conditional():
        return callback(*args, **kwargs)
    sublime.set_timeout(functools.partial(do_when, conditional, callback, *args, **kwargs), 50)


class Settings(dict):
    """Combine default and user settings"""
    def __init__(self, user_settings):
        settings = DEFAULT_SETTINGS.copy()
        settings.update(user_settings)
        ## Combine core_patterns and patterns
        settings['core_patterns'].update(settings['patterns'])
        settings['patterns'] = settings.pop('core_patterns')
        super(Settings, self).__init__(settings)


class ThreadProgress(object):
    def __init__(self, thread, message, success_message, file_counter):
        self.thread = thread
        self.message = message
        self.success_message = success_message
        self.file_counter = file_counter
        self.addend = 1
        self.size = 8
        sublime.set_timeout(lambda: self.run(0), 100)

    def run(self, i):
        if not self.thread.is_alive():
            if hasattr(self.thread, 'result') and not self.thread.result:
                sublime.status_message('')
                return
            sublime.status_message(self.success_message)
            return

        before = i % self.size
        after = (self.size - 1) - before
        sublime.status_message('%s [%s=%s] (%s files scanned)' % \
            (self.message, ' ' * before, ' ' * after, self.file_counter))
        if not after:
            self.addend = -1
        if not before:
            self.addend = 1
        i += self.addend
        sublime.set_timeout(lambda: self.run(i), 100)



class TodoExtractor(object):
    def __init__(self, settings, filepaths, dirpaths, ignored_dirs, ignored_file_patterns, 
                 file_counter):
        self.filepaths = filepaths
        self.dirpaths = dirpaths
        self.patterns = settings['patterns']
        self.settings = settings
        self.file_counter = file_counter
        self.ignored_dirs = ignored_dirs
        self.ignored_files = ignored_file_patterns
        self.log = logging.getLogger('SublimeTODO.extractor')

    def iter_files(self):
        """"""
        seen_paths_ = []
        files = self.filepaths
        dirs = self.dirpaths
        exclude_dirs = self.ignored_dirs

        for filepath in files:
            pth = path.realpath(path.abspath(filepath))
            if pth not in seen_paths_:
                seen_paths_.append(pth)
                yield pth

        for dirpath in dirs:
            dirpath = path.abspath(dirpath)
            for dirpath, dirnames, filenames in walk(dirpath):
                ## remove excluded dirs
                for dir in [dir for dir in exclude_dirs if dir in dirnames]:
                    self.log.debug('Ignoring dir: {0}'.format(dir))
                    dirnames.remove(dir)

                for filepath in filenames:
                    pth = path.join(dirpath, filepath)
                    pth = path.realpath(path.abspath(pth))
                    if pth not in seen_paths_:
                        seen_paths_.append(pth)
                        yield pth

    def filter_files(self, files):
        """"""
        exclude_patterns = [re.compile(patt) for patt in self.ignored_files]
        for filepath in files:
            if any(patt.match(filepath) for patt in exclude_patterns):
                continue
            yield filepath

    def search_targets(self):
        """Yield filtered filepaths for message extraction"""
        return self.filter_files(self.iter_files())

    def extract(self):
        """"""
        message_patterns = '|'.join(self.patterns.values())
        patt = re.compile(message_patterns, re.IGNORECASE)
        for filepath in self.search_targets():
            try:
                f = open(filepath)
                self.log.debug('Scanning {0}'.format(filepath))
                for linenum, line in enumerate(f):
                    for mo in patt.finditer(line):
                        ## Remove the non-matched groups
                        matches = [Message(msg_type, msg) for msg_type, msg in mo.groupdict().iteritems() if msg]
                        for match in matches:
                            yield {'filepath': filepath, 'linenum': linenum + 1, 'match': match}
            except IOError:
                ## Probably a broken symlink
                pass
            finally:
                self.file_counter.increment()
                f.close()


class TodoRenderer(object):
    def __init__(self, settings, window, file_counter):
        self.window = window
        self.settings = settings
        self.file_counter = file_counter

    @property
    def view_name(self):
        """The name of the new results view. Defined in settings."""
        return self.settings['result_title']

    @property
    def header(self):
        hr = u'+ {0} +'.format('-' * 76)
        return u'{hr}\n| TODOS @ {0:<68} |\n| {1:<76} |\n{hr}\n'.format(
            datetime.utcnow().strftime('%A %d %B %Y %H:%M'),
            u'{0} files scanned'.format(self.file_counter),
            hr=hr)

    @property
    def view(self):
        existing_results = [v for v in self.window.views() 
                            if v.name() == self.view_name and v.is_scratch()]
        if existing_results:
            v = existing_results[0]
        else:
            v = self.window.new_file()
            v.set_name(self.view_name)
            v.set_scratch(True)
            v.settings().set('todo_results', True)
        return v

    def format(self, messages):
        """Yield lines for rendering into results view. Includes headers and 
        blank lines.
        Lines are returned in the form (type, content, [data]) where type is either 
        'header', 'whitespace' or 'result'
        """
        key_func = lambda m: m['match'].type
        messages = sorted(messages, key=key_func)

        for message_type, matches in groupby(messages, key=key_func):
            matches = list(matches)
            if matches:
                yield ('header', u'\n## {0} ({1})'.format(message_type.upper().decode('utf8', 'ignore'), len(matches)), {})
                for idx, m in enumerate(matches, 1):
                    msg = m['match'].msg.decode('utf8', 'ignore') ## Don't know the file encoding
                    filepath = path.basename(m['filepath'])
                    line = u"{idx}. {filepath}:{linenum} {msg}".format(
                        idx=idx, filepath=filepath, linenum=m['linenum'], msg=msg)
                    yield ('result', line, m)

    def render_to_view(self, formatted_results):
        """This blocks the main thread, so make it quick"""
        ## Header
        result_view = self.view
        edit = result_view.begin_edit()
        result_view.erase(edit, sublime.Region(0, result_view.size()))
        result_view.insert(edit, result_view.size(), self.header)
        result_view.end_edit(edit)

        ## Region : match_dicts
        regions = {}

        ## Result sections
        for linetype, line, data in formatted_results:
            edit = result_view.begin_edit()
            insert_point = result_view.size()
            result_view.insert(edit, insert_point, line)
            if linetype == 'result':
                rgn = sublime.Region(insert_point, result_view.size())
                regions[rgn] = data
            result_view.insert(edit, result_view.size(), u'\n')
            result_view.end_edit(edit)

        result_view.add_regions('results', regions.keys(), '')

        ## Store {Region : data} map in settings
        ## TODO: Abstract this out to a storage class Storage.get(region) ==> data dict
        ## Region() cannot be stored in settings, so convert to a primitive type
        # d_ = regions
        d_ = dict(('{0},{1}'.format(k.a, k.b), v) for k, v in regions.iteritems())
        result_view.settings().set('result_regions', d_)

        ## Set syntax and settings
        result_view.set_syntax_file('Packages/SublimeTODO/todo_results.hidden-tmLanguage')
        result_view.settings().set('line_padding_bottom', 2)
        result_view.settings().set('line_padding_top', 2)
        result_view.settings().set('word_wrap', False)
        result_view.settings().set('command_mode', True)
        self.window.focus_view(result_view)


class WorkerThread(threading.Thread):
    def __init__(self, extractor, renderer):
        self.extractor = extractor
        self.renderer = renderer
        threading.Thread.__init__(self)

    def run(self):
        ## Extract in this thread
        todos = self.extractor.extract()
        rendered = list(self.renderer.format(todos))

        ## Render into new window in main thread
        def render():
            self.renderer.render_to_view(rendered)
        sublime.set_timeout(render, 10)


class FileScanCounter(object):
    """Thread-safe counter used to update the status bar"""
    def __init__(self):
        self.ct = 0
        self.lock = threading.RLock()
        self.log = logging.getLogger('SublimeTODO')

    def __call__(self, filepath):
        self.log.debug('Scanning %s' % filepath)
        self.increment()

    def __str__(self):
        with self.lock:
            return '%d' % self.ct

    def increment(self):
        with self.lock:
            self.ct += 1

    def reset(self):
        with self.lock:
            self.ct = 0


class TodoCommand(sublime_plugin.TextCommand):

    def search_paths(self, window):
        """Return (filepaths, dirpaths)"""
        return (
            [view.file_name() for view in window.views() if view.file_name()], 
            window.folders()
        )

    def run(self, edit):
        window = self.view.window()
        settings = Settings(self.view.settings().get('todo', {}))


        ## TODO: Cleanup this init code. Maybe move it to the settings object
        filepaths, dirpaths = self.search_paths(window)

        ignored_dirs = settings.get('folder_exclude_patterns', [])
        ## Get exclude patterns from global settings
        ## Is there really no better way to access global settings?
        global_settings = sublime.load_settings('Global.sublime-settings')
        ignored_dirs.extend(global_settings.get('folder_exclude_patterns', []))

        exclude_file_patterns = settings.get('file_exclude_patterns', [])
        exclude_file_patterns.extend(global_settings.get('file_exclude_patterns', []))
        exclude_file_patterns.extend(global_settings.get('binary_file_patterns', []))
        exclude_file_patterns = [fnmatch.translate(patt) for patt in exclude_file_patterns]

        file_counter = FileScanCounter()
        extractor = TodoExtractor(settings, filepaths, dirpaths, ignored_dirs, 
                                  exclude_file_patterns, file_counter)
        renderer = TodoRenderer(settings, window, file_counter)

        worker_thread = WorkerThread(extractor, renderer)
        worker_thread.start()
        ThreadProgress(worker_thread, 'Finding TODOs', '', file_counter)


class NavigateResults(sublime_plugin.TextCommand):
    DIRECTION = {'forward': 1, 'backward': -1}
    STARTING_POINT = {'forward': -1, 'backward': 0}

    def __init__(self, view):
        super(NavigateResults, self).__init__(view)

    def run(self, edit, direction):
        view = self.view
        settings = view.settings()
        results = self.view.get_regions('results')
        if not results:
            sublime.status_message('No results to navigate')
            return

        ##NOTE: numbers stored in settings are coerced to floats or longs
        selection = int(settings.get('selected_result', self.STARTING_POINT[direction]))
        selection = selection + self.DIRECTION[direction]
        try:
            target = results[selection]
        except IndexError:
            target = results[0]
            selection = 0

        settings.set('selected_result', selection)
        ## Create a new region for highlighting
        target = target.cover(target)
        view.add_regions('selection', [target], 'selected', 'dot')
        view.show(target)


class ClearSelection(sublime_plugin.TextCommand):
    def run(self, edit):
        self.view.erase_regions('selection')
        self.view.settings().erase('selected_result')


class GotoComment(sublime_plugin.TextCommand):
    def __init__(self, *args):
        self.log = logging.getLogger('SublimeTODO.nav')
        super(GotoComment, self).__init__(*args)

    def run(self, edit):
        ## Get the idx of selected result region
        selection = int(self.view.settings().get('selected_result', -1))
        ## Get the region
        selected_region = self.view.get_regions('results')[selection]
        ## Convert region to key used in result_regions (this is tedious, but 
        ##    there is no other way to store regions with associated data)
        data = self.view.settings().get('result_regions')['{0},{1}'.format(selected_region.a, selected_region.b)]
        self.log.debug('Goto comment at {filepath}:{linenum}'.format(**data))
        new_view = self.view.window().open_file(data['filepath'])
        do_when(lambda: not new_view.is_loading(), lambda: new_view.run_command("goto_line", {"line": data['linenum']}))


class MouseGotoComment(sublime_plugin.TextCommand):
    def __init__(self, *args):
        self.log = logging.getLogger('SublimeTODO.nav')
        super(MouseGotoComment, self).__init__(*args)

    def highlight(self, region):
        target = region.cover(region)
        self.view.add_regions('selection', [target], 'selected', 'dot')
        self.view.show(target)

    def get_result_region(self, pos):
        line = self.view.line(pos)
        return line

    def run(self, edit):
        if not self.view.settings().get('result_regions'):
            return
        ## get selected line
        pos = self.view.sel()[0].end()
        result = self.get_result_region(pos)
        self.highlight(result)
        data = self.view.settings().get('result_regions')['{0},{1}'.format(result.a, result.b)]
        self.log.debug('Goto comment at {filepath}:{linenum}'.format(**data))
        new_view = self.view.window().open_file(data['filepath'])
        do_when(lambda: not new_view.is_loading(), lambda: new_view.run_command("goto_line", {"line": data['linenum']}))
