# Copyright (c) 2013, Kristoffer Gronlund
#
# psshlib API
#
# Exposes an API for performing
# parallel SSH operations
#
# Three commands are supplied:
#
# call(hosts, cmdline, opts)
#
# copy(hosts, src, dst, opts)
#
# slurp(hosts, src, dst, opts)
#
# call returns {host: (rc, stdout, stdin) | error}
# copy returns {host: path | error}
# slurp returns {host: path | error}
#
# error is an error object which has an error message (or more)
#
# opts is command line options as given to pssh/pscp/pslurp
#
# call: Executes the given command on a set of hosts, collecting the output
# copy: Copies files from the local machine to a set of remote hosts
# slurp: Copies files from a set of remote hosts to local folders

import os
import sys
from psshlib.cli import DEFAULT_PARALLELISM, DEFAULT_TIMEOUT
from psshlib.manager import Manager, FatalError
from psshlib.task import Task


class Error(object):
    """
    Returned instead of a result for a host
    in case of an error during the processing for
    that host.
    """
    def __init__(self, msg):
        self.msg = msg


class Options(object):
    """
    Common options for call, copy and slurp.
    """
    limit = DEFAULT_PARALLELISM  # Max number of parallel threads
    timeout = DEFAULT_TIMEOUT    # Timeout in seconds
    askpass = False              # Ask for a password
    outdir = None                # Write stdout to a file per host in this directory
    errdir = None                # Write stderr to a file per host in this directory
    ssh_options = []             # Extra options to pass to SSH
    ssh_extra = []               # Extra arguments to pass to SSH
    verbose = False              # Warning and diagnostic messages
    quiet = False                # Silence extra output
    print_out = False            # Print output to stdout when received
    inline = True                # Store stdout and stderr in memory buffers
    inline_stdout = False        # Store stdout in memory buffer
    input_stream = None          # Stream to read stdin from
    recursive = True             # (copy, slurp only) Copy recursively


def _expand_host_port_user(lst):
    """
    Input: list containing hostnames, (host, port)-tuples or (host, port, user)-tuples.
    Output: list of (host, port, user)-tuples.
    """
    for v in lst:
        if isinstance(v, basestring):
            return (v, None, None)
        elif len(v) == 1:
            return (v[0], None, None)
        elif len(v) == 2:
            return (v[0], v[1], None)
        else:
            return v


class _CallOutputBuilder(object):
    def __init__(self):
        self.finished_tasks = []

    def finished(self, task, n):
        """Called when Task is complete"""
        self.finished_tasks.append(task)

    def result(self, manager):
        """Called when all Tasks are complete to generate result"""
        ret = {}
        for task in self.finished_tasks:
            if task.failures:
                ret[task.host] = Error(', '.join(task.failures))
            else:
                ret[task.host] = (task.exitstatus,
                                  task.outputbuffer or manager.outdir,
                                  task.errorbuffer or manager.errdir)
        return ret


def _build_call_cmd(host, port, user, cmdline, options, extra):
    cmd = ['ssh', host,
           '-o', 'NumberOfPasswordPrompts=1',
           '-o', 'SendEnv=PSSH_NODENUM PSSH_HOST']
    if options:
        for opt in options:
            cmd += ['-o', opt]
    if user:
        cmd += ['-l', user]
    if port:
        cmd += ['-p', port]
    if extra:
        cmd.extend(extra)
    if cmdline:
        cmd.append(cmdline)
    return cmd


def call(hosts, cmdline, opts=Options()):
    """
    Executes the given command on a set of hosts, collecting the output
    Returns {host: (rc, stdout, stdin) | Error}
    """
    if opts.outdir and not os.path.exists(opts.outdir):
        os.makedirs(opts.outdir)
    if opts.errdir and not os.path.exists(opts.errdir):
        os.makedirs(opts.errdir)
    manager = Manager(limit=opts.limit,
                      timeout=opts.timeout,
                      askpass=opts.askpass,
                      outdir=opts.outdir,
                      errdir=opts.errdir,
                      callbacks=_CallOutputBuilder())
    for host, port, user in _expand_host_port_user(hosts):
        cmd = _build_call_cmd(host, port, user, cmdline,
                              options=opts.ssh_options,
                              extra=opts.ssh_extra)
        t = Task(host, port, user, cmd,
                 stdin=opts.input_stream,
                 verbose=opts.verbose,
                 quiet=opts.quiet,
                 print_out=opts.print_out,
                 inline=opts.inline,
                 inline_stdout=opts.inline_stdout)
        manager.add_task(t)
    try:
        return manager.run()
    except FatalError:
        sys.exit(1)


class _CopyOutputBuilder(object):
    def __init__(self, dst):
        self.finished_tasks = []

    def finished(self, task, n):
        self.finished_tasks.append(task)

    def result(self, manager):
        ret = {}
        for task in self.finished_tasks:
            if task.failures:
                ret[task.host] = Error(', '.join(task.failures))
            else:
                ret[task.host] = (task.exitstatus,
                                  task.outputbuffer or manager.outdir,
                                  task.errorbuffer or manager.errdir)
        return ret


def _build_copy_cmd(host, port, user, src, dst, opts):
    cmd = ['scp', '-qC']
    if opts.options:
        for opt in opts.options:
            cmd += ['-o', opt]
    if port:
        cmd += ['-P', port]
    if opts.recursive:
        cmd.append('-r')
    if opts.extra:
        cmd.extend(opts.extra)
    cmd.extend(src)
    if user:
        cmd.append('%s@%s:%s' % (user, host, dst))
    else:
        cmd.append('%s:%s' % (host, dst))
    return cmd


def copy(hosts, src, dst, opts=Options()):
    """
    Copies from the local node to a set of remote hosts
    hosts: [(host, port, user)...]
    src: local path
    dst: remote path
    opts: CopyOptions (optional)
    """
    if opts.outdir and not os.path.exists(opts.outdir):
        os.makedirs(opts.outdir)
    if opts.errdir and not os.path.exists(opts.errdir):
        os.makedirs(opts.errdir)
    manager = Manager(limit=opts.limit,
                      timeout=opts.timeout,
                      askpass=opts.askpass,
                      outdir=opts.outdir,
                      errdir=opts.errdir,
                      callbacks=_CopyOutputBuilder())
    for host, port, user in _expand_host_port_user(hosts):
        cmd = _build_copy_cmd(host, port, user, src, dst, opts)
        t = Task(host, port, user, cmd,
                 stdin=opts.input_stream,
                 verbose=opts.verbose,
                 quiet=opts.quiet,
                 print_out=opts.print_out,
                 inline=opts.inline,
                 inline_stdout=opts.inline_stdout)
        manager.add_task(t)
    try:
        return manager.run()
    except FatalError:
        sys.exit(1)


class _SlurpOutputBuilder(object):
    def __init__(self):
        self.finished_tasks = []

    def finished(self, task, n):
        self.finished_tasks.append(task)

    def result(self, manager):
        ret = {}
        for task in self.finished_tasks:
            if task.failures:
                ret[task.host] = Error(', '.join(task.failures))
            else:
                # TODO: save name of output file in Task
                ret[task.host] = (task.exitstatus,
                                  task.outputbuffer or manager.outdir,
                                  task.errorbuffer or manager.errdir)
        return ret


def _slurp_make_local_dirs(hosts, dst, opts):
    if not os.path.exists(dst):
        os.makedirs(dst)
    for host, port, user in _expand_host_port_user(hosts):
        if opts.localdir:
            dirname = "%s/%s" % (opts.localdir, host)
        else:
            dirname = host
        if not os.path.exists(dirname):
            os.mkdir(dirname)


def _build_slurp_cmd(host, port, user, src, dst, opts):
    cmd = ['scp', '-qC']
    if opts.options:
        for opt in opts.options:
            cmd += ['-o', opt]
    if port:
        cmd += ['-P', port]
    if opts.recursive:
        cmd.append('-r')
    if opts.extra:
        cmd.extend(opts.extra)
    if user:
        cmd.append('%s@%s:%s' % (user, host, src))
    else:
        cmd.append('%s:%s' % (host, src))
    cmd.append(dst)
    return cmd


def slurp(hosts, src, dst, opts=Options()):
    """
    Copies from the remote node to the local node
    hosts: [(host, port, user)...]
    src: remote path
    dst: local path
    opts: CopyOptions (optional)
    """
    _slurp_make_local_dirs(hosts, dst, opts)
    if opts.outdir and not os.path.exists(opts.outdir):
        os.makedirs(opts.outdir)
    if opts.errdir and not os.path.exists(opts.errdir):
        os.makedirs(opts.errdir)
    manager = Manager(limit=opts.limit,
                      timeout=opts.timeout,
                      askpass=opts.askpass,
                      outdir=opts.outdir,
                      errdir=opts.errdir,
                      callbacks=_SlurpOutputBuilder())
    for host, port, user in _expand_host_port_user(hosts):
        if opts.localdir:
            localpath = "%s/%s/%s" % (opts.localdir, host, dst)
        else:
            localpath = "%s/%s" % (host, dst)
        cmd = _build_slurp_cmd(host, port, user, src, localpath, opts)
        t = Task(host, port, user, cmd,
                 stdin=opts.input_stream,
                 verbose=opts.verbose,
                 quiet=opts.quiet,
                 print_out=opts.print_out,
                 inline=opts.inline,
                 inline_stdout=opts.inline_stdout)
        manager.add_task(t)
    try:
        return manager.run()
    except FatalError:
        sys.exit(1)
