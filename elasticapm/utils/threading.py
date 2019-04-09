#  BSD 3-Clause License
#
#  Copyright (c) 2019, Elasticsearch BV
#  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
#  * Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
#  FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#  DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#  SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE


from __future__ import absolute_import

import threading
from timeit import default_timer


class IntervalTimer(threading.Thread):
    """
    A timer that runs a function repeatedly. In contrast to threading.Timer,
    IntervalTimer runs the given function in perpetuity or until it is cancelled.
    When run, it will wait `interval` seconds until the first execution.
    """

    def __init__(self, function, interval, name=None, args=(), kwargs=None, daemon=None):
        super(IntervalTimer, self).__init__(name=name)
        self.daemon = daemon
        self._args = args
        self._kwargs = kwargs if kwargs is not None else {}
        self._function = function
        self._interval = interval
        self._interval_done = threading.Event()

    def run(self):
        execution_time = 0
        while True:
            real_interval = self._interval - execution_time
            interval_completed = True
            if real_interval:
                interval_completed = not self._interval_done.wait(real_interval)
            if not interval_completed:
                # we've been cancelled, time to go home
                return
            start = default_timer()
            self._function(*self._args, **self._kwargs)
            execution_time = default_timer() - start

    def cancel(self):
        self._interval_done.set()
