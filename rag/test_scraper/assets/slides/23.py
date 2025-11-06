class CallCounter:
    """Count the number of times a function was called.

    >>> fib_counter = CallCounter()
    >>> fib = fib_counter.count(fib)
    >>> fib(35)
    9227465
    >>> fib_counter.n
    29860703
    >>> fib_counter.n = 0
    >>> fib = memo(fib)
    >>> fib(35)
    9227465
    >>> fib_counter.n
    36
    >>> fib_counter.n = 0
    >>> fib(200)
    280571172992510140037611932413038677189525
    >>> fib_counter.n
    165
    """
    def __init__(self):
        self.n = 0

    def count(self, f):
        def counted(n):
            self.n += 1
            return f(n)
        return counted
    
def fib(n):
    if n == 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fib(n-2) + fib(n-1)

def memo(f):
    cache = {}
    def memoized(n):
        if n not in cache:
            cache[n] = f(n)
        return cache[n]
    return memoized

###

def cycle(k, n):
    """Build an n-element list that cycles among range(k).

    >>> cycle(3, 10)
    [0, 1, 2, 0, 1, 2, 0, 1, 2, 0]
    """
    s = []
    for i in range(n):
        s.append(i % k)  # Add to the end
    return s

def cycle_link(k, n):
    """Build an n-element linked list that cycles among range(k).

    >>> print(cycle_link(3, 10))
    (0 1 2 0 1 2 0 1 2 0)
    """
    result = Link.empty
    while n > 0:
        n -= 1
        result = Link(n % k, result)  # Add to the front
    return result

def cycle_link_append(k, n):
    """Build an n-element linked list that cycles among range(k).

    >>> print(cycle_link_append(3, 10))
    (0 1 2 0 1 2 0 1 2 0)
    """
    first = Link.empty
    for i in range(n):
        new_link = Link(i % k)
        if first is Link.empty:
            first, last = new_link, new_link
        else:
            last.rest = new_link
            last = new_link
    return first

def double(s, v):
    """Insert another v after each v in s.

    >>> s = [2, 7, 1, 8, 2, 8]
    >>> double(s, 8)
    >>> s
    [2, 7, 1, 8, 8, 2, 8, 8]
    """
    i = 0
    while i < len(s):
        if s[i] == v:
            s.insert(i+1, v)
            i += 2
        else:
            i += 1

def double_fast(s, v):
    """Insert another v after each v in s.

    >>> s = [2, 7, 1, 8, 2, 8]
    >>> double_fast(s, 8)
    >>> s
    [2, 7, 1, 8, 8, 2, 8, 8]
    """
    read = len(s) - 1
    vs = s.count(v)
    s.extend([0 for _ in range(vs)])  # Make space for extra vs
    write = len(s) - 1
    while write > read:
        if s[read] == v:
            s[write] = v
            s[write - 1] = v
            write -= 2
        else:
            s[write] = s[read]
            write -= 1
        read -= 1

def double_link(s, v):
    """Insert another v after each v in s.

    >>> s = Link(2, Link(7, Link(1, Link(8, Link(2, Link(8))))))
    >>> double_link(s, 8)
    >>> print(s)
    (2 7 1 8 8 2 8 8)
    """
    while s is not Link.empty:
        if s.first == v:
            s.rest = Link(v, s.rest)
            s = s.rest.rest
        else:
            s = s.rest

def time_double():
    from timeit import timeit
    with_list = 'double(     cycle(     5, 100000), 3)'
    with_link = 'double_link(cycle_link_append(5, 100000), 3)'
    list_fast = 'double_fast(cycle(     5, 100000), 3)'
    imports = 'from cycle import double, double_fast, double_link, cycle, cycle_link_append'
    print('with_list:', round(100*timeit(with_list, imports, number=10)), 'ms')
    print('with_link:', round(100*timeit(with_link, imports, number=10)), 'ms')
    print('list_fast:', round(100*timeit(list_fast, imports, number=10)), 'ms')



class Link:
    """A linked list.

    >>> s = Link(3, Link(4, Link(5)))
    >>> s
    Link(3, Link(4, Link(5)))
    >>> print(s)
    (3 4 5)
    """
    empty = ()

    def __init__(self, first, rest=empty):
        assert rest is Link.empty or isinstance(rest, Link)
        self.first = first
        self.rest = rest

    def __repr__(self):
        if self.rest:
            rest_repr = ', ' + repr(self.rest)
        else:
            rest_repr = ''
        return 'Link(' + repr(self.first) + rest_repr + ')'

    def __str__(self):
        string = '('
        while self.rest is not Link.empty:
            string += str(self.first) + ' '
            self = self.rest
        return string + str(self.first) + ')'
