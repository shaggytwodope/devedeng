#!/usr/bin/env python3

# Copyright 2014 (C) Raster Software Vigo (Sergio Costas)
#
# This file is part of DeVeDe-NG
#
# DeVeDe-NG is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# DeVeDe-NG is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>

from gi.repository import GLib, GObject
import subprocess
import os
import signal
import devedeng.configuration_data


class executor(GObject.GObject):
    """ This class encapsulates everything needed for launching processes """

    __gsignals__ = {'ended': (GObject.SIGNAL_RUN_FIRST, None, (int, ))}

    def __init__(self):

        GObject.GObject.__init__(self)

        self.config = devedeng.configuration_data.configuration.get_config()
        self.channel_stdin = None
        self.channel_stdout = None
        self.channel_stderr = None
        self.text = ""
        self.stdout_data = ""
        self.stderr_data = ""
        self.stdin_file = None
        self.stdout_file = None

        self.dependencies = None
        self.childs = []
        self.progress_bar = None
        self.killed = False
        self.pulse_mode = False
        self.use_pulse_mode = False
        self.pulse_text = None
        self.handle = None

    def add_dependency(self, dep):

        self.add_dependency2(dep)

        for child in dep.childs:
            self.add_dependency2(child)

    def add_dependency2(self, dep):

        if (self.dependencies is None):
            self.dependencies = []

        if (self.dependencies.count(dep) == 0):
            self.dependencies.append(dep)

        # the childs have the same dependencies than the parent process because, from outside, it is viewed as a single process
        for child in self.childs:
            child.add_dependency(dep)

    def remove_dependency(self, process):
        # dependencies are removed only in the parent because the running class have all the processes, parents and childs, and calls
        # this method on all of them
        if (self.dependencies is not None):
            tmp2 = []
            for dep in self.dependencies:
                if dep != process:
                    tmp2.append(dep)
            if (len(tmp2) != 0):
                self.dependencies = tmp2
            else:
                self.dependencies = None

    def add_child_process(self, child):

        # the childs have the same dependencies than the parent process because, from outside, it is viewed as a single process
        if self.dependencies is not None:
            for dep in self.dependencies:
                child.add_dependency(dep)

        if (self.childs.count(child) == 0):
            self.childs.append(child)

    def run(self, progress_bar):

        self.progress_bar = progress_bar
        self.progress_bar[0].set_label(self.text)
        self.progress_bar[1].set_fraction(0.0)
        self.progress_bar[0].show_all()
        # call, if it exists, the pre-function
        try:
            self.pre_function()
        except:
            pass
        self.launch_process(self.command_var)
        if self.use_pulse_mode != self.pulse_mode:
            self.set_pulse_mode(self.use_pulse_mode)

    def remove_ansi(self, line):

        output = ""
        while True:
            pos = line.find("\033[")  # try with double-byte ESC
            jump = 2
            if pos == -1:
                pos = line.find("\233")  # if not, try with single-byte ESC
                jump = 1
            if pos == -1:  # no ANSI characters; we ended
                output += line
                break

            output += line[:pos]
            line = line[pos + jump:]

            while True:
                if len(line) == 0:
                    break
                if (ord(line[0]) < 64) or (ord(line[0]) > 126):
                    line = line[1:]
                else:
                    line = line[1:]
                    break
        return output

    def launch_process(self, command, redirect_output=True):

        if command is not None:
            self.launch_command = "\n\nLaunching:"
            for e in command:
                self.launch_command += (" " + e)
            self.launch_command += "\n"

        self.config.append_log(self.text)
        if command is not None:
            self.config.append_log(self.launch_command)

        try:
            if (self.stdin_file is not None):
                self.handle = subprocess.Popen(command,
                                               stdin=subprocess.PIPE,
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE)
                self.channel_stdin = GLib.IOChannel(self.handle.stdin.fileno())
                self.channel_stdin.add_watch(GLib.IO_OUT | GLib.IO_HUP,
                                             self.read_stdin_from_file)
                self.file_in = open(self.stdin_file, "rb")
            else:
                self.handle = subprocess.Popen(command,
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE)
        except Exception as error_launch:
            self.handle = None
            self.stderr_data += str(error_launch)
            self.wait_end()
            return

        if (redirect_output):
            self.stdout_buf = ""
            self.stderr_buf = ""
            self.channel_stdout = GLib.IOChannel(self.handle.stdout.fileno())
            self.channel_stderr = GLib.IOChannel(self.handle.stderr.fileno())
            if (self.stdout_file is not None):
                self.channel_stdout.add_watch(GLib.IO_IN | GLib.IO_HUP,
                                              self.read_stdout_to_file)
                self.file_out = open(self.stdout_file, "wb")
            else:
                self.channel_stdout.add_watch(GLib.IO_IN | GLib.IO_HUP,
                                              self.read_stdout)
            self.channel_stderr.add_watch(GLib.IO_IN | GLib.IO_HUP,
                                          self.read_stderr)
        else:
            (stdout_r, stderr_r) = self.handle.communicate()
            self.handle = None
            self.config.append_log(self.launch_command)
            try:
                self.config.append_log(stdout_r.decode("utf-8"))
            except:
                self.config.append_log(stdout_r.decode("latin-1"))
            try:
                self.config.append_log(stderr_r.decode("utf-8"))
            except:
                self.config.append_log(stderr_r.decode("latin-1"))
            return (stdout_r, stderr_r)

    def set_pulse_mode(self, pulse_mode):

        if pulse_mode == self.pulse_mode:
            return

        self.pulse_mode = pulse_mode

        if pulse_mode:
            self.timer_pulse = GLib.timeout_add(250, self.run_pulse)
        else:
            GLib.source_remove(self.timer_pulse)

    def run_pulse(self, v=None):

        if self.progress_bar is None:
            return

        if self.pulse_text is not None:
            self.progress_bar[1].set_text(self.pulse_text)
        self.progress_bar[1].pulse()
        return True

    def read_stdout_to_file(self, source, condition):

        if (condition != GLib.IO_IN):
            self.channel_stdout = None
            if ((self.channel_stderr is None) and
                (self.channel_stdin is None)):
                self.wait_end()
            return False
        else:
            line_data = self.handle.stdout.read1(4096)
            self.file_out.write(line_data)
            return True

    def read_stdin_from_file(self, source, condition):

        line_data = self.file_in.read1(4096)
        if (len(line_data) == 0):
            self.channel_stdin = None
            self.handle.stdin.close()
            if ((self.channel_stderr is None) and
                (self.channel_stdout is None)):
                self.wait_end()
            return False
        else:
            self.handle.stdin.write(line_data)
            return True

    def read_stdout(self, source, condition):

        if (condition != GLib.IO_IN):
            self.channel_stdout = None
            if ((self.channel_stderr is None) and
                (self.channel_stdin is None)):
                self.wait_end()
            return False
        else:
            read_data = self.handle.stdout.read1(4096)
            try:
                line_data = self.stdout_buf + (read_data.decode("utf-8"))
            except:
                line_data = self.stdout_buf + (read_data.decode("latin-1"))
            self.stdout_data += line_data
            data = (line_data).replace("\r", "\n").split("\n")
            if (len(data) == 1):
                final_data = []
                self.stdout_buf = data[0]
            else:
                final_data = data[:-1]
                self.stdout_buf = data[-1]
            if (len(final_data) != 0):
                self.process_stdout(final_data)
            return True

    def read_stderr(self, source, condition):

        if (condition != GLib.IO_IN):
            self.channel_stderr = None
            if (((self.channel_stdout is None) or
                 (self.stdout_file is not None)) and
                ((self.channel_stdin is None) or
                 (self.stdin_file is not None))):
                self.wait_end()
            return False
        else:
            read_data = self.handle.stderr.read1(4096)
            try:
                line_data = self.stderr_buf + (read_data.decode("utf-8"))
            except:
                line_data = self.stderr_buf + (read_data.decode("latin-1"))
            self.stderr_data += line_data
            data = (line_data).replace("\r", "\n").split("\n")
            if (len(data) == 1):
                final_data = []
                self.stderr_buf = data[0]
            else:
                final_data = data[:-1]
                self.stderr_buf = data[-1]
            if (len(final_data) != 0):
                self.process_stderr(final_data)
            return True

    def cancel(self):
        """ Called to kill this process. """

        if self.handle is None:
            return

        self.killed = True
        os.kill(self.handle.pid, signal.SIGKILL)

    def wait_end(self):

        if self.handle is not None:
            retval = self.handle.wait()
            self.handle = None
        else:
            retval = -1

        self.set_pulse_mode(False)

        # call, if it exists, the post-function
        try:
            self.post_function(retval, self.killed)
        except:
            pass

        if self.killed:
            retval = 0
        else:
            self.config.append_log(self.stdout_data)
            self.config.append_log(self.stderr_data)

        self.emit("ended", retval)

    def expand_xml(self, text):

        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&apos;')
        return text

    def get_division(self, data):

        pos = data.find("/")
        pos2 = data.find(":")

        if (pos == -1):
            pos = pos2

        if (pos == -1):
            try:
                return float(data)
            except:
                return 0
        else:
            try:
                data1 = float(data[:pos])
                data2 = float(data[pos + 1:])
            except:
                return 0
            if (data2 == 0):
                return 0
            else:
                return (float(int((data1 / data2) * 1000.0))) / 1000.0

    def get_time(self, line):

        time_string = ""

        for letter in line.strip():
            if (letter == ':') or (letter == '.') or (letter.isdigit()):
                time_string += letter
            else:
                break

        elements = time_string.split(":")

        if (len(elements) == 0):
            return -1

        value = 0
        for element in elements:
            if (element == ''):
                continue
            value *= 60
            value += int(0.5 + float(element))
        return value
