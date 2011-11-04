# -*- coding: utf-8 -*-

## TODO: Implement TODO_IGNORE setting (pass to pss ignore) (http://mdeering.com/posts/004-get-your-textmate-todos-and-fixmes-under-control)
## TODO: Create a custom (hidden) langage for the output
## TODO: Make the output clickable (a la find results)
## TODO: Occasional NoneType bug
## TODO: Make the sections foldable (define them as regions?)


from datetime import datetime
from os import path
import sublime_plugin


## Find pss on import, not on each .run()
PSS = path.join(path.dirname(path.abspath(__file__)), 'psslib', 'pss.py')
# from psslib import pss
from psslib.driver import pss_run as pss
from markdown_pss_formatter import MarkdownOutputFormatter


PATTERNS = {
    'TODO': 'TODO[\s,:]+(.*)$',
    'FIXME': 'FIX ?ME[\s,:]+(\S.*)$',
    'CHANGED': 'CHANGED[\s,:]+(\S.*)$',
    'RADAR': '(.*<)ra?dar:\/(?:\/problem|)\/([&0-9]+)(>.*)$'
}


class TodoCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.window = self.view.window()
        new_view = self.window.new_file()
        self.extract_and_render(new_view)

    def search_paths(self):
        search_paths = []
        search_paths.extend(self.window.folders() or [])
        return search_paths

    def extract_and_render(self, result_view):
        """Find notes matching patterns, pass through custom pss formatter, 
        which writes to a new view
        """
        search_paths = self.search_paths()
        ## TODO: Search open files as well as project folders
        # search_paths.extend([path.dirname(view.file_name()) for view in self.view.window().views()])
        # search_paths.extend([view.file_name() for view in self.view.window().views()])
        edit_ = result_view.begin_edit()
        result_view.insert(edit_, result_view.size(), '# TODO LIST (%s)\n\n' % datetime.utcnow().strftime('%Y-%m-%d %H:%M'))
        result_view.end_edit(edit_)

        for label, pattern in PATTERNS.iteritems():
            results = []
            renderer = MarkdownOutputFormatter(results, label, pattern)
            pss(search_paths, pattern=pattern, ignore_case=True, output_formatter=renderer)

            if results:
                edit_ = result_view.begin_edit()
                result_view.insert(edit_, result_view.size(), '## %s\n' % label)
                for result in results:
                    result_view.insert(edit_, result_view.size(), '%s\n' % result)
                result_view.insert(edit_, result_view.size(), '\n')
                result_view.end_edit(edit_)

        result_view.set_syntax_file('Packages/YAML/YAML.tmLanguage')
