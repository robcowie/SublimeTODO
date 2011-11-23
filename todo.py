# -*- coding: utf-8 -*-

## TODO: Implement TODO_IGNORE setting (pass to pss ignore) (http://mdeering.com/posts/004-get-your-textmate-todos-and-fixmes-under-control)
## TODO: Make the output clickable (a la find results)
## TODO: Occasional NoneType bug
## TODO: Make the sections foldable (define them as regions?)

from datetime import datetime
import logging
import threading
import sublime
import sublime_plugin

from psslib.driver import pss_run as pss
from results_formatter import ResultsOutputFormatter


DEBUG = False
PATTERNS = {
    'TODO': r'TODO[\s,:]+(.*)$',
    'FIXME': r'FIX ?ME[\s,:]+(\S.*)$',
    'CHANGED': r'CHANGED[\s,:]+(\S.*)$',
    'RADAR': r'ra?dar:/(?:/problem|)/([&0-9]+)$'
}


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
    def __init__(self, patterns, search_paths, file_counter):
        self.search_paths = search_paths
        self.patterns = patterns
        self.file_counter = file_counter
        self.log = logging.getLogger('SublimeTODO.extractor')

    def extract(self):
        """Find notes matching patterns, pass through custom pss formatter, 
        which writes to a new view
        """
        search_paths = self.search_paths
        all_results = {}
        for label, pattern in self.patterns.iteritems():
            self.log.debug('Extracting for %s' % label)
            self.file_counter.reset()
            results = []
            renderer = ResultsOutputFormatter(results, label, pattern)
            pss(search_paths, pattern=pattern, ignore_case=True, 
                search_all_types=True, textonly=True,
                output_formatter=renderer, file_hook=self.file_counter)
            if results:
                all_results[label] = results

        return all_results


class TodoRenderer(object):
    def __init__(self, window, file_counter):
        self.window = window
        self.file_counter = file_counter

    def header(self, all_results):
        return "# TODO LIST (%s) \n## %s files scanned \n\n" % (
            datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
            self.file_counter
        )

    def render(self, all_results):
        """This blocks the main thread, so make it quick"""
        ## Header
        result_view = self.window.new_file()
        edit_ = result_view.begin_edit()
        result_view.insert(edit_, result_view.size(), self.header(all_results))
        result_view.end_edit(edit_)

        ## Result sections
        for label, results in all_results.iteritems():
            edit_ = result_view.begin_edit()
            result_view.insert(edit_, result_view.size(), '## %s\n\n' % label)
            for result in results:
                result_view.insert(edit_, result_view.size(), '%s\n' % result)
            result_view.insert(edit_, result_view.size(), '\n')
            result_view.end_edit(edit_)

        ## Set syntax and settings
        result_view.set_syntax_file('Packages/SublimeTODO/todo_results.hidden-tmLanguage')
        result_view.settings().set('line_padding_bottom', 2)
        result_view.settings().set('line_padding_top', 2)
        result_view.settings().set('word_wrap', False)


class WorkerThread(threading.Thread):
    def __init__(self, extractor, renderer):
        self.extractor = extractor
        self.renderer = renderer
        threading.Thread.__init__(self)

    def run(self):
        ## Extract in this thread
        todos = self.extractor.extract()

        ## Render into new window in main thread
        def render():
            self.renderer.render(todos)
        sublime.set_timeout(render, 10)


class FileScanCounter(object):
    """Thread-safe counter used to update the status bar
    Passed to the modified driver.pss_run(file_hook) and called (incremented) 
    for every scanned file"""
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
        search_paths = []
        search_paths.extend(window.folders() or [])
        search_paths.extend([view.file_name() for view in window.views() 
                             if view.file_name()])
        return search_paths

    def run(self, edit):
        window = self.view.window()
        search_paths = self.search_paths(window)
        patterns = PATTERNS
        patterns.update(self.view.settings().get('todo_patterns', {}))

        file_counter = FileScanCounter()
        extractor = TodoExtractor(patterns, search_paths, file_counter)
        renderer = TodoRenderer(window, file_counter)

        worker_thread = WorkerThread(extractor, renderer)
        worker_thread.start()
        ThreadProgress(worker_thread, 'Finding TODOs', '', file_counter)
