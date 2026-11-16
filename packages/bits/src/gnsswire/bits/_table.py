"""Declarative field tables: a frozen dataclass whose annotations are the table.

Each field of a message dataclass is one row of the spec's table: its name,
and in ``typing.Annotated`` metadata its kind and width::

    @dataclass(frozen=True, slots=True)
    class Cell:
        fine: Annotated[int, S(15)]

    @dataclass(frozen=True, slots=True)
    class Example:
        number: Annotated[int, U(12, "DF002")]
        sat_mask: Annotated[int, U(64)]
        sig_mask: Annotated[int, U(32)]
        cell_mask: Annotated[int, U(popcount(F.sat_mask) * popcount(F.sig_mask))]
        rough: Annotated[tuple[int, ...], U(8, count=popcount(F.sat_mask))]
        cells: Annotated[tuple[Cell, ...], Group(Cell, count=popcount(F.cell_mask))]
        extra: Annotated[int | None, U(4, when=F.number == 1077)]

Rows are read and written in declaration order. Kinds:

``U(width)``, ``S(width)``, ``SM(width)``
    unsigned, two's complement and sign-magnitude integers of up to 64 bits
    (see ``_io``).
``Mask(width)``
    an unsigned bit mask of any width, for the masks that exceed 64 bits
    (SPARTN SF079: up to 256).
``Octets(length)``
    whole bytes, kept as ``bytes``; ``length`` counts bytes.
``Group(cls)``
    a nested message dataclass with its own table.
``Rest()``
    the bits after the table's other rows, to the end of the data: ``None``
    when they are fewer than eight and all zero (plain fill bits), otherwise
    an :class:`Extension` holding them. Only as the last row of the outermost
    table, with no ``count`` or ``when``. Writing an :class:`Extension` puts
    its bits back, so a table with a ``Rest`` row reads any data that starts
    with the table and writes it back unchanged. This is for formats whose
    specification lets later versions append fields that a decoder must
    skip (RTCM 10403.3 section 3.5.16.3.4, SPARTN v2.0.3 section 8.4 item 4).

Every kind takes two optional dependent attributes:

``count=``
    the row repeats; the value is a tuple of that many items.
``when=``
    the row is present only when this is non-zero; otherwise the value is
    ``None`` and no bits are read or written.

Widths, lengths, counts and conditions are ints or expressions over fields
read earlier. ``F.name`` refers to a field; inside a group, names resolve in
the group first and then outwards through the enclosing messages. Expressions
support ``+ - * // % << >> & | ^``, comparisons, ``popcount(e)`` and
``e.map({key: value})``. ``a & b`` does not evaluate ``b`` when ``a`` is zero,
so ``(F.flag == 0) & (F.mask & 4 != 0)`` may refer to a field that is absent
when ``flag`` is set. They are data, not code: :func:`layout` exposes the
compiled rows so that other tools (documentation, generated decoders) can
walk them.

Parameters: a table may depend on integers that are not in its own bits but
in an enclosing layer (SPARTN v2.0.3 marks such fields ``**``: their width
depends on the constellation, which the transport layer's subtype TF007
gives). The dataclass names them in a ``PARAMS`` class attribute, its
expressions refer to them with ``F.name`` like fields, and every call that
reads or writes the table passes them as keywords::

    class Ocb:
        PARAMS: ClassVar[tuple[str, ...]] = ("subtype",)
        ephemeris_type: Annotated[int, U(F.subtype.map({0: 2, 1: 2, 2: 3}))]

    unpack(Ocb, payload, subtype=2)

Parameters are not fields: they are not stored in the message.

Values are not validated against the spec's ranges; a row only checks that a
value fits its width. A message is the raw integers on the wire.
"""

from __future__ import annotations

import dataclasses
import operator
import typing
from collections.abc import Callable, Iterator, Mapping
from typing import Any, TypeVar

from ._io import BitError, BitReader, BitWriter

T = TypeVar("T")


# --- expressions -------------------------------------------------------------

class Expr:
    """A value computed from fields read earlier. Build with ``F``, not directly."""

    __slots__ = ()
    __hash__ = object.__hash__

    def eval(self, env: Callable[[str], Any]) -> int:
        raise NotImplementedError

    def refs(self) -> Iterator[str]:
        raise NotImplementedError

    def __bool__(self) -> bool:
        raise TypeError("an Expr has no truth value; combine conditions with & and |")

    def map(self, table: Mapping[int, int]) -> Expr:
        """Look the value up in ``table``; a value not in it is a decode error."""
        return Lookup(self, dict(table))


def _lift(value: Expr | int) -> Expr:
    if isinstance(value, Expr):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Const(value)
    raise TypeError(f"expected an int or an Expr, not {type(value).__name__}")


_BINARY: dict[str, Callable[[int, int], int]] = {
    "+": operator.add, "-": operator.sub, "*": operator.mul, "//": operator.floordiv,
    "%": operator.mod, "<<": operator.lshift, ">>": operator.rshift, "&": operator.and_,
    "|": operator.or_, "^": operator.xor,
    "==": lambda a, b: int(a == b), "!=": lambda a, b: int(a != b),
    "<": lambda a, b: int(a < b), "<=": lambda a, b: int(a <= b),
    ">": lambda a, b: int(a > b), ">=": lambda a, b: int(a >= b),
}


def _binary(op: str, swap: bool = False) -> Callable[[Expr, Expr | int], Expr]:
    def method(self: Expr, other: Expr | int) -> Expr:
        a, b = self, _lift(other)
        return Binary(op, b, a) if swap else Binary(op, a, b)
    return method


for _sym, _name in [("+", "add"), ("-", "sub"), ("*", "mul"), ("//", "floordiv"),
                    ("%", "mod"), ("<<", "lshift"), (">>", "rshift"), ("&", "and"),
                    ("|", "or"), ("^", "xor")]:
    setattr(Expr, f"__{_name}__", _binary(_sym))
    setattr(Expr, f"__r{_name}__", _binary(_sym, swap=True))
for _sym, _name in [("==", "eq"), ("!=", "ne"), ("<", "lt"), ("<=", "le"),
                    (">", "gt"), (">=", "ge")]:
    setattr(Expr, f"__{_name}__", _binary(_sym))


class Const(Expr):
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value

    def eval(self, env: Callable[[str], Any]) -> int:
        return self.value

    def refs(self) -> Iterator[str]:
        return iter(())

    def __repr__(self) -> str:
        return repr(self.value)


class Ref(Expr):
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def eval(self, env: Callable[[str], Any]) -> int:
        value = env(self.name)
        if not isinstance(value, int):
            raise BitError(f"field {self.name} is {value!r}, not an integer")
        return value

    def refs(self) -> Iterator[str]:
        yield self.name

    def __repr__(self) -> str:
        return self.name


class Binary(Expr):
    __slots__ = ("op", "left", "right")

    def __init__(self, op: str, left: Expr, right: Expr) -> None:
        self.op, self.left, self.right = op, left, right

    def eval(self, env: Callable[[str], Any]) -> int:
        left = self.left.eval(env)
        if self.op == "&" and left == 0:
            # 0 & x is 0 for every x: the right side is not evaluated, so a
            # condition can guard a field that is absent (None) when it fails.
            return 0
        return _BINARY[self.op](left, self.right.eval(env))

    def refs(self) -> Iterator[str]:
        yield from self.left.refs()
        yield from self.right.refs()

    def __repr__(self) -> str:
        return f"({self.left!r} {self.op} {self.right!r})"


class Popcount(Expr):
    __slots__ = ("arg",)

    def __init__(self, arg: Expr) -> None:
        self.arg = arg

    def eval(self, env: Callable[[str], Any]) -> int:
        value = self.arg.eval(env)
        if value < 0:
            raise BitError(f"popcount of negative value {value}")
        return value.bit_count()

    def refs(self) -> Iterator[str]:
        return self.arg.refs()

    def __repr__(self) -> str:
        return f"popcount({self.arg!r})"


class Lookup(Expr):
    __slots__ = ("arg", "table")

    def __init__(self, arg: Expr, table: dict[int, int]) -> None:
        self.arg, self.table = arg, table

    def eval(self, env: Callable[[str], Any]) -> int:
        key = self.arg.eval(env)
        try:
            return self.table[key]
        except KeyError:
            raise BitError(f"{self.arg!r} = {key} is not one of {sorted(self.table)}") from None

    def refs(self) -> Iterator[str]:
        return self.arg.refs()

    def __repr__(self) -> str:
        return f"{self.arg!r}.map({self.table!r})"


def popcount(value: Expr | int) -> Expr:
    """Number of set bits, typically of a mask that sizes a repeated row."""
    return Popcount(_lift(value))


class _Fields:
    """``F.name`` is a reference to the field ``name``."""

    __slots__ = ()

    def __getattr__(self, name: str) -> Ref:
        if name.startswith("__"):
            raise AttributeError(name)
        return Ref(name)


F = _Fields()


# --- kinds -------------------------------------------------------------------

class Kind:
    """One row's kind. Subclasses carry the width (or length) and the repeat rules."""

    __slots__ = ("tag", "count", "when")

    def __init__(self, tag: str | None, count: Expr | int | None, when: Expr | int | None) -> None:
        self.tag = tag   # the spec's identifier for the row (DF002, SF011), for documentation
        self.count = None if count is None else _lift(count)
        self.when = None if when is None else _lift(when)

    def size_exprs(self) -> list[Expr]:
        return []

    def _attrs(self) -> str:
        parts = [repr(e) for e in self.size_exprs()] + [repr(self.tag)] * (self.tag is not None)
        parts += [f"count={self.count!r}"] * (self.count is not None)
        parts += [f"when={self.when!r}"] * (self.when is not None)
        return ", ".join(parts)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._attrs()})"


class _Int(Kind):
    __slots__ = ("width",)
    reader: Callable[[BitReader, int], int]
    writer: Callable[[BitWriter, int, int], None]

    def __init__(self, width: Expr | int, tag: str | None = None, *,
                 count: Expr | int | None = None, when: Expr | int | None = None) -> None:
        super().__init__(tag, count, when)
        self.width = _lift(width)

    def size_exprs(self) -> list[Expr]:
        return [self.width]


class U(_Int):
    """Unsigned integer of ``width`` bits (0 to 64)."""
    __slots__ = ()
    reader = BitReader.uint
    writer = BitWriter.uint


class S(_Int):
    """Two's-complement integer of ``width`` bits (1 to 64)."""
    __slots__ = ()
    reader = BitReader.sint
    writer = BitWriter.sint


class SM(_Int):
    """Sign-magnitude integer of ``width`` bits (2 to 64)."""
    __slots__ = ()
    reader = BitReader.smag
    writer = BitWriter.smag


class Mask(_Int):
    """Unsigned bit mask of ``width`` bits, any width from 0 (``U`` stops at 64)."""
    __slots__ = ()
    reader = BitReader.mask
    writer = BitWriter.mask


class Octets(Kind):
    """``length`` whole bytes, kept as ``bytes``."""

    __slots__ = ("length",)

    def __init__(self, length: Expr | int, tag: str | None = None, *,
                 count: Expr | int | None = None, when: Expr | int | None = None) -> None:
        super().__init__(tag, count, when)
        self.length = _lift(length)

    def size_exprs(self) -> list[Expr]:
        return [self.length]


@dataclasses.dataclass(frozen=True, slots=True)
class Extension:
    """The bits a :class:`Rest` row found after a table: ``bits`` of them, MSB first, as ``value``.

    ``bits`` counts every bit to the end of the data, fill bits included, so
    that writing them back ends on the same byte boundary.
    """

    bits: int
    value: int

    def __post_init__(self) -> None:
        for name in ("bits", "value"):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool):
                raise TypeError(f"Extension.{name} must be an int, not {v!r}")
        if self.bits < 0 or not 0 <= self.value < (1 << self.bits):
            raise ValueError(f"Extension value {self.value} does not fit {self.bits} bits")

    @property
    def whole_bytes(self) -> int:
        """Whole bytes after the table's last byte (``bits // 8``)."""
        return self.bits // 8

    @property
    def fill(self) -> int:
        """The bits between the table's end and the next byte boundary (``bits % 8`` of them)."""
        return self.value >> (self.bits - self.bits % 8)


class Rest(Kind):
    """The rest of the data after a table, kept as an :class:`Extension` (or ``None``)."""

    __slots__ = ()

    def __init__(self, tag: str | None = None) -> None:
        super().__init__(tag, None, None)


class Group(Kind):
    """A nested message dataclass, read and written with its own table."""

    __slots__ = ("cls",)

    def __init__(self, cls: type, tag: str | None = None, *,
                 count: Expr | int | None = None, when: Expr | int | None = None) -> None:
        super().__init__(tag, count, when)
        if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
            raise TypeError(f"Group needs a dataclass, not {cls!r}")
        self.cls = cls

    def _attrs(self) -> str:
        rest = super()._attrs()
        return self.cls.__name__ + (", " + rest if rest else "")


# --- compiled layout ---------------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class Row:
    """One compiled row: the field name, its kind, and the nested layout of a group."""

    name: str
    kind: Kind
    group: Layout | None


class Layout:
    """The compiled table of one message dataclass. Get it with :func:`layout`."""

    __slots__ = ("cls", "rows", "fixed_bits", "params", "rest")

    def __init__(self, cls: type, rows: tuple[Row, ...], params: tuple[str, ...] = ()) -> None:
        self.cls = cls
        self.rows = rows
        self.params = params   # names the caller supplies (``PARAMS``), in declaration order
        # The table's width when it is constant, not counting a Rest row.
        self.fixed_bits = _fixed_bits(rows)
        # The name of the Rest row, if the table ends with one.
        self.rest = rows[-1].name if rows and isinstance(rows[-1].kind, Rest) else None

    def __repr__(self) -> str:
        return f"<Layout {self.cls.__qualname__}: {len(self.rows)} rows>"

    def _root(self, params: Mapping[str, int]) -> _Scope:
        if set(params) != set(self.params):
            raise TypeError(f"{self.cls.__qualname__} takes parameters {list(self.params)}, "
                            f"got {sorted(params)}")
        scope = _Scope(None)
        for name, value in params.items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"parameter {name} must be an int, not {value!r}")
            scope.values[name] = value
        return scope

    def read(self, reader: BitReader, params: Mapping[str, int] | None = None) -> Any:
        root = self._root(params or {})
        return self._read(reader, root, self.cls.__qualname__)

    def write(self, message: Any, writer: BitWriter,
              params: Mapping[str, int] | None = None) -> None:
        if type(message) is not self.cls:
            raise TypeError(f"expected {self.cls.__qualname__}, got {type(message).__qualname__}")
        root = self._root(params or {})
        self._write(message, writer, root, self.cls.__qualname__)

    def _read(self, r: BitReader, outer: _Scope, path: str) -> Any:
        scope = _Scope(outer)
        for row in self.rows:
            where = f"{path}.{row.name}"
            kind = row.kind
            with _located(where):
                if kind.when is not None and not kind.when.eval(scope.get):
                    value = None
                elif kind.count is None:
                    value = self._read_one(row, r, scope, where)
                else:
                    n = kind.count.eval(scope.get)
                    if n < 0:
                        raise BitError(f"count {n} is negative")
                    value = tuple(self._read_one(row, r, scope, f"{where}[{i}]") for i in range(n))
            scope.values[row.name] = value
        return self.cls(**scope.values)

    @staticmethod
    def _read_one(row: Row, r: BitReader, scope: _Scope, where: str) -> Any:
        kind = row.kind
        if isinstance(kind, _Int):
            return type(kind).reader(r, kind.width.eval(scope.get))
        if isinstance(kind, Octets):
            return r.octets(kind.length.eval(scope.get))
        if isinstance(kind, Rest):
            n, value = r.tail()
            return None if n < 8 and value == 0 else Extension(n, value)
        assert row.group is not None
        return row.group._read(r, scope, where)

    def _write(self, message: Any, w: BitWriter, outer: _Scope, path: str) -> None:
        scope = _Scope(outer)
        for row in self.rows:
            where = f"{path}.{row.name}"
            kind = row.kind
            value = getattr(message, row.name)
            with _located(where):
                if kind.when is not None and not kind.when.eval(scope.get):
                    if value is not None:
                        raise BitError(f"is {value!r} but its condition {kind.when!r} is false")
                elif kind.count is None:
                    self._write_one(row, value, w, scope, where)
                else:
                    n = kind.count.eval(scope.get)
                    if not isinstance(value, tuple) or len(value) != n:
                        raise BitError(f"needs a tuple of {n} items, got {value!r}")
                    for i, item in enumerate(value):
                        self._write_one(row, item, w, scope, f"{where}[{i}]")
            scope.values[row.name] = value

    @staticmethod
    def _write_one(row: Row, value: Any, w: BitWriter, scope: _Scope, where: str) -> None:
        kind = row.kind
        if isinstance(kind, _Int):
            if not isinstance(value, int) or isinstance(value, bool):
                raise BitError(f"needs an int, got {value!r}")
            type(kind).writer(w, value, kind.width.eval(scope.get))
        elif isinstance(kind, Octets):
            n = kind.length.eval(scope.get)
            if not isinstance(value, bytes) or len(value) != n:
                raise BitError(f"needs {n} bytes, got {value!r}")
            w.octets(value)
        elif isinstance(kind, Rest):
            if value is None:
                return
            if type(value) is not Extension:
                raise BitError(f"needs an Extension or None, got {value!r}")
            if value.bits < 8 and value.value == 0:
                raise BitError("fewer than eight zero bits are plain fill: None, not an Extension")
            if (w.pos + value.bits) % 8:
                raise BitError(f"{value.bits} bits after a table of {w.pos} bits do not end "
                               f"on a byte boundary")
            w.tail(value.value, value.bits)
        else:
            assert row.group is not None
            if type(value) is not row.group.cls:
                raise BitError(f"needs a {row.group.cls.__qualname__}, got {value!r}")
            row.group._write(value, w, scope, where)


class _Scope:
    """Field values read so far in one message, chained to the enclosing message's."""

    __slots__ = ("values", "outer")

    def __init__(self, outer: _Scope | None) -> None:
        self.values: dict[str, Any] = {}
        self.outer = outer

    def get(self, name: str) -> Any:
        scope: _Scope | None = self
        while scope is not None:
            if name in scope.values:
                return scope.values[name]
            scope = scope.outer
        raise BitError(f"no field {name} read before this one")


class _located:
    """Prefix the innermost BitError with the path of the row that raised it."""

    __slots__ = ("where",)

    def __init__(self, where: str) -> None:
        self.where = where

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: type | None, exc: BaseException | None, tb: object) -> bool:
        if isinstance(exc, BitError) and not getattr(exc, "located", False):
            exc.args = (f"{self.where}: {exc.args[0] if exc.args else ''}",) + exc.args[1:]
            exc.located = True  # type: ignore[attr-defined]
        return False


def _fixed_bits(rows: tuple[Row, ...]) -> int | None:
    total = 0
    for row in rows:
        kind = row.kind
        if isinstance(kind, Rest):
            continue
        if kind.when is not None or kind.count is not None:
            return None
        if isinstance(kind, _Int) and isinstance(kind.width, Const):
            total += kind.width.value
        elif isinstance(kind, Octets) and isinstance(kind.length, Const):
            total += kind.length.value * 8
        elif row.group is not None and row.group.fixed_bits is not None:
            total += row.group.fixed_bits
        else:
            return None
    return total


_LAYOUTS: dict[type, Layout] = {}


def _params(cls: type) -> tuple[str, ...]:
    params = getattr(cls, "PARAMS", ())
    if not (isinstance(params, tuple) and all(isinstance(p, str) for p in params)):
        raise TypeError(f"{cls.__qualname__}.PARAMS must be a tuple of names")
    clash = set(params) & {f.name for f in dataclasses.fields(cls)}
    if clash:
        raise TypeError(f"{cls.__qualname__}: {sorted(clash)} are both fields and parameters")
    return params


def _compile(cls: type, outer_names: frozenset[str], stack: tuple[type, ...]) -> Layout:
    if cls in stack:
        raise TypeError(f"{cls.__qualname__} contains itself")
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise TypeError(f"{cls!r} is not a dataclass")
    hints = typing.get_type_hints(cls, include_extras=True)
    rows = []
    seen: list[str] = []
    for f in dataclasses.fields(cls):
        if not f.init:
            raise TypeError(f"{cls.__qualname__}.{f.name}: every field must be an __init__ field")
        meta = [m for m in getattr(hints[f.name], "__metadata__", ()) if isinstance(m, Kind)]
        if len(meta) != 1:
            raise TypeError(f"{cls.__qualname__}.{f.name}: needs exactly one kind "
                            f"(U, S, SM, Octets, Group or Rest) in Annotated[...], "
                            f"found {len(meta)}")
        kind = meta[0]
        visible = outer_names | set(seen)
        exprs = kind.size_exprs() + [e for e in (kind.count, kind.when) if e is not None]
        for expr in exprs:
            for name in expr.refs():
                if name not in visible:
                    raise TypeError(f"{cls.__qualname__}.{f.name}: refers to {name}, "
                                    f"which is not a field read before it")
        if isinstance(kind, Rest) and (stack or f.name != dataclasses.fields(cls)[-1].name):
            raise TypeError(f"{cls.__qualname__}.{f.name}: Rest must be the last row of the "
                            f"outermost table")
        group = None
        if isinstance(kind, Group):
            group = _compile(kind.cls, frozenset(visible), stack + (cls,))
        rows.append(Row(f.name, kind, group))
        seen.append(f.name)
    return Layout(cls, tuple(rows))


def layout(cls: type) -> Layout:
    """The compiled, checked table of a message dataclass (cached per class).

    Names in a group's expressions are checked against the enclosing fields
    of this root, so compile the outermost message, not its groups alone.
    """
    try:
        return _LAYOUTS[cls]
    except KeyError:
        pass
    params = _params(cls)
    found = _compile(cls, frozenset(params), ())
    compiled = Layout(cls, found.rows, params)
    _LAYOUTS[cls] = compiled
    return compiled


def _refuse(cls: type, whole_bytes: int) -> None:
    if whole_bytes:
        raise BitError(f"{cls.__qualname__}: {whole_bytes} bytes left over")
    raise BitError(f"{cls.__qualname__}: fill bits are not zero")


def read(cls: type[T], reader: BitReader, **params: int) -> T:
    """Read one ``cls`` from the reader's position; ``params`` are its ``PARAMS``."""
    return layout(cls).read(reader, params)  # type: ignore[no-any-return]


def write(message: Any, writer: BitWriter, **params: int) -> None:
    """Append ``message`` to the writer; ``params`` are its ``PARAMS``."""
    layout(type(message)).write(message, writer, params)


def pack(message: Any, **params: int) -> bytes:
    """``message`` as bytes, the last byte filled with zero bits."""
    w = BitWriter()
    write(message, w, **params)
    return w.to_bytes()


def unpack(cls: type[T], data: bytes, *, strict: bool = False, **params: int) -> T:
    """Read one ``cls`` from the whole of ``data``; ``pack(unpack(cls, data)) == data``.

    A table without a :class:`Rest` row must fill ``data`` exactly, up to
    zero fill bits in the last byte. A table with one keeps whatever follows
    its other rows in that row; with ``strict`` set, it is refused instead
    unless it is plain zero fill (the row's value is ``None``).
    """
    r = BitReader(data)
    message = read(cls, r, **params)
    rest = layout(cls).rest
    if rest is not None:
        extension = getattr(message, rest)
        if strict and extension is not None:
            _refuse(cls, extension.whole_bytes)
        return message
    if r.remaining >= 8:
        _refuse(cls, r.remaining // 8)
    if r.uint(r.remaining):
        _refuse(cls, 0)
    return message
