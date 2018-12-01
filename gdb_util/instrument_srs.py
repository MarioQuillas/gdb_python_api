# code to instrument std::sort for my custom type
# see examples/sort_random_sequence.cpp

# Copyright (c) 2018 Jeff Trull

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import gdb
import re
from threading import Thread
from queue import Queue
from distutils.version import StrictVersion

# This code requires an (as of now) unreleased feature: writable breakpoint commands
# Produce a helpful error for anyone who tries to use this too soon, with a version check

if StrictVersion(gdb.VERSION) < StrictVersion('8.2'):
    raise NotImplementedError('this module relies on writable breakpoint commands, released in gdb 8.2')


class GuiThread(Thread):
    def __init__(self, base_addr, size):
        Thread.__init__(self)
        self.base_addr = base_addr  # the vector we are monitoring
        self.size = size            # its size
        self.messages = Queue()     # cross-thread communication
        # store contents of vec
        self.values = []
        int_t = gdb.lookup_type('int')
        for idx in range(0, size):
            self.values.append(int((base_addr + idx).dereference().cast(int_t)))
        self.animations = []

    # Front end code
    # These methods run in the gdb thread in response to breakpoints,
    # and accept gdb.Value objects

    # Updates for instrumented actions
    def show_swap(self, a, b):
        # sending gdb.Value objects over the queue doesn't seem to work
        # at least, their addresses are no longer accessible in the other thread
        # So we'll do the calculations here
        a_idx = a.address - self.base_addr
        b_idx = b.address - self.base_addr
        self._send_message('swap', int(a_idx), int(b_idx))

    def show_move(self, a, b):  # a moved into from b
        # a is always an address and b is an rvalue reference
        # so we use "a" and "b.address"

        # detect whether a or b is a temporary
        a_in_vec = (a >= self.base_addr) and (a < (self.base_addr + self.size))
        b_in_vec = (b.address >= self.base_addr) and (b.address < (self.base_addr + self.size))

        # we will supply temporaries as their address in string form,
        # and in-vector quantities as their offset (a Python int)
        # this way gdb.Value objects don't outlive their frame

        if a_in_vec and b_in_vec:
            a_idx = a - self.base_addr
            b_idx = b.address - self.base_addr
            self._send_message('move', int(b_idx), int(a_idx))
        elif a_in_vec:
            # source is a temporary; stringify its address to use as a token representing it
            a_idx = a - self.base_addr
            self._send_message('move_from_temp', str(b.address), int(a_idx))
        elif b_in_vec:
            # dest is a temporary
            b_idx = b.address - self.base_addr
            self._send_message('move_to_temp', int(b_idx), str(a))
        else:
            # I've never seen a move from temporary to temporary
            raise RuntimeError('saw an unexpected move from temporary to temporary')

    def _send_message(self, tp, src, dst):
        self.messages.put((tp, src, dst))   # contents are swap info

    # And now the back end.
    # These run in the GUI thread, taking commands and updating the display.
    # They use Qt objects and do *not* use gdb stuff
    # Only standard Python types cross the barrier

    def _check_for_messages(self):
        from PyQt5.QtCore import QPointF

        # poll command queue
        # not ideal but safe. OK for now.
        if not self.messages.empty():
            op, a, b = self.messages.get()
            if op is 'swap':
                # actually seems to understand the size of the elements:
                self._perform_swap(a, b)
            elif op is 'move':
                self.elements[b] = self.elements[a]
                self.elements[a] = None
                self._perform_move(self.elements[b], QPointF(20+20*b, 20))
            elif op is 'move_from_temp':
                # temporary elements indexed by address, as a string
                (pos, temp_elt) = self.temp_elements[a]
                self.temp_elements[a] = (pos, None)
                self._perform_move(temp_elt, QPointF(20+20*b, 20))
                self.elements[b] = temp_elt
            elif op is 'move_to_temp':
                # see if we know of this temp element
                if b in self.temp_elements:
                    # we already saw this address. reuse its position.
                    (pos, temp_elt) = self.temp_elements[b]
                else:
                    pos = QPointF(20+20*len(self.temp_elements), 60)
                self._perform_move(self.elements[a], pos)
                self.temp_elements[b] = (pos, self.elements[a])
                self.elements[a] = None
            else:
                print('unknown move command from %s to %s' % (a, b))

    def _perform_move(self, a, pos):
        from PyQt5.QtCore import QPropertyAnimation
        # create animation for this move operation
        anim = QPropertyAnimation(a, b'pos')
        anim.setDuration(200)
        anim.setEndValue(pos)
        anim.start()
        # the QPropertyAnimation object must outlive this method, so we attach it to this instance
        # TODO we should really collect it afterwards, perhaps with a handler for the finished() signal...
        self.animations.append(anim)

    def _perform_swap(self, a, b):
        from PyQt5.QtCore import QPointF, QPropertyAnimation

        elt_a = self.elements[a]
        elt_b = self.elements[b]
        # update positions
        pos_a = elt_a.pos
        pos_b = elt_b.pos

        # animate the exchange: move in an arc above/below a point halfway between
        pos_between = (pos_a + pos_b) / 2
        pos_above = QPointF(pos_between.x(), -10)
        pos_below = QPointF(pos_between.x(), 50)
        anim_a = QPropertyAnimation(self.elements[a], b'pos')
        anim_b = QPropertyAnimation(self.elements[b], b'pos')
        anim_a.setDuration(400)
        anim_b.setDuration(400)
        anim_a.setKeyValueAt(0.5, pos_above)
        anim_b.setKeyValueAt(0.5, pos_below)
        anim_a.setKeyValueAt(1, pos_b)
        anim_b.setKeyValueAt(1, pos_a)
        anim_a.start()
        anim_b.start()
        self.animations.append(anim_a)
        self.animations.append(anim_b)

        # update elements list
        self.elements[a] = elt_b
        self.elements[b] = elt_a

    def run(self):
        # putting the PyQt imports here avoids the "main thread" warning
        # it seems that merely importing the PyQt modules causes QObject accesses
        from PyQt5.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QGraphicsRectItem, QDesktopWidget
        from PyQt5.QtCore import Qt, QTimer, QObject
        from PyQt5.QtGui import QColor, QBrush, QPen, QPainterPath, QPainter, QFont

        # and that includes class definitions too :-/
        class Element(QGraphicsRectItem):
            def __init__(self, idx, value):
                super(Element, self).__init__()
                self.value = value
                self.setRect(0, 0, 20, 20)
                self.setPos(20+20*idx, 20)

            def paint(self, painter, options, widget):
                # drawing and filling a rounded rect
                painter.setRenderHint(QPainter.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(self.rect(), 2, 2)
                painter.fillPath(path, QColor('white'))
                painter.drawPath(path)
                painter.setFont(QFont('Inconsolata', 9))
                painter.drawText(self.rect(), Qt.AlignCenter, str(self.value))

        # animated objects must inherit from QObject
        # but QGraphicsRectItem does not, and it's too late (post compile) to fix it
        # so a proxy is used:
        class AnimProxy(QObject):
            from PyQt5.QtCore import pyqtProperty, QPointF

            def __init__(self, obj):
                super(AnimProxy, self).__init__()
                self.obj = obj     # the underlying non-QObject with "setPos" method

            @pyqtProperty(QPointF)
            def pos(self):
                return self.obj.pos()

            @pos.setter
            def pos(self, pt):
                self.obj.setPos(pt)

        class VectorView(QGraphicsView):
            def __init__(self):
                super(VectorView, self).__init__()
                self.resize(QDesktopWidget().availableGeometry(self).size())

            def resizeEvent(self, e):
                self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

        self.app = QApplication([])

        self.scene = QGraphicsScene()

        # a gray background rectangle to reveal for "moved from" elements
        self.scene.addRect(20, 20, 20*len(self.values), 20, QPen(), QColor('grey'))

        # then the elements themselves
        idx = 0   # or zip with index
        self.elements = []
        for v in self.values:
            elt = Element(idx, v)
            # we manipulate position through the AnimProxy (QObject)
            self.elements.append(AnimProxy(elt))
            # but QGraphicsScene gets the underlying Element (QGraphicsRectItem)
            self.scene.addItem(elt)
            idx = idx + 1

        # positions for temp elements
        self.temp_elements = {}

        self.view = VectorView()
        self.view.setScene(self.scene)
        self.view.show()

        # periodically poll command queue
        self.cmd_poll_timer = QTimer()
        self.cmd_poll_timer.timeout.connect(self._check_for_messages)
        self.cmd_poll_timer.start(500)   # throttling to 700ms per action for visibility

        self.app.exec_()


#
# define observability breakpoints
#

# my special swap, initially disabled to avoid the call to std::shuffle
swap_bp = gdb.Breakpoint('swap(int_wrapper_t&, int_wrapper_t&)')
swap_bp.enabled = False  # off until we get to our algorithm of interest
swap_bp.silent = True    # don't spam user

# move ctor
move_bp = gdb.Breakpoint('int_wrapper_t::int_wrapper_t(int_wrapper_t&&)')
move_bp.enabled = False
move_bp.silent = True

# move assignment operator
move_assign_bp = gdb.Breakpoint('int_wrapper_t::operator=(int_wrapper_t&&)')
move_assign_bp.enabled = False
move_assign_bp.silent = True

# and for the algorithm itself:
sort_bp = gdb.Breakpoint('std::sort<std::vector<int_wrapper_t, std::allocator<int_wrapper_t> >::iterator>')
sort_bp.enabled = True
sort_bp.silent = True

# next prepare to enable and execute the swap display commands

# The code below requires gdb 8.1.1 which enabled writable commands for breakpoints

# actions for when we arrive at std::sort
# TODO is there a way to improve this formatting?
sort_bp.commands = (
    # a breakpoint at the end of std::sort, for cleanup and to keep our process alive
    "py finish_bp = gdb.FinishBreakpoint()\n"
    # move up to the main() frame to accessvariables
    "py gdb.selected_frame().older().select()\n"
    # tell our gui thread about the container being sorted
    # new gdb 8.1.1 does not seem to understand the operator[], though 8.1.0 did
    # "py gdb_util.instrument_srs.gui = gdb_util.instrument_srs.GuiThread(gdb.parse_and_eval('&A[0]'), gdb.parse_and_eval('A.size()'))\n"
    "py gdb_util.instrument_srs.gui = gdb_util.instrument_srs.GuiThread(gdb.parse_and_eval('A._M_impl._M_start'), gdb.parse_and_eval('A._M_impl._M_finish - A._M_impl._M_start'))\n"
    # launch gui
    "py gdb_util.instrument_srs.gui.start()\n"
    # turn on observability breakpoints
    "enable %d\n"
    "enable %d\n"
    "enable %d\n"
    # run the algorithm
    "c\n"
    "end\n")%(swap_bp.number, move_bp.number, move_assign_bp.number)

# actions for each swap()
swap_bp.commands = (
    "py gdb_util.instrument_srs.gui.show_swap(gdb.selected_frame().read_var('a'), gdb.selected_frame().read_var('b'))\n"
    # now pass through the actual swap execution while ignoring any moves
    "disable %d\n"
    "disable %d\n"
    "py fbp = gdb.FinishBreakpoint(internal=True)\n"
    "py fbp.silent = True\n"
    # re-enable moves at the finish breakpoint
    # (we will not execute any commands after our own continue, per gdb manual)
    "py fbp.commands = 'enable %d\\nenable %d\\nc\\n'\n"
    # resume
    "c\n"
    "end\n")%(move_bp.number, move_assign_bp.number, move_bp.number, move_assign_bp.number)

# actions for move (either construct or assign)
move_commands = (
    "py gdb_util.instrument_srs.gui.show_move(gdb.selected_frame().read_var('this'), gdb.selected_frame().read_var('other'))\n"
    "c\n"
    "end\n")
move_bp.commands = move_commands
move_assign_bp.commands = move_commands

