# -*- coding: utf-8 -*-

## TODO: Implement TODO_IGNORE setting (pass to pss ignore) (http://mdeering.com/posts/004-get-your-textmate-todos-and-fixmes-under-control)
## TODO: Create a custom (hidden) langage for the output
## TODO: Make the output clickable (a la find results)
## TODO: Occasional NoneType bug
## TODO: Make the sections foldable (define them as regions?)
## TODO: Add progress indicator (see Package Control source)


from datetime import datetime
import threading
import sublime
import sublime_plugin


from psslib.driver import pss_run as pss
from results_formatter import ResultsOutputFormatter


PATTERNS = {
    'TODO': 'TODO[\s,:]+(.*)$',
    'FIXME': 'FIX ?ME[\s,:]+(\S.*)$',
    'CHANGED': 'CHANGED[\s,:]+(\S.*)$',
    'RADAR': '(.*<)ra?dar:\/(?:\/problem|)\/([&0-9]+)(>.*)$'
}


class TodoFinder(threading.Thread):
    def __init__(self, window):
        self.window = window
        threading.Thread.__init__(self)

    def run(self):
        sublime.set_timeout(self.extract, 100)

    def search_paths(self):
        search_paths = []
        search_paths.extend(self.window.folders() or [])
        search_paths.extend([view.file_name() for view in self.window.views() 
                             if view.file_name()])
        return search_paths

    def extract(self):
        """Find notes matching patterns, pass through custom pss formatter, 
        which writes to a new view
        """
        search_paths = self.search_paths()

        all_results = {}
        for label, pattern in PATTERNS.iteritems():
            results = []
            renderer = ResultsOutputFormatter(results, label, pattern)
            pss(search_paths, pattern=pattern, ignore_case=True, 
                search_all_types=True, output_formatter=renderer)
            if results:
                all_results[label] = results

        self.render(all_results)

    def render(self, all_results):
        ## Header
        result_view = self.window.new_file()
        edit_ = result_view.begin_edit()
        result_view.insert(edit_, result_view.size(), '# TODO LIST (%s)\n\n' % datetime.utcnow().strftime('%Y-%m-%d %H:%M'))
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


class TodoCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.window = self.view.window()
        worker_thread = TodoFinder(self.window)

        ## worker starter callback
        def starter():
            worker_thread.start()

        sublime.set_timeout(starter, 10)
