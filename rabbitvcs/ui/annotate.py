from __future__ import absolute_import
#
# This is an extension to the Nautilus file manager to allow better
# integration with the Subversion source control system.
#
# Copyright (C) 2006-2008 by Jason Field <jason@jasonfield.com>
# Copyright (C) 2007-2008 by Bruce van der Kooij <brucevdkooij@gmail.com>
# Copyright (C) 2008-2010 by Adam Plumb <adamplumb@gmail.com>
#
# RabbitVCS is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# RabbitVCS is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with RabbitVCS;  If not, see <http://www.gnu.org/licenses/>.
#

import os
from datetime import datetime
import time

from rabbitvcs.util import helper

from gi import require_version
require_version("Gtk", "3.0")
sa = helper.SanitizeArgv()
from gi.repository import Gtk, GObject, Gdk, GLib
sa.restore()

from rabbitvcs.ui import InterfaceView
from rabbitvcs.ui.log import log_dialog_factory
from rabbitvcs.ui.action import SVNAction, GitAction
import rabbitvcs.ui.widget
from rabbitvcs.ui.dialog import MessageBox, Loading
from rabbitvcs.util.strings import S
from rabbitvcs.util.decorators import gtk_unsafe
from rabbitvcs.util.highlighter import highlight
import rabbitvcs.util.settings
import rabbitvcs.vcs

from rabbitvcs import gettext
_ = gettext.gettext

class Annotate(InterfaceView):
    """
    Provides a UI interface to annotate items in the repository or
    working copy.

    Pass a single path to the class when initializing

    """

    def __init__(self, path, revision=None):
        if os.path.isdir(path):
            MessageBox(_("Cannot annotate a directory"))
            raise SystemExit()
            return

        InterfaceView.__init__(self, "annotate", "Annotate")

        self.get_widget("Annotate").set_title(_("Annotate - %s") % path)
        self.vcs = rabbitvcs.vcs.VCS()

        sm = rabbitvcs.util.settings.SettingsManager()
        self.datetime_format = sm.get("general", "datetime_format")

    def on_close_clicked(self, widget):
        self.close()

    def on_save_clicked(self, widget):
        self.save()

    def on_refresh_clicked(self, widget):
        self.load()

    def on_from_show_log_clicked(self, widget, data=None):
        log_dialog_factory(self.path, ok_callback=self.on_from_log_closed)

    def on_from_log_closed(self, data):
        if data is not None:
            self.get_widget("from").set_text(S(data).display())

    def on_to_show_log_clicked(self, widget, data=None):
        log_dialog_factory(self.path, ok_callback=self.on_to_log_closed)

    def on_to_log_closed(self, data):
        if data is not None:
            self.get_widget("to").set_text(S(data).display())

    def enable_saveas(self):
        self.get_widget("save").set_sensitive(True)

    def disable_saveas(self):
        self.get_widget("save").set_sensitive(False)

    def save(self, path=None):
        if path is None:
            from rabbitvcs.ui.dialog import FileSaveAs
            dialog = FileSaveAs()
            path = dialog.run()

        if path is not None:
            fh = open(path, "w")
            fh.write(self.generate_string_from_result())
            fh.close()

    def launch_loading(self):
        self.loading_dialog = Loading()
        GLib.idle_add(self.loading_dialog.run)

    def kill_loading(self):
        GLib.idle_add(self.loading_dialog.destroy)

class SVNAnnotate(Annotate):
    def __init__(self, path, revision=None):
        Annotate.__init__(self, path, revision)

        self.svn = self.vcs.svn()

        if revision is None:
            revision = "HEAD"

        self.path = path
        self.get_widget("from").set_text("1")
        self.get_widget("to").set_text(S(revision).display())

        self.table = rabbitvcs.ui.widget.Table(
            self.get_widget("table"),
            [GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_STRING,
                GObject.TYPE_STRING, rabbitvcs.ui.widget.TYPE_MARKUP],
            [_("Line"), _("Revision"), _("Author"),
                _("Date"), _("Text")]
        )
        self.table.allow_multiple()

        self.loading_dialog = None

        self.load()

    #
    # Helper methods
    #

    def load(self):
        from_rev_num = self.get_widget("from").get_text().lower()
        to_rev_num = self.get_widget("to").get_text().lower()

        if not from_rev_num.isdigit():
            MessageBox(_("The from revision field must be an integer"))
            return

        from_rev = self.svn.revision("number", number=int(from_rev_num))

        to_rev = self.svn.revision("head")
        if to_rev_num.isdigit():
            to_rev = self.svn.revision("number", number=int(to_rev_num))

        self.launch_loading()

        self.action = SVNAction(
            self.svn,
            notification=False
        )

        self.action.append(
            self.svn.annotate,
            self.path,
            from_rev,
            to_rev
        )
        self.action.append(self.populate_table)
        self.action.append(self.enable_saveas)
        self.action.schedule()

        self.kill_loading()

    def blame_info(self, item):
        revision = item["revision"].number
        if revision <= 0:
            return ("", "", "")

        revision = str(revision)

        # remove fractional seconds and timezone information from
        # the end of the string provided by pysvn:
        # * timezone should be always "Z" (for UTC), "%Z" is not yet
        #   yet supported by strptime
        # * fractional could be parsed with "%f" since python 2.6
        #   but this precision is not needed anyway
        # * the datetime module does not include strptime until python 2.4
        #   so this workaround is required for now
        datestr = item["date"][0:-8]
        try:
            date = datetime(*time.strptime(datestr,"%Y-%m-%dT%H:%M:%S")[:-2])
            date = helper.format_datetime(date, self.datetime_format)
        except:
            date = ""
 
        return revision, date, item["author"]

    def populate_table(self):
        blamedict = self.action.get_result(0)
        lines = highlight(self.path, [item["line"] for item in blamedict])

        self.table.clear()
        for i, item in enumerate(blamedict):
            revision, date, author = self.blame_info(item)
            self.table.append([
                str(int(item["number"]) + 1),
                revision,
                author,
                date,
                lines[i]
            ])

    def generate_string_from_result(self):
        blamedict = self.action.get_result(0)

        text = ""
        for item in blamedict:
            revision, date, author = self.blame_info(item)

            text += "%s\t%s\t%s\t%s\t%s\n" % (
                str(int(item["number"]) + 1),
                revision,
                author,
                date,
                item["line"]
            )

        return text

class GitAnnotate(Annotate):
    def __init__(self, path, revision=None):
        Annotate.__init__(self, path, revision)

        self.git = self.vcs.git(path)

        if revision is None:
            revision = "HEAD"

        self.path = path
        self.get_widget("to").set_text(S(revision).display())

        self.table = rabbitvcs.ui.widget.Table(
            self.get_widget("table"),
            [GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_STRING,
                GObject.TYPE_STRING, rabbitvcs.ui.widget.TYPE_MARKUP],
            [_("Line"), _("Revision"), _("Author"),
                _("Date"), _("Text")]
        )
        self.table.allow_multiple()

        self.load()

    #
    # Helper methods
    #

    def launch_loading(self):
        self.loading_dialog = Loading()
        GLib.idle_add(self.loading_dialog.run)

    def kill_loading(self):
        GLib.idle_add(self.loading_dialog.destroy)

    def load(self):
        to_rev = self.git.revision(self.get_widget("to").get_text())

        self.launch_loading()

        self.action = GitAction(
            self.git,
            notification=False
        )

        self.action.append(
            self.git.annotate,
            self.path,
            to_rev
        )
        self.action.append(self.populate_table)
        self.action.append(self.enable_saveas)
        self.action.schedule()
        self.kill_loading()

    def populate_table(self):
        blamedict = self.action.get_result(0)
        lines = highlight(self.path, [item["line"] for item in blamedict])

        self.table.clear()
        for i, item in enumerate(blamedict):
            self.table.append([
                str(item["number"]),
                item["revision"][:7],
                item["author"],
                helper.format_datetime(item["date"], self.datetime_format),
                lines[i]
            ])

    def generate_string_from_result(self):
        blamedict = self.action.get_result(0)

        text = ""
        for item in blamedict:
            text += "%s\t%s\t%s\t%s\t%s\n" % (
                str(item["number"]),
                item["revision"][:7],
                item["author"],
                helper.format_datetime(item["date"], self.datetime_format),
                item["line"]
            )

        return text

classes_map = {
    rabbitvcs.vcs.VCS_SVN: SVNAnnotate,
    rabbitvcs.vcs.VCS_GIT: GitAnnotate
}

def annotate_factory(vcs, path, revision=None):
    if not vcs:
        guess = rabbitvcs.vcs.guess(path)
        vcs = guess["vcs"]

    return classes_map[vcs](path, revision)


if __name__ == "__main__":
    from rabbitvcs.ui import main, REVISION_OPT, VCS_OPT
    (options, paths) = main(
        [REVISION_OPT, VCS_OPT],
        usage="Usage: rabbitvcs annotate url [-r REVISION]"
    )

    window = annotate_factory(options.vcs, paths[0], options.revision)
    window.register_gtk_quit()
    Gtk.main()
