# encoding: utf-8

'''
cloner synchronises two directories so that destination is equal to source, ignoring file permissions
it can use different methods to test wether two files are equal
it can create a database to speed up successive synchronisations
'''

import os
from stat import *
import time, sys
from shutil import copy2, rmtree, copystat

def usage():
    print 'cloner source_path destination_path'


def main():
    try:
        src_path = os.path.abspath(sys.argv[1])
        if not os.path.isdir(src_path):
            raise
        dst_path = os.path.abspath(sys.argv[2])
        if os.path.exists(dst_path) and not os.path.isdir(dst_path):
            raise
    except:
        usage()
        exit(1)
    
    clone(src_path, dst_path, files_are_equal=compare_lazy_and_fix)
    
_compare_size_date_cache = {}
def compare_size_date(p1, p2, use_cache = True):
    #if not os.path.isfile(p1) or not os.path.isfile(p2):
    #	return False
    # os.stat win7x64/py2.7 (c:/pagefile.sys): nt.stat_result(st_mode=33206, st_ino=0L, st_dev=0, st_nlink=0, st_uid=0, st_gid=0, st_size=5232394240L, st_atime=1295195959L, st_mtime=1295395403L, st_ctime=1252095642L)
    try:
        if not use_cache or p1 not in _compare_size_date_cache:
            _compare_size_date_cache[p1] = os.stat(p1)
        s1 = _compare_size_date_cache[p1]
        if not use_cache or p2 not in _compare_size_date_cache:
            _compare_size_date_cache[p2] = os.stat(p2)
        s2 = _compare_size_date_cache[p2]
    except OSError:
        return False
    return S_ISREG(s1[ST_MODE]) and S_ISREG(s2[ST_MODE]) and int(s1.st_mtime) == int(s2.st_mtime) and s1.st_size == s2.st_size


import hashlib
from multiprocessing import Process, Pipe
def _compare_hash_helper(path, pipe):
    with open(path, 'rb') as fd:
        pipe.send(hashlib.sha1(fd.read()).digest())
        pipe.close()
_compare_hash_cache = {}
def compare_hash(path1, path2, use_cache = True):
    '''a caching, multi-threaded file content hash compare function
    tries to do as little as possible and all at once.
    '''
    if not os.path.isfile(path1) or not os.path.isfile(path2):
        return False
    # setting up multiprocessing
    hash1_proc, hash2_proc = None, None
    max_name_len = (79-10-4)//2
    status_msg = 'hashing '
    if not use_cache or path1 not in _compare_hash_cache:
        hash1_pipe, child_conn = Pipe()
        hash1_proc = Process(target=_compare_hash_helper, args=(path1, child_conn))
        hash1_proc.start()
        # build status msg
        status_msg += '`%s..%s`' % (path1[:max_name_len//2-1], path1[-max_name_len//2+1:])
    if not use_cache or path2 not in _compare_hash_cache:
        hash2_pipe, child_conn = Pipe()
        hash2_proc = Process(target=_compare_hash_helper, args=(path2, child_conn))
        hash2_proc.start()
        # build status msg
        if len(status_msg) > 10:
            status_msg += ', '
        status_msg += '`%s..%s`' % (path2[:max_name_len//2-1], path2[-max_name_len//2+1:])
    print_(status_msg, templine = True, newline = False)
    # getting hashing results (and storing them in cache)
    if hash1_proc is not None:
        hash1_proc.join()
        hash = hash1_pipe.recv()
        _compare_hash_cache[path1] = hash
    if hash2_proc is not None:
        hash2_proc.join()
        hash = hash2_pipe.recv()
        _compare_hash_cache[path2] = hash
    # clear status message
    print_(' '*79, templine = True, newline = False)
    # return what we've learned
    return _compare_hash_cache[path1] == _compare_hash_cache[path2]
    
def compare_lazy_and_fix(p1, p2):
    '''only compares hashes if sizes and attributes don't match
    then tries to fix attributes if it turns out the hashes match
    WARNING! this means this function has a side effect on the file system!
    it can change a file's attributes without user interaction
    '''
    if compare_size_date(p1, p2):
        return True
    if compare_hash(p1, p2):
        log('fixing attributes for `%s`'%p2)
        copystat(p1, p2)
        return compare_size_date(p1, p2, use_cache = False) # rebuilding cache entry
    return False

def compare_content(p1, p2):
    '''stupid uncachable file comparison; not very useful'''
    if not os.path.isfile(p1) or not os.path.isfile(p2):
        return False
    if os.path.getsize(p1) != os.path.getsize(p2):
        return False
    with open(p1, 'rb') as fd1, open(p2, 'rb') as fd2:
        chunk_size = 2**21 # 2mb
        while 1:
            c1 = fd1.read(chunk_size)
            if not len(c1):
                break
            c2 = fd2.read(chunk_size)
            if c1!=c2:
                return False
    return True

def print_(*s, **kw):
    newline = kw['newline'] if 'newline' in kw else True
    templine = kw['templine'] if 'templine' in kw else False
    s = ' '.join(s)
    sys.stdout.write(s.encode('unicode_escape').replace(os.path.sep.encode('unicode_escape'), os.path.sep))
    if templine and not s.endswith('\r'):
        sys.stdout.write('\r')
    if newline and not s.endswith('\n'):
        sys.stdout.write('\n')
    
def error(s):
    print_('ERR(%.3f):'%time.time(), s)

def log(s):
    print_('LOG(%.3f):'%time.time(), s)

def create_dir(dir_path):
    if not os.path.exists(dir_path):
        os.mkdir(dir_path)
        log('created `%s`' % dir_path)
    elif not os.path.isdir(dir_path):
        error('conflict in `%s`' % dir_path)
        return False
    return True

def copy(p1, p2):
    # print some nice status message
    p1_name = p1
    max_name_len = 69
    if len(p1_name) > max_name_len:
        p1_name = '%s..%s' % (p1_name[:max_name_len//2], p1_name[-max_name_len//2:])
    print_('copying', p1_name, templine = True, newline = False)
    # find a temporary name for the new file
    i=0
    while 1:
        i+=1
        tmp = p2 + '~%i'%i
        if not os.path.exists(tmp):
            break
    # copy the file
    try:
        copy2(p1, tmp)
    except IOError, e:
        if e.errno == 2: # windows: No such file or directory
            error('%s `%s`' % (e.strerror, p1))
            return False
        if e.errno == 13: # windows: permission denied
            error('%s `%s`' % (e.strerror, p1))
            return False
        if e.errno == 22: # windows: invalid mode ('rb') or filename / file unreadable / b0rked :/
            error('%s `%s`' % (e.strerror, p1))
            return False
        raise
    # remove any existing file
    if os.path.exists(p2):
        os.unlink(p2)
    # rename the file
    os.rename(tmp, p2)
    # clear status message
    print_(' '*79, templine = True, newline = False)

def clone(src_path, dst_path, ask_before_damaging = True, overwrite_existing_files = False, remove_superfluous = False, files_are_equal = compare_size_date):
    # make sure we're working with unicode strings
    src_path, dst_path = unicode(src_path), unicode(dst_path)
    log('cloning `%s` -> `%s`' % (src_path, dst_path))
    # sync!
    for src_base, dirs, files in os.walk(src_path):
        # define dst base
        dst_base = os.path.join(dst_path, src_base[len(src_path):].lstrip(os.path.sep))
        # make sure dst base exists
        if not create_dir(dst_base):
            log('skipping `%s`' % dst_base)
            del dirs[:] # clear dirs for next os.walk iteration
            continue
            
        # remove superfluous files from dst base
        remove_all_files_lock = False
        for e in os.listdir(dst_base):
            dst_e = os.path.join(dst_base, e)
            if os.path.isfile(dst_e):
                if e not in files:
                    log('superfluous file `%s`' % dst_e)
                    if remove_superfluous:
                        okay_to_remove = True
                        if ask_before_damaging and not remove_all_files_lock:
                            mode = raw_input('remove? (y/n/a) ')
                            if mode == 'a':
                                remove_all_files_lock = True
                            elif mode != 'y':
                                okay_to_remove = False
                        if okay_to_remove:
                            log('removing `%s`' % dst_e)
                            os.remove(dst_e)
            elif os.path.isdir(dst_e):
                if e not in dirs:
                    log('superfluous dir `%s`' % dst_e)
                    if remove_superfluous:
                        okay_to_remove = True
                        if ask_before_damaging:
                            if raw_input('remove? (y/n) ') != 'y':
                                okay_to_remove = False
                        if okay_to_remove:
                            log('removing `%s`' % dst_e)
                            rmtree(dst_e)
        
        # creating sub-dirs is handled by creating base dirs already. :]
        
        # copy files
        for file_name in files:
            src_file = os.path.join(src_base, file_name)
            dst_file = os.path.join(dst_base, file_name)
            if not os.path.exists(dst_file):
                copy(src_file, dst_file)
            else:
                if not files_are_equal(src_file, dst_file):
                    if not overwrite_existing_files:
                        error('file exists `%s` (overwrite disabled)' % dst_file)
                    else:
                        log('file exists `%s`' % dst_file)
                        okay_to_overwrite = True
                        if ask_before_damaging:
                            if raw_input('overwrite? (y/n) ') != 'y':
                                okay_to_overwrite = False
                        if okay_to_overwrite:
                            log('overwriting `%s`' % dst_file)
                            copy(src_file, dst_file)
                # else:
                    # log('skipping `%s` (equal)' % src_file)

    log('done')

if __name__ == '__main__':
    main()
    
