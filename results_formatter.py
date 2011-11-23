# -*- coding: utf-8 -*-


import itertools
from os import path
import re
from psslib.outputformatter import OutputFormatter


class ResultsOutputFormatter(OutputFormatter):
    """A simple pss OutputFormatter that formats search results and appends to 
    self.results
    """
    def __init__(self, results, header, pattern, **kargs):
        OutputFormatter.__init__(self, **kargs)
        self.header = header
        self.pattern = pattern
        self.results = results
        self.counter = itertools.count(1)

    def start_matches_in_file(self, filename):
        """ Called when a sequences of matches from some file is about to be
            output. filename is the name of the file in which the matches were
            found.
        """
        pass

    def end_matches_in_file(self, filename):
        """ Called when the matches for a file have finished.
        """
        pass

    def binary_file_matches(self, msg):
        """Ignore binary files with matches"""
        pass

    def matching_line(self, match, filepath):
        """ Called to emit a matching line, with a matchresult.MatchResult 
            object.
        """
        idx = self.counter.next()
        line = match.matching_line
        index_str = '%d.' % idx
        try:
            output = '%s %s (%d): %s' % (index_str.rjust(4), path.basename(filepath), 
                match.matching_lineno, 
                self._process_matched_line(line)
            )
            self.results.append(output)
        except AttributeError:
            pass

    def _process_matched_line(self, line):
        """Don't want to show the entire matched line, just a portion of it.
        pss doesn't handle regexp groups, so we can't define groups in the 
        pattern. Horribly inefficient as it searches the line a second time
        """
        return re.search(self.pattern, line.strip()).groups()[0]

    def context_line(self, line, lineno):
        """ Called to emit a context line.
        """
        pass

    def context_separator(self):
        """ Called to emit a "context separator" - line between non-adjacent 
            context lines.
        """
        pass

    def found_filename(self, filename):
        """ Called to emit a found filename when pss runs in file finding mode
            instead of line finding mode (emitting only the found files and not
            matching their contents).
        """
        raise NotImplementedError()
