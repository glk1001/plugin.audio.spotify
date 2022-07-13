"""
meta.py

Some useful metaclasses.
"""


class TagRegistered(type):
    """
    As classes of this metaclass are created, they keep a registry in the
    base class of all classes by a class attribute, indicated by attr_name.

    >>> FooObject = TagRegistered('FooObject', (), dict(tag='foo'))
    >>> FooObject._registry['foo'] is FooObject
    True
    >>> BarObject = TagRegistered('Barobject', (FooObject,), dict(tag='bar'))
    >>> FooObject._registry is BarObject._registry
    True
    >>> len(FooObject._registry)
    2
    >>> FooObject._registry['bar']
    <class 'jaraco.classes.meta.Barobject'>
    """

    attr_name = 'tag'

    def __init__(cls, name, bases, namespace):
        super(TagRegistered, cls).__init__(name, bases, namespace)
        if not hasattr(cls, '_registry'):
            cls._registry = {}
        meta = cls.__class__
        attr = getattr(cls, meta.attr_name, None)
        if attr:
            cls._registry[attr] = cls
