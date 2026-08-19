# C++ features used in wcache, for a C programmer

**Not erasable.** This is a durable reference. It grows as later units introduce
new features; it is not overwritten like `EXPLAIN.md`.

Assumes you know C and general programming. Every claim here was checked against
`g++ 13.3.1` on this machine, and the compiler output shown is real output.

Right now it covers everything in `native/include/wcache/types.h`.

---

## 0. The one idea behind the whole file

C has `typedef`, which makes a **nickname**. C++ has templates, which let you
make a **new type**. The whole of `types.h` is one trick: turn six nicknames
into six genuinely different types, so the compiler can tell them apart, and pay
nothing at runtime for it.

Everything below is machinery in service of that.

---

## 1. Namespaces

```cpp
namespace wcache {
    class Tagged { ... };
}
```

A namespace is a named scope for symbols. C solves name collisions with prefixes
(`wcache_Tagged`); C++ gives you a real scope.

```cpp
wcache::SimTime t{5};      // fully qualified, always works
using namespace wcache;    // dump the whole namespace into scope
SimTime t{5};              // now this works unqualified
```

`::` is the scope operator, the equivalent of `.` but for scopes instead of
objects. `std::` is the standard library's namespace, which is why it is
`std::vector` and not `vector`.

**Convention worth following:** never write `using namespace` in a header. It
would force every file that includes the header to swallow the namespace. In
`.cpp` files and tests it is fine. `types.h` does not do it; the smoke tests do.

Namespaces nest, and `types.h` uses that for the tags:

```cpp
namespace wcache {
namespace tags { struct line; }
}
// referred to as wcache::tags::line
```

---

## 2. `#pragma once`

```cpp
#pragma once
```

Replaces the C idiom:

```c
#ifndef WCACHE_TYPES_H
#define WCACHE_TYPES_H
...
#endif
```

It tells the compiler "if you have already read this file, skip it". Strictly it
is not in the C++ standard, but every compiler that matters supports it, and it
cannot be defeated by two headers accidentally choosing the same guard macro.

Needed because C++ forbids defining the same class twice, and a header gets
included many times across a build.

---

## 3. `using X = Y;` makes a nickname, not a type

```cpp
using LineId = std::int64_t;    // C++ spelling
typedef std::int64_t LineId;    // C spelling, identical meaning
```

Both create an **alias**. `LineId` *is* `std::int64_t`, not a relative of it.
The compiler sees one type with two spellings:

```cpp
using SimTime   = std::int64_t;
using LocalTick = std::int64_t;

SimTime a = 5;
LocalTick b = 7;
if (a < b) { }        // compiles. They are the same type.
```

This is the thing N12 wants to prevent, and it is why an alias is not enough.

`types.h` still uses `using`, but pointed at a *template instantiation* rather
than at a built-in:

```cpp
using SimTime = Tagged<std::int64_t, tags::sim_time>;
```

`SimTime` is still just a nickname. But it is a nickname for something that is
genuinely its own type, because of section 5.

---

## 4. `class`, access control, and constructors

```cpp
class Tagged {
public:
    constexpr explicit Tagged(Rep v) : v_(v) {}
    constexpr Rep get() const { return v_; }
private:
    Rep v_;
};
```

A `class` is a C `struct` plus three things: access control, member functions,
and constructors.

### Access control

`public:` and `private:` are labels; everything after one has that access until
the next label. `private` members are reachable only from inside the class's own
functions. `class` defaults to private, `struct` defaults to public; that is the
*only* difference between the two keywords in C++.

Here `v_` is private, so the only way to read it is `get()`, and the only way to
set it is the constructor. That is what makes it impossible to sneak a raw
integer in.

The trailing underscore in `v_` is a convention marking a member, nothing more.

### Member functions

`get()` is a function that belongs to the class. Calling it is `t.get()`.
Inside, `v_` means "this object's `v_`".

### Constructors

A function with the class's name and no return type. It runs when an object is
created.

```cpp
constexpr explicit Tagged(Rep v) : v_(v) {}
                                  ^^^^^^^  member initializer list
```

The part after `:` is the **member initializer list**. It initializes members
*before* the body runs. The alternative,

```cpp
Tagged(Rep v) { v_ = v; }      // default-construct v_, then assign to it
```

does two steps instead of one, and does not work at all for `const` members or
references, which must be initialized rather than assigned. Use the initializer
list by default. The body `{}` is empty because there is nothing left to do.

### `const` member functions

```cpp
constexpr Rep get() const { return v_; }
                    ^^^^^
```

The `const` after the parameter list is a promise that this function does not
modify the object. It also means you can call it on a `const` object:

```cpp
const SimTime t{5};
t.get();          // ok, get() is const
```

If `get()` were not marked `const`, that line would not compile. Mark every
member function that does not mutate as `const`. It costs nothing and the
compiler enforces it.

---

## 5. Templates

This is the feature you asked about, so here it is at length.

### The idea

A template is **a recipe for making types (or functions), with the types left as
blanks**. It is not a type itself. The compiler fills the blanks in and
generates real code, at compile time.

```cpp
template <typename Rep, typename Tag>
class Tagged { ... };
```

reads as: "here is a recipe called `Tagged`. It has two blanks, and I will call
them `Rep` and `Tag`. Both blanks take a **type**."

`typename` is what says "this blank is filled by a type" as opposed to a value.
(`class` can be written instead of `typename` in this position and means exactly
the same thing. Two spellings, no difference. `typename` is clearer.)

You cannot use `Tagged` on its own. You use it filled in:

```cpp
Tagged<std::int64_t, tags::sim_time>       // Rep = int64_t, Tag = tags::sim_time
Tagged<std::int64_t, tags::local_tick>     // Rep = int64_t, Tag = tags::local_tick
```

### How to read the file: default-deny, not a blacklist

Before the mechanics, the shape of the design.

Nothing in `types.h` forbids anything. There is no list of illegal combinations,
and searching for one finds nothing. What the file contains is **ten operator
declarations**, and those are the complete set of operations that work. Every
other combination is refused by not being mentioned: a type with no conversions
and no matching operator has nothing to fall back on.

The permission matrix, generated from the code by compile-time detection rather
than read off by hand:

```
  left < right      Line Core Slot  Sim Loc  Ref
LineId          Y   .   .   .   .   .
CoreId          .   Y   .   .   .   .
SlotId          .   .   Y   .   .   .
SimTime         .   .   .   Y   .   .
LocalTick       .   .   .   .   Y   .
RefusalOrder    .   .   .   .   .   Y

  left + right      Line Core Slot  Sim Loc  Ref
LineId          .   .   .   .   .   .
CoreId          .   .   .   .   .   .
SlotId          .   .   .   .   .   .
SimTime         .   .   .   Y   Y   .     <- the one deliberate crossing
LocalTick       .   .   .   .   Y   .
RefusalOrder    .   .   .   .   .   .
```

Seventy-two cells, nine of them open. Note that `SimTime + LocalTick` is
**allowed**: it is Part 5's `tile_origin[tile(c)] + local_tick(c, cursor)`, the
one place trace time legitimately enters simulated time. Comparison, by
contrast, is diagonal-only with no exceptions.

The same wall stands outside operators, at arguments and assignment:

```
COMPILES  probe(LineId{7})                     legal call
rejected  probe(SlotId{7})                     wrong type passed
rejected  SimTime a{1}; a = LocalTick{2};      assignment
COMPILES  SimTime a{1}; a = SimTime{2};        assignment
```

**Why the inversion matters.** A blacklist would need 63 entries here, and every
forgotten one is a silent hole. It also does not scale: A4 owes a seventh type,
`SetIndex`, which grows each table from 36 cells to 49. A blacklist would need
13 new entries per table, thought of and remembered by a person. Default-deny
needs one line:

```cpp
using SetIndex = Tagged<std::int32_t, tags::set_index>;
```

and all 13 new cells refuse automatically. The only remaining work is deciding
which, if any, deserve a door.

`explicit` and the absence of any conversion out of `Tagged` are what hold the
floor at zero. The ten declarations are the doors.

### Why a template at all

Worth separating two questions, because the answers differ.

**Why six distinct types?** That is plan decision N12, a requirement.

**Why a template to build them?** Deduplication only. Six hand-written classes
would give exactly the same type safety. The template buys one thing.

Four ways to satisfy N12, all four built and measured:

| | Distinct? | Blocks cross-type `<`? | Blocks implicit `int`? | Catches uninitialised? | Arithmetic reads well? | Size |
|---|---|---|---|---|---|---|
| raw `int64_t` | no | no | no | no | yes | 0 |
| `using X = int64_t` | **no** | no | no | no | yes | 6 |
| six hand-written classes | yes | yes | yes | always | yes | ~96, six near-copies |
| `enum class X : int64_t {}` | yes | yes | yes | **warning, best-effort** | **no** | 3 |
| `Tagged` template | yes | yes | yes | always | yes | 55, one copy |

Every row was built and compiled; the failures below are real output, not
predictions.

#### Against `enum class`, the strongest competitor

It needs no template at all, so it deserved a fair test. Two findings.

**1. Uninitialised values are caught by flow analysis, which has holes.** gcc
does warn on the simple cases (`SimTime t; return t;` warns under plain
`-Wall`). But flow analysis is best-effort. A constructor that initialises two
of three members produces **no diagnostic at all** at `-O2` with
`-Wall -Wextra -Wpedantic -Wuninitialized -Wmaybe-uninitialized`:

```cpp
struct CoreState {
    int     cursor;
    int     tile;
    SimTime ready_time;                       // forgotten below
    CoreState(int c, int t) : cursor(c), tile(t) {}
};
// enum class: compiles clean, reads an indeterminate value
// Tagged:     error: use of deleted function 'Tagged<..., tags::sim_time>::Tagged()'
```

Plan 3.3's `Request`, `Mshr`, and `CoreState` are all this shape. The
distinction is a warning that usually fires versus a type rule that always
fires.

**2. It supports no arithmetic, so every legal use needs a cast, and the cast
re-admits N12's bug.** Part 5's expression, correct and buggy, spelled
identically:

```cpp
SimTime issue_time_correct(SimTime origin, LocalTick    offset) {
    return SimTime{ I64(origin) + I64(offset) };
}
SimTime issue_time_bug(SimTime origin, RefusalOrder stamp) {
    return SimTime{ I64(origin) + I64(stamp) };     // a counter added to a clock
}
```

Under `enum class` both compile silently at `-Wall -Wextra -Wpedantic
-Wconversion -Wsign-conversion` and both print 1217. Under `Tagged` the first
compiles and the second is `error: no match for 'operator+' (operand types are
'SimTime' and 'RefusalOrder')`, naming the function.

Once casting is routine, a cast stops marking anything, and one around an
illegal mix is indistinguishable from the hundreds around legal ones. `Tagged`
inverts that: legal operations need no cast, illegal ones have no spelling.

#### Against six hand-written classes

Narrower, but concrete: six copies give a typo six independent places to live.

```cpp
constexpr bool operator<=(LocalTick a, LocalTick b) { return a.get() < b.get(); }
//                                                                  ^ should be <=
```

Compiled with the project's full warning set this produces **zero warnings**, and
a thorough `SimTime` suite reports `5 passed, 0 failed`, because `SimTime` is
fine. Only `LocalTick{5} <= LocalTick{5}` is wrong, and it returns `false`.

Where that bites: A3 validates a burst's local tick against its tile with
`tick <= tile_last_tick`, so the typo silently drops the last tick of every
tile. That is N11's failure mode arriving by a route N11 does not cover.

It also multiplies the plan's own lesson. Part 7 records that "125 passing
checks hid 6 live mutations". Six copies of an operator are six independent
places for a mutation to survive, and six times the mutation-testing burden. One
definition is right for all six types or wrong for all six, and one test settles
it. The line count (55 versus 96) is the secondary point.

### `Tagged` is the template. There is no class behind it.

Read these two lines as **one** declaration, not two:

```cpp
template <typename Rep, typename Tag>     // the parameter list
class Tagged { ... };                     // the thing being declared
```

It does not declare a class `Tagged` and separately a template. It declares a
single entity, a **class template**, whose name is `Tagged`. So `Tagged` on its
own is not a type and you cannot make one:

```
$ Tagged x{5};
error: class template argument deduction failed
error: no matching function for call to 'Tagged(int)'

$ sizeof(Tagged)
error: missing template arguments before ')' token
```

Three levels, three words, worth keeping straight:

| | Example | A type? | What it is |
|---|---|---|---|
| class template | `Tagged` | **no** | the recipe; generates nothing on its own |
| instantiation | `Tagged<long, tags::sim_time>` | yes | a class the compiler generated by filling the blanks |
| alias | `SimTime` | yes, the same one | a nickname for that instantiation |

`SimTime` introduces no new type, only a shorter spelling:

```cpp
static_assert(std::is_same<SimTime, Tagged<long, tags::sim_time>>::value);   // passes
static_assert(!std::is_same<SimTime, LocalTick>::value);                     // passes
```

`types.h` therefore contains **one** template and **six** types.

Note what the first error above was really saying. C++17 tries to deduce class
template arguments from the constructor. It gets `Rep = int` and then stops,
because `Tag` appears nowhere in the constructor's parameters and so cannot be
deduced from anything. That is deliberate: a tag is a label you choose, never a
consequence of the data. It is also why the six aliases exist, so nobody has to
write the tag out by hand.

### Eight `template` lines, eight separate templates

`template <typename Rep, typename Tag>` appears eight times in `types.h`: once
for the class, once for each of the six comparison operators, and once for the
`std::hash` specialization. These are eight independent templates that happen to
name their blanks the same way. The operators are **not** members of `Tagged`
and do not inherit its parameters:

```cpp
template <typename Rep, typename Tag>                          // template #1
class Tagged { ... };

template <typename Rep, typename Tag>                          // template #2, unrelated
constexpr bool operator<(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b);
```

In template #2, `Tagged<Rep, Tag>` is a **pattern matched against an argument's
type**, not a use of template #1's parameters. Section 10 depends entirely on
that reading. A `template <...>` line always attaches to the single declaration
that immediately follows it, and to nothing else.

### The injected class name

Inside a class template's body, the bare name means the current instantiation:

```cpp
template <typename Rep, typename Tag>
class Demo {
    Demo twice() const { return Demo(v_ * 2); }   // both `Demo` mean Demo<Rep,Tag>
};
```

Verified: `decltype(Demo<int,tagA>{1}.twice())` is `Demo<int,tagA>`. This is why
`Tagged`'s constructor is written `Tagged(Rep v)` rather than
`Tagged<Rep,Tag>(Rep v)`. Outside the body there is no such shorthand and the
arguments must be written.

### Instantiation

When the compiler first sees `Tagged<std::int64_t, tags::sim_time>`, it
**instantiates** the template: it copies the recipe, substitutes
`Rep = std::int64_t` and `Tag = tags::sim_time` throughout, and compiles the
result as an ordinary class. Roughly as if you had written by hand:

```cpp
class Tagged__int64__sim_time {
public:
    constexpr explicit Tagged__int64__sim_time(std::int64_t v) : v_(v) {}
    constexpr std::int64_t get() const { return v_; }
private:
    std::int64_t v_;
};
```

It does this once per distinct set of arguments. Six aliases in `types.h`
produce six classes.

**And here is the whole point:** those six classes are *unrelated*. Two
instantiations of the same template with different arguments are as different
from each other as `int` and `std::string`. There is no inheritance between
them, no conversion, nothing. `Tagged<int64_t, sim_time>` and
`Tagged<int64_t, local_tick>` have identical layout and identical behaviour, and
the compiler still refuses to mix them.

That is the entire mechanism N12 asked for.

### Templates live in headers

A template is not compiled until it is instantiated, and instantiation happens
wherever it is used. So the compiler needs the full body in view at every use
site. That is why `types.h` is header-only with no `.cpp`: there is nothing to
put in one. This is normal for template code and is why C++ headers are so much
fatter than C headers.

---

## 6. Tags, and types that are never defined

```cpp
namespace tags {
struct line;
struct core;
struct sim_time;
}
```

Look closely: there is no `{ }` and no members. These are **declarations without
definitions**, which C++ calls **incomplete types**. The equivalent in C is
`struct foo;` with the definition somewhere else, except here there is no
somewhere else.

An incomplete type:

- has a name, so it can fill a template blank
- has no size, so you cannot make one, put one in a struct, or take
  `sizeof` of it
- generates no code whatsoever

That is exactly what a tag needs. Its only job is to be a distinct name so that
`Tagged<int64_t, tags::sim_time>` differs from `Tagged<int64_t, tags::core>`.
Using `struct sim_time {};` with a body would also work and would cost nothing
in practice, but leaving it incomplete makes it impossible to misuse: nobody can
accidentally create a `tags::sim_time` object, because there is no such thing.

---

## 7. `explicit`

```cpp
constexpr explicit Tagged(Rep v) : v_(v) {}
```

By default, a one-argument constructor doubles as an **implicit conversion**.
Without `explicit`, this would compile:

```cpp
SimTime t = 5;          // int silently becomes SimTime
void f(SimTime);
f(5);                   // and here too
```

`explicit` switches that off. The conversion must be asked for by name:

```cpp
SimTime t{5};           // ok, direct initialization with braces
SimTime t(5);           // ok, direct initialization with parens
SimTime t = 5;          // rejected
f(5);                   // rejected
f(SimTime{5});          // ok
```

Real message from this compiler:

```
error: conversion from 'int' to non-scalar type 'wcache::SimTime'
       {aka 'wcache::Tagged<long int, wcache::tags::sim_time>'} requested
    3 | SimTime t = 5;
      |             ^
```

Why it matters here: without `explicit`, every raw integer in the codebase could
silently become any of the six types, and the entire exercise is pointless. With
it, every crossing between raw integers and model types has to be typed out, so
`grep` finds them all.

Note the asymmetry. `explicit` blocks integer-to-`SimTime`. Nothing at all
allows `SimTime`-to-integer, because a conversion out would have to be written
as a conversion operator and `types.h` does not define one. `get()` is the only
exit.

---

## 8. `= delete`

```cpp
Tagged() = delete;
```

`Tagged()` with no arguments is the **default constructor**, the one that runs
for `SlotId s;`. C++ normally writes one for you automatically. `= delete` says
"this function exists, and using it is an error".

```
error: use of deleted function
       'wcache::Tagged<Rep, Tag>::Tagged() [with Rep = int; Tag = wcache::tags::slot]'
    3 | SlotId s;
      |        ^
note: declared here
   27 |     Tagged() = delete;
```

Note what the message tells you: the exact instantiation (`Tag = tags::slot`)
and the line that deleted it. Compare the older C++ idiom of making the function
private, which produced a confusing "is private" error from a random call site.
`= delete` is the modern way and gives the better diagnostic.

`= delete` works on any function, and the counterpart `= default` asks for the
compiler-generated version explicitly.

Consequence you will hit: `std::vector<SlotId> v(4);` does not compile, because
that constructor default-constructs four elements. `std::vector<SlotId> v(4, NoSlot);`
does. That is the intended friction.

---

## 9. Operator overloading

```cpp
constexpr bool operator<(Tagged<Rep,Tag> a, Tagged<Rep,Tag> b) { return a.get() < b.get(); }
```

C++ lets you define what the built-in operators mean for your own types.
`operator<` is a function with a funny name; `a < b` is compiled as
`operator<(a, b)`.

You cannot overload operators for built-in types only (`int < int` stays what it
is), and you cannot invent new operators. You can only give meaning to existing
ones for your own types.

### Member or free function

Both are allowed:

```cpp
class Tagged {
    bool operator<(Tagged other) const { ... }     // member: left operand is `this`
};
bool operator<(Tagged a, Tagged b) { ... }         // free: both operands are parameters
```

`types.h` uses free functions. For symmetric binary operators that is the usual
convention, because it treats both operands the same way. It also keeps the
class body down to the three things that need access to `v_`.

`operator+=` is also free here:

```cpp
constexpr SimTime& operator+=(SimTime& a, SimTime b) { a = a + b; return a; }
```

The `&` on the first parameter is a **reference**: `a` is not a copy, it is
another name for the caller's object, so assigning to it modifies the caller's
variable. It is C's `SimTime *a` with the pointer syntax removed and null ruled
out. The return type `SimTime&` returns a reference so that `(x += y) += z`
works, which is how the built-in `+=` behaves.

### Pass by value here

The parameters are `Tagged<Rep,Tag> a`, by value, not `const Tagged<Rep,Tag>& a`.
For a class wrapping one 8-byte integer, a copy is cheaper than a reference, since
a reference is a pointer that may then need dereferencing. Rule of thumb: pass
small trivially-copyable things by value, large or non-copyable things by
`const&`.

---

## 10. Template argument deduction, the load-bearing part

This is the mechanism that makes the whole scheme work, so it gets its own
section.

For a **function** template, you do not have to spell out the arguments. The
compiler works them out from the call:

```cpp
template <typename Rep, typename Tag>
constexpr bool operator<(Tagged<Rep, Tag> a, Tagged<Rep, Tag> b);

SimTime{1} < SimTime{2}
```

The compiler matches the parameter *pattern* `Tagged<Rep, Tag>` against the
actual argument type `Tagged<long, tags::sim_time>`, and concludes
`Rep = long`, `Tag = tags::sim_time`. It does this for each parameter.

**Now the trick.** `Tag` appears in *both* parameters. So both arguments must
deduce it to the same thing. Feed it two different types:

```cpp
SimTime{1} < LocalTick{1}
```

- from the left:  `Tag = tags::sim_time`
- from the right: `Tag = tags::local_tick`

The two disagree. Deduction fails, this candidate is discarded, and since there
is no other candidate and neither type converts to anything, the whole
expression is an error:

```
error: no match for 'operator<' (operand types are
       'wcache::SimTime' {aka 'wcache::Tagged<long int, wcache::tags::sim_time>'} and
       'wcache::LocalTick' {aka 'wcache::Tagged<long int, wcache::tags::local_tick>'})
    3 | return SimTime{1} < LocalTick{1};
      |        ~~~~~~~~~~ ^ ~~~~~~~~~~~~
note: candidate: 'template<class Rep, class Tag>
      constexpr bool wcache::operator<(Tagged<Rep, Tag>, Tagged<Rep, Tag>)'
note:   template argument deduction/substitution failed:
```

The compiler even prints the candidate it tried and says why it did not fit. It
is a good error, and it is the one N12's exit criterion is asking for.

Contrast with the deliberate crossing, which is **not** a template:

```cpp
constexpr SimTime operator+(SimTime origin, LocalTick offset) {
    return SimTime{origin.get() + offset.get()};
}
```

Concrete types on both sides, no blanks, no deduction. It is one specific
overload for one specific pair, so exactly that pair works and nothing else
does. That is how you punch a single hole in the wall without weakening it
elsewhere.

---

## 11. `constexpr`

```cpp
constexpr Rep get() const { return v_; }
```

`constexpr` on a function means "this **may** be evaluated at compile time, if
its inputs are known at compile time". It does not force it. The same function
runs perfectly well at runtime with runtime values.

```cpp
static_assert(SimTime{5} + SimTime{3} == SimTime{8});   // computed at compile time
SimTime t = read_from_config() + SimTime{3};            // same operator+, at runtime
```

`constexpr` on a *variable* is stronger: it means the value **must** be a compile-time
constant.

```cpp
inline constexpr SlotId NoSlot{INT32_MAX};   // baked into the binary, not computed at startup
```

This is a better `#define`: it has a type, it obeys scope, it appears in the
debugger, and the compiler checks it.

Rough guide: put `constexpr` on small functions that could reasonably be
compile-time. It never makes things worse.

---

## 12. `inline` on a variable

```cpp
inline constexpr SlotId NoSlot{INT32_MAX};
```

Different meaning from `inline` on a function (which is about expanding calls).
On a variable, `inline` is C++17 and it means: **this header may be included by
many .cpp files, and all of them share one definition of this variable.**

Without it, every `.cpp` including `types.h` would define its own `NoSlot`, and
the linker would reject the duplicate symbols. The old workaround was `extern`
in the header plus one definition in a `.cpp`, or a function returning a
`static`. `inline` removes the need for both.

Rule: any variable defined in a header wants `inline`.

---

## 13. Template specialization, and `std::hash`

```cpp
namespace std {
template <typename Rep, typename Tag>
struct hash<wcache::Tagged<Rep, Tag>> {
    size_t operator()(wcache::Tagged<Rep, Tag> v) const noexcept {
        return hash<Rep>{}(v.get());
    }
};
}
```

Four things at once.

### Why it exists

`std::unordered_map<Key, Value>` needs to hash its keys. It does that by looking
up `std::hash<Key>`. The standard library ships `std::hash` for built-ins and
for `std::string`, and it has never heard of `LineId`. Without this block,
`std::unordered_map<LineId, Mshr>` from plan section 3.3 does not compile.

### Specialization

The general `std::hash<T>` template is declared by the standard library but left
undefined for unknown `T`. This block **specializes** it: "when `T` happens to
match the pattern `wcache::Tagged<Rep, Tag>`, here is the definition to use."

Because the specialization still has blanks (`Rep` and `Tag`) it is a **partial
specialization**, and one block covers all six types at once. A **full**
specialization would name one concrete type and have an empty `template <>`.

Reopening `namespace std` is normally forbidden. Specializing a standard
template for your own type is the documented exception, which is why this is
legal.

### `operator()`

The function-call operator. Defining it makes objects of the type callable like
functions:

```cpp
std::hash<long> h;
h(42);              // calls h.operator()(42)
std::hash<long>{}(42);   // make a temporary and call it, same thing in one line
```

`hash<Rep>{}(v.get())` therefore means: build a temporary hasher for the
underlying integer, hand it the unwrapped value, use its answer. The wrapper
adds no hashing of its own, which is right, since the tag carries no
information at runtime.

### `noexcept`

A promise that this function never throws an exception. The compiler enforces it
in the sense that an escaping exception terminates the program rather than
propagating. Standard containers check for it and can take faster paths when it
holds. Hash functions are expected to be `noexcept`, so it belongs here.

---

## 14. `static_assert`

```cpp
static_assert(SimTime{5} + LocalTick{3} == SimTime{8});
```

An assertion checked **at compile time**. If the condition is false the build
fails. Costs nothing at runtime because there is no runtime involved.

This is why `constexpr` matters: only a `constexpr` function can be called
inside a `static_assert`. The two features work as a pair.

Distinct from `assert()` from `<cassert>`, which is a runtime check and is
compiled out by `-DNDEBUG`. The plan cares about that difference: it says
config- and trace-derived checks must `throw` so they survive the `-DNDEBUG`
sweep build, while internal invariants may `assert`.

---

## 15. Does any of this cost anything?

No. Checked, not assumed.

```
sizeof SimTime = 8    sizeof int64 = 8
alignof        = 8    alignof      = 8
trivially_copyable = 1    standard_layout = 1
```

And the generated code, at `-O2`, for adding two `SimTime` versus adding two
raw `std::int64_t`:

```asm
_Z7wrappedN6wcache6TaggedIlNS_4tags8sim_timeEEES3_:    ; SimTime + SimTime
        leaq    (%rdi,%rsi), %rax
        ret

_Z3rawll:                                              ; int64 + int64
        leaq    (%rdi,%rsi), %rax
        ret
```

Byte-identical. The class, the tag, the constructor, and `get()` all vanish. The
types exist only during compilation.

### Reading that first symbol

`_Z7wrappedN6wcache6TaggedIlNS_4tags8sim_timeEEES3_` is a **mangled name**. C++
encodes parameter types into the linker symbol, because unlike C it allows
several functions to share a name. Decoded: `_Z` starts it, `7wrapped` is a
7-character name, then the parameter types, where `6wcache` and `6Tagged` are
length-prefixed names, `I...E` brackets template arguments, `l` is `long`, and
`S3_` back-references a type already spelled out.

You do not need to read these. `c++filt` does it:

```
$ echo '_Z7wrappedN6wcache6TaggedIlNS_4tags8sim_timeEEES3_' | c++filt
wrapped(wcache::Tagged<long, wcache::tags::sim_time>, wcache::Tagged<long, wcache::tags::sim_time>)
```

Worth knowing about because mangled names are what you see in linker errors and
in `perf` output.

---

## 16. Line-by-line index of `types.h`

| Line | Feature | Section |
|---|---|---|
| `#pragma once` | include guard | 2 |
| `namespace wcache {` | namespace | 1 |
| `template <typename Rep, typename Tag>` | class template, two type blanks | 5 |
| `class Tagged {` / `public:` / `private:` | class, access control | 4 |
| `using rep_type = Rep;` | alias, exported so other code can ask "what is inside" | 3 |
| `Tagged() = delete;` | deleted default constructor | 8 |
| `constexpr explicit Tagged(Rep v) : v_(v) {}` | constexpr, explicit, member init list | 4, 7, 11 |
| `constexpr Rep get() const` | const member function | 4 |
| `Rep v_;` | private member, type comes from the blank | 4 |
| `constexpr bool operator<(Tagged<Rep,Tag>, Tagged<Rep,Tag>)` | free operator, deduction | 9, 10 |
| `namespace tags { struct line; }` | incomplete type as a tag | 6 |
| `using LineId = Tagged<std::int64_t, tags::line>;` | alias to an instantiation | 3, 5 |
| `inline constexpr SlotId NoSlot{INT32_MAX};` | inline variable, constexpr variable | 11, 12 |
| `constexpr SimTime operator+(SimTime, LocalTick)` | non-template overload, the one crossing | 10 |
| `struct hash<wcache::Tagged<Rep,Tag>>` | partial specialization, operator(), noexcept | 13 |
| `enum class Axis : std::uint8_t` | scoped enum with a pinned underlying type | 18 |
| `struct Coord { std::int32_t kh, ...; };` | aggregate, brace initialisation | 18 |
| `switch (a) { case Axis::KH: ... } throw ...` | exhaustive switch, and why not `default:` | 18 |
| `constexpr Coord with_coord_on(Coord c, Axis, int32)` | by-value parameter as a working copy | 18 |

---

## 17. What is coming in later units

Listed so you know what to expect, not explained yet. Each gets a section here
when the unit that needs it lands.

| Feature | First needed by |
|---|---|
| ~~`std::vector`, `std::unordered_map` as class templates you *use* rather than write~~ | `std::vector` landed at A4b, as `slots_` in `set_associative.h`; it gets no section of its own, and the one wcache-specific consequence is in section 8. `std::unordered_map` landed at plan unit B3, as `entries_` in `mshr.h`: section 26 |
| ~~virtual functions and abstract base classes~~ | landed early, at A2a: section 19 |
| ~~`override`, `final`~~ | landed at A2b: section 20 |
| ~~`std::unique_ptr` and ownership~~ | landed at A5, as `make_policy`'s return type: section 25 |
| ~~exceptions: `throw` (section 18), custom exception types~~; `noexcept` revisited | `throw` types landed at A2b: section 20. `noexcept` still owed |
| ~~`std::priority_queue` and custom comparators, for the event queue~~ | landed at plan unit B2: section 26 |
| ~~`enum class` for the outcome and reason enums~~ | the reason enums landed at plan unit B3 (`WaitReason`, `Level`) and plan unit B2 added `EventClass` and `EventKind`, all four by section 18's mechanism with nothing new to explain. The **outcome** enum (3.4's five triage results) belongs to plan unit C1 and will add nothing either |
| move semantics, `&&`, `std::move` | C2 if it becomes hot |

---

## 18. `enum class`, `struct`, and exhaustive `switch` (unit A1b)

### `enum class Axis : std::uint8_t`

```cpp
enum class Axis : std::uint8_t { KH = 0, KW = 1, CIN = 2, COUT = 3 };
```

Three differences from C's `enum`, all of them the point:

| | C `enum` | C++ `enum class` |
|---|---|---|
| spelling | bare `KH`, dumped into the surrounding scope | `Axis::KH`, and only that |
| converts to `int` | yes, silently | no |
| underlying type | compiler's choice | pinned here to `uint8_t` |

The scoping matters because `KH`, `KW`, `CIN` are exactly the names a
surrounding file wants for its own locals. The no-conversion rule matters
because `coord_on(c, 2)` is then a compile error instead of a coordinate read
from whichever axis happens to be numbered 2 today.

Pinning the underlying type does one more job. `static_cast<Axis>(9)` is
**well-defined** precisely because 9 is representable in `uint8_t`; without the
`: std::uint8_t` the range of valid values is the enumerators' own range and
the cast is undefined behaviour. That is why `tests/mutation_check.sh` treats
removing it as a real mutation: the unknown-axis test would stop being legal to
write.

Section 5's table rejected `enum class` as the mechanism for the six *scalar*
types. That is not in tension with using it here. There it was proposed as a
way to get distinct arithmetic types, which it does badly. Here the thing being
modelled genuinely is a small closed set of names, which is what it is for.

### `struct` is `class` with a different default

```cpp
struct Coord { std::int32_t kh, kw, cin, cout; };
```

`struct` and `class` differ in exactly one respect: members are `public` by
default in a `struct`, `private` in a `class`. Everything else, member
functions, constructors, inheritance, is available to both. The convention
followed here is C's: `struct` for a bag of values with no invariant to
protect, `class` when there is state to keep consistent (`Tagged`).

Because `Coord` declares no constructor, it is an **aggregate**, and brace
initialisation fills the members in declaration order:

```cpp
const Coord c{1, 2, 64, 100};    // kh=1, kw=2, cin=64, cout=100
```

No constructor to write, and none to forget to update when a field is added.
The cost is that field order is now part of the interface, which is why the
tests pin it.

`Coord` and `WeightShape` are both four `int32`s and are still two types. In C
they would be one `struct` used for two purposes, and `extent_on(coord, axis)`
would compile. Here it does not, and `tests/compile_fail.sh` holds that.

### The `throw` after an exhaustive `switch`

```cpp
constexpr std::int32_t coord_on(const Coord& c, Axis a) {
    switch (a) {
        case Axis::KH:   return c.kh;
        /* ... */
        case Axis::COUT: return c.cout;
    }
    throw std::logic_error("coord_on: unknown Axis");
}
```

The `switch` covers every enumerator, so a compiler checking exhaustiveness is
satisfied and warns nothing. It cannot conclude that the function returns,
though, because the argument's *type* admits values no enumerator names (see
the cast above), so without a trailing statement `-Wall` reports "control
reaches end of non-void function".

Two ways to silence it. `default: return 0;` is the tempting one and is wrong:
it invents an answer, and A2 reads burst anchors through this function, so the
invented answer becomes a well-formed, wrong line id. `throw` refuses instead.

`throw` rather than `assert` because the sweep build is `-DNDEBUG` and compiles
asserts out; anything that must survive the release build throws. And a `throw`
on an untaken branch is allowed inside a `constexpr` function, so the geometry
still evaluates at compile time when its inputs are constants.

---

## 19. Abstract base classes and virtual functions (unit A2a)

```cpp
class AddressMapper {
public:
    virtual ~AddressMapper() = default;
    virtual void expand(const Burst& b, std::vector<LineId>& out) const = 0;
};
```

In C this is a struct of function pointers that every implementation fills in
by hand. C++ writes the table for you.

- **`virtual`** on a member function means the call is resolved from the
  object's dynamic type, not from the static type of the pointer. `mapper.expand(...)`
  through an `AddressMapper&` runs `BlockPackMapper::expand` when that is what
  the reference refers to.
- **`= 0`** makes it *pure*: no body here, and the class cannot be
  instantiated. `AddressMapper m;` is a compile error naming the unimplemented
  function. A derived class that leaves one unimplemented is abstract too, and
  fails at its own first instantiation rather than at link time.
- **`virtual ~AddressMapper() = default;`** is not decoration. Deleting a
  derived object through a base pointer with a non-virtual destructor is
  undefined behaviour, and the usual symptom is a leak rather than a crash.
  The rule: any class meant to be inherited from and held by base pointer gets
  a virtual destructor. `= default` asks the compiler for the ordinary
  member-wise one.
- **`const`** on the pure virtual is part of the contract, not a hint: an
  override may not drop it, so no implementation can mutate the mapper while
  answering a query. Mapper state is fixed at construction.

The cost is one indirect call per `expand`, which is per burst rather than per
line, against a function that then appends several line ids. Not measurable
here, and it is what makes a layout a swept parameter: a differently nested
tensor is a new subclass, and nothing that holds an `AddressMapper` changes.

`override` and `final`, which the concrete mapper uses, arrive with A2b.

---

## 20. One header, one `.cpp` (unit A2b)

This is the first unit in the tree that is not header-only, so three things
arrive at once: the translation-unit split, `override` and `final`, and the
standard exception types.

### The split, and what a `.cpp` actually is

C's model, unchanged in C++: a **translation unit** is one `.cpp` after the
preprocessor has pasted in every `#include`. The compiler sees one at a time
and produces one `.o`. The linker glues them.

```
include/wcache/block_pack.h   declares BlockPackMapper           (the promise)
src/block_pack.cpp            defines its constructor and friends (the delivery)
build/fixture/block_pack.o    what the compiler made of the .cpp
build/fixture/libwcache.a     an archive holding that .o
```

A test binary `#include`s the header, so it knows the class exists, its size,
its layout, and the signature of every member. It does **not** know what the
constructor does. The linker supplies that from `libwcache.a`.

This is the same discipline as C's `.h` / `.c`. The one C++ wrinkle worth
knowing is that the boundary is *not* free to move for everything. Templates
must stay in headers (section 5, "Templates live in headers"), because the
compiler cannot generate `Tagged<int64_t, tags::line>` in a translation unit
that has never seen the template body. Ordinary classes have no such
constraint, which is why A1 could be header-only and A2b did not have to be.

### Why this class is not header-only

`Tagged`, `Coord` and `Axis` are header-only because they had to be (templates,
`constexpr`) or because they are three lines. `BlockPackMapper` is neither. Two
reasons to move its body out:

- **One definition of the invariant.** The constructor is the only place the
  layout's rules are established. With the body in the header, every
  translation unit compiles its own copy, and a unit compiled with a different
  `-D` or a different include order can end up with a subtly different
  constructor than the one the library was built with. That is not a warning;
  it is an ODR violation and the linker is allowed to pick either. With the
  body in one `.cpp` there is one machine-code constructor and the question
  cannot be asked.
- **Rebuild cost.** Everything that touches the layout includes this header.
  Editing a message string in the constructor should recompile one file, not
  every test binary.

The two overrides that *did* stay in the header, `num_lines()` and
`line_size_bytes()`, are one-liners returning a member. There is no invariant in
`return num_lines_;` for two copies to disagree about.

Note the Makefile consequence, which is real and was written down before this
unit existed: `$(OBJS)` was empty while every unit was header-only, so `$(LIB)`
never changed, and a mutated `include/wcache/*.h` left the previous test binary
in place. That is why `LIB_HDRS` is listed explicitly. `$(LIB)` now genuinely
changes, but the explicit list is still what covers a header a `.o` does not
happen to depend on.

### `override`

```cpp
void expand(const Burst& b, std::vector<LineId>& out) const override;
```

`override` says: this function is meant to replace a `virtual` one in a base
class, and it is a compile error if it does not. It changes no behaviour; it
changes what happens when you get the signature wrong.

Without it, a near miss is not an error, it is a **new, unrelated function**,
and the class quietly stays abstract:

```cpp
void expand(const Burst& b, std::vector<LineId>& out);        // dropped const
Placement locate(LineId line, int num_sets) const;            // int, not int64_t
```

Neither of those overrides anything. The first is the one that bites, because
`const` on the pure virtual is part of A2a's contract (section 19) and dropping
it would let an implementation mutate the mapper while answering a query. What
you would see is a compile error at the first attempt to construct the class,
naming the *base's* function as unimplemented, which points at the wrong file.
With `override` the error lands on the declaration that is actually wrong.

`tests/compile_fail.sh` already holds the negative case for the dropped
`const`, so this is checked rather than believed.

### `final`

```cpp
class BlockPackMapper final : public AddressMapper { ... };
```

`final` on a class forbids deriving from it. (It can also go on a single
virtual function, meaning "no further override of this one".)

It is a design statement, not an optimisation, though a compiler may
de-virtualise calls through a `BlockPackMapper&` because it knows there is no
subclass. The statement is board decision B10: a differently *nested* memory
layout is a new `AddressMapper` subclass, not a variant of this one. A class
deriving from `BlockPackMapper` would be inheriting the block-packed flatten in
order to disagree with part of it, which is exactly the arrangement that makes
a bug in one override invisible in the others.

C has no equivalent because C has no inheritance to forbid.

### The standard exception types, and picking between them

Section 18 introduced `throw` at the unreachable end of an exhaustive `switch`.
This unit throws on purpose, on the ordinary path, and the *type* carries
meaning. All three live in `<stdexcept>`:

| Type | Means | Used here for |
|---|---|---|
| `std::invalid_argument` | the caller passed a bad value | `cin_block = 0`, a negative extent, a product that overflows |
| `std::out_of_range` | a value is outside a valid range | reserved for A2d: a burst coordinate outside the tensor |
| `std::logic_error` | a bug in the program, not in the input | the A2d stubs: nothing is wrong with the argument, the function should not have been called |

`invalid_argument` and `out_of_range` both derive from `logic_error`, which
derives from `std::exception`. That hierarchy is why order matters in a
`try`/`catch` chain: `catch (const std::logic_error&)` written first would
swallow both of the others. `tests/check.h`'s `CHECK_THROWS` takes the type as
a parameter for exactly this reason, so a test can say which one it expects
rather than only that something was thrown.

All three are constructed from a `std::string` or a `const char*`, and
`what()` returns it:

```cpp
throw std::invalid_argument("BlockPackMapper: cin_block must be >= 1, got " +
                            std::to_string(v));
```

`std::to_string` is `<string>`'s overload set for the built-in numeric types.
It is the reason messages here print the offending value instead of only
asserting the rule, which is what N11 asks for.

### `[[noreturn]]`

```cpp
[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("BlockPackMapper: " + what);
}
```

An **attribute**, in the C++11 double-bracket syntax (C23 has the same thing).
It promises that control never comes back out of this function. Two effects,
both about diagnostics rather than speed:

- a caller that ends with `reject(...)` does not draw "control reaches end of
  non-void function", because the compiler knows it does not;
- if the function ever gained a path that *did* return, that is a warning here
  rather than undefined behaviour at every call site.

It is the same reasoning as the `throw` after the exhaustive `switch` in
section 18: refuse rather than invent an answer.

### Unnamed parameters

```cpp
// header
void expand(const Burst& b, std::vector<LineId>& out) const override;

// .cpp
void BlockPackMapper::expand(const Burst&, std::vector<LineId>&) const {
    throw std::logic_error("... increment A2d");
}
```

A parameter with a type and no name is legal and unusable, which is the point:
it is how C++ spells "this argument is deliberately ignored". `-Wextra` turns
on `-Wunused-parameter`, so leaving the names in would warn, and the two usual
workarounds are worse. `(void)b;` is noise that a reader has to decide is
deliberate, and `#pragma` disables the warning for a region rather than for one
argument.

The names stay in the header declaration, since that is where a caller reads
them. Only the definition drops them. C allows the same thing since C23; in
older C the idiom is the `(void)b;` cast.

### `static_assert` on the enumerator values

Already covered in section 14, but this file uses it for something section 14
did not: enforcing a cross-file ordering obligation.

```cpp
static_assert(static_cast<int>(Axis::CIN) == 2, "Axis order feeds the flatten");
```

`Axis`'s declaration order in `types.h` is the row-major nesting order that
this file's radices assume. Nothing about the two files makes a compiler notice
if one is reordered and the other is not, and the result would be plausible,
wrong line ids rather than a crash. The `static_assert` costs nothing at
runtime and turns the mismatch into a build failure in the file that would have
been wrong. Note it can only check the *numbering*, not the expression that
depends on it; it catches the specific accident, not the general class.

### Where the members are initialised

```cpp
class BlockPackMapper final : public AddressMapper {
    // ...
    std::int64_t n_cin_blocks_ = 0;   // default member initialiser
};

BlockPackMapper::BlockPackMapper(WeightShape shape, /* ... */)
    : shape_(shape), cin_block_(cin_block), /* ... */ {   // initialiser list
    // validation, then the derived members are assigned here
}
```

Two mechanisms, and the choice between them is load-bearing here.

The **initialiser list** (everything after the `:` and before the `{`) runs
before the constructor's body. Members are initialised in **declaration order**,
not in the order you list them, and `-Wall` warns if the two disagree. This is
where a member with no default constructor *must* be given its value, since
there is nothing to assign over.

The **body** is ordinary code, and anything set there is an assignment to an
already-initialised member.

`num_lines_` is a plain `std::int64_t` and not a `LineId` for exactly this
reason. `Tagged` deletes its default constructor (decision B2), so a `LineId`
member would have to be initialised in the list, which runs *before* the
validation in the body. Storing the `int64` and wrapping it at the accessor
keeps the order "check, then derive" instead of "derive, then check". The
default member initialisers (`= 0`) mean a constructor that throws part way
leaves no member holding an indeterminate value.

---

## 21. Indexing an array by an `enum class`, and why a delta is not a tagged type (unit A2c)

Two small things, both of which the flatten forced and neither of which is in
section 18 or section 6.

### `enum class` as an array index

`BlockPackMapper` stores its four line strides as one array and looks them up by
axis:

```cpp
std::int64_t stride_[4] = {0, 0, 0, 0};      // indexed by static_cast<int>(Axis)

stride_[static_cast<int>(Axis::COUT)] = 1;
```

In C this is the ordinary idiom and needs no cast, because a C `enum` constant
is already an `int`. Section 18's table records the C++ difference: `enum class`
does **not** convert to `int`, so the cast is mandatory. That is usually
described as pure friction. Here it is the useful half, because it makes every
site that treats an axis as a number visible to `grep`, and there are exactly
five of them, all in one file.

What the cast does not do is make the index safe. Three separate facts have to
line up, and C++ checks none of them for you:

1. **The array is not bounds checked.** A raw array subscript out of range is
   undefined behaviour, silently. `std::array` would not help: its `operator[]`
   is unchecked too, and only `.at()` throws.
2. **The enumerator values must match the slots.** Nothing ties `Axis::CIN == 2`
   to "slot 2 holds the CIN stride". This is what the four `static_assert`s at
   the top of `block_pack.cpp` buy, and it is section 14's cross-file ordering
   guard used for a second purpose: reordering `types.h` now breaks the build in
   the file whose array would otherwise be silently permuted.
3. **The parameter's type admits values no enumerator names.** Section 18
   already explains why: `Axis` pins its underlying type to `uint8_t`, so
   `static_cast<Axis>(9)` is well defined, and `stride_[9]` is then a read past
   the end of the object.

Point 3 is why the accessor is a `switch` and not a one line index:

```cpp
std::int64_t BlockPackMapper::line_stride(Axis a) const {
    switch (a) {
        case Axis::KH:
        case Axis::KW:
        case Axis::CIN:
        case Axis::COUT:
            return stride_[static_cast<int>(a)];
    }
    throw std::logic_error("BlockPackMapper::line_stride: unknown Axis");
}
```

The `switch` looks redundant, and the redundancy is the price of the array. It
converts "undefined behaviour on a bad cast" into "a diagnosed refusal", it is
the same refuse-rather-than-invent shape as section 18's `coord_on`, and
`-Wswitch` makes a fifth enumerator a build failure here rather than a silent
fall through to the `throw`. The general rule: an array indexed by an `enum
class` needs a `static_assert` on the numbering AND a validating lookup, or it
is two independent silent failures wearing a cast for reassurance.

### A delta is not a tagged type

`line_stride` returns `std::int64_t`, not `LineId`, and the v1 tree returned
`LineId`. The mechanical reason is that section 9 gave `Tagged` comparison
operators and nothing else, so `stride * block_index` does not compile and every
use would have to call `.get()` first. A tag stripped at every use is carrying
nothing.

The reason underneath is worth keeping, because it decides the same question
again at A4 for `SetIndex`. An **address** and a **delta between addresses** are
different quantities with different algebra:

| | line id | line stride |
|---|---|---|
| add two of them | meaningless | fine, a stride |
| subtract two of them | fine, gives a stride | fine, a stride |
| multiply by a plain integer | meaningless | fine, a stride |
| what `Tagged` gives it | the tag you want | operators it must not have |

C draws exactly this line between a pointer and `ptrdiff_t`, and C++ makes it
sharper: `p + q` on two pointers is a compile error, `p - q` is a `ptrdiff_t`.
So the shape a flatten takes is forced. Do the arithmetic in the plain
representation type, and construct the tagged type once, on the way out:

```cpp
std::int64_t line = 0;
for (Axis a : kAxes) line += block_index * line_stride(a);
return LineId{line};                          // named once, at the end
```

The test for whether something should be a `Tagged` is not "is it an int64 that
means something". It is "do the operations I need on it survive having no
arithmetic". A count, an id, and an index usually pass. A stride, an offset, and
a size usually do not.

---

## 22. Standard algorithms, exception safety, and two integer traps (unit A2d)

Four things `expand` and `locate` forced. The first two are the first use in the
tree of anything out of `<algorithm>`; the last two are places where C++ gives an
answer that is well defined, silent, and not the one you wanted.

### `std::sort`, `std::unique`, and why `Tagged` needs no comparator

De-duplicating a `std::vector` is three calls, and the shape is not obvious the
first time:

```cpp
std::sort(lines.begin(), lines.end());
lines.erase(std::unique(lines.begin(), lines.end()), lines.end());
```

Three separate facts, none of which a C programmer's intuition supplies:

1. **`std::unique` removes only *adjacent* duplicates.** It is a linear scan, not
   a set. That is why the sort comes first; on unsorted input it "works" and
   leaves duplicates behind, silently.
2. **`std::unique` does not erase anything.** It compacts the survivors to the
   front and returns an iterator to the new logical end. The elements past that
   point are unspecified but still there, and `size()` is unchanged. The
   container has no idea anything happened until you call `erase` with that
   iterator. Forgetting the `erase` is the classic version of this bug: the
   vector still holds the old count and the tail holds garbage.
3. **Both take the range as two iterators**, so `erase(first, last)` is the
   two-argument overload that removes a whole range, not the one-element one.

The part that matters for this tree is that neither call needs a comparator.
`std::sort` uses `operator<` and `std::unique` uses `operator==`, both found by
argument-dependent lookup, and section 9 gave `Tagged` exactly those. So

```cpp
std::vector<LineId> lines;      // sorts and uniques with no lambda in sight
```

works, while a hand-written wrapper class exposing only `.get()` would need a
lambda at every one of those call sites. This is the payoff of section 9's
choice to give `Tagged` the six comparisons and nothing else: comparisons are
precisely what the standard algorithms ask for, and arithmetic is precisely what
they do not.

### The strong exception guarantee, bought by doing the work to the side

`layout.h` requires that a call which throws leave the caller's buffer exactly as
it was. There are two ways to write that, and they are not equally safe:

```cpp
// (a) append, and roll back if something goes wrong
const std::size_t base = out.size();
try { for (...) out.push_back(...); }
catch (...) { out.resize(base); throw; }

// (b) build to the side, commit once at the end
std::vector<LineId> lines;
for (...) lines.push_back(...);
out.insert(out.end(), lines.begin(), lines.end());
```

(b) is what `expand` does. The difference is not style. In (a) the guarantee is
something you maintain: every future edit to the loop has to stay inside the
`try`, the bare `catch (...)` has to rethrow, and `resize` has to be the exact
inverse of what was done. In (b) the guarantee is structural, because `out`
appears exactly once in the function and it is the last statement. There is no
edit to the loop that can break it.

This is the small version of the **copy-and-swap** idiom, which is C++'s general
answer to "make this operation all-or-nothing": do the work on a copy, then
commit with an operation that cannot fail. Worth knowing by name, because it is
the same reasoning that will decide how a cache level installs a line.

One detail that makes the commit sound: the range `insert` either appends the
whole range or has no effect, provided copying the element type cannot throw.
`LineId` is trivially copyable, so that holds here. The cost of (b) is one
allocation per call, which is a real cost and is written in the code as a
comment rather than left for a reader to discover.

### `/` and `%` on a negative left operand

Since C++11 the language pins this down, and the pinned-down answer is a trap:

```cpp
-1 / 32  ==  0        // truncation toward zero, not toward minus infinity
-1 % 32  == -1        // the remainder takes the sign of the DIVIDEND
```

Both halves bite in this file, at different times:

| Expression | Naive expectation | What C++ gives | What it breaks |
|---|---|---|---|
| `cin / cin_block` at `cin = -1` | a negative block index | `0` | a bad coordinate lands on a real line (A2c) |
| `line % num_sets` at `line = -1` | `num_sets - 1` | `-1` | a set index used to index an array from below (A2d) |

Python answers `-1 // 32 == -1` and `-1 % 32 == 31`, so intuition carried over
from there is wrong in both columns. The rule to remember is that C++ makes
`(a / b) * b + (a % b) == a` hold with truncation toward zero, and everything
else follows from that.

The consequence for how code is written: neither of these is fixable by choosing
a type. Making the value unsigned would remove the negative rather than diagnose
it, which is worse, and it is the class of bug the whole tree is signed to avoid
(section 5's note on the v1 flatten). The fix is always a range check *before*
the division, which is why `locate` checks `0 <= line < num_lines()` first and
`line_of` checks each coordinate first.

### The width of an intermediate, and where the cast goes

```cpp
const std::int64_t last = start + static_cast<std::int64_t>(b.count - 1) * b.stride;
```

`count` and `stride` are both `std::int32_t`. C++ does **not** widen an
expression because of what it is assigned to: the usual arithmetic conversions
look only at the operands, so `b.count * b.stride` is computed in `int` and then
widened on the way into the `int64_t`. By then it has already overflowed, and
signed overflow is undefined behaviour rather than wraparound, so the compiler is
entitled to assume it did not happen.

So the cast has to sit on an **operand**, before the multiply, not on the result:

```cpp
static_cast<std::int64_t>(a) * b     // correct: the multiply happens in int64
static_cast<std::int64_t>(a * b)     // wrong:   the multiply already happened
```

One operand is enough; the other is converted to match. This is the same rule
`blocks_covering` in `block_pack.cpp` already follows for `(extent + block - 1)`,
and it is worth stating as a rule because the wrong version is not a warning:
`-Wconversion` complains about narrowing, and this is the opposite mistake.

---

## 23. Constraining a template, and how the tree's type wall was closed (unit A4a)

A1a built the type wall out of `explicit` (section 7) and `= delete` (section 8).
A4a closed the one hole left in it, and doing so needed four features that are new
to this tree and have no C analogue at all. They are worth learning together,
because none of them does anything useful alone.

The hole first, since it is what the machinery is for. `SlotId` holds an
`std::int32_t` and `Placement::tag` is an `std::int64_t`, so

```cpp
SlotId s{p.tag};        // 64 bits into 32
```

is a truncation. Under the old constructor it compiled, with a `-Wnarrowing`
warning, and a tag of 4294967303 arrived as slot 7. The compiler did complain;
nothing turned the complaint into a refusal.

### Correcting section 7

Section 7 quotes the constructor as

```cpp
constexpr explicit Tagged(Rep v) : v_(v) {}
```

**That is no longer the code.** This file is append-only, so the quote stays where
it is and this section is the correction. Everything section 7 says about
`explicit` is still true and still load-bearing; what changed is the parameter.
It now reads:

```cpp
template <typename U,
          typename = std::enable_if_t<detail::converts_without_narrowing<Rep, U>::value>>
constexpr explicit Tagged(U v) : v_{v} {}
```

`explicit` still blocks the conversion nobody asked for (`SimTime t = 5`). The
template blocks the conversion that was asked for but loses information.

### `std::declval<T>()`: a value of type T that never exists

```cpp
std::declval<T>()
```

There is no C equivalent because C has no need for one. It names a value of type
`T` **without constructing one**, which matters because you cannot always
construct a `T`: `Tagged` has no default constructor, and neither does anything
else in the tree that follows B2.

It is declared and never defined. Calling it is a link error by design. It exists
only inside `decltype`, which never evaluates its argument.

### `decltype(expr)`: the type this expression *would* have

```cpp
decltype(std::int32_t{std::declval<std::int64_t>()})
```

`decltype` asks the compiler a question about types and runs nothing. The
expression inside is analysed, its type is reported, and no code is emitted. It is
the closest C++ has to asking the compiler "would this line be legal?" in a place
where you can act on the answer.

Here the question is: *if* an `int32_t` were braced-initialised from an `int64_t`,
what would come out? There are two possible answers, `int32_t` or "that is
ill-formed", and it is the second one we are hunting.

Why braced initialisation specifically: it is the one context where the language
forbids a narrowing conversion outright. Not warns, forbids. So the question
"does `To{From}` compile?" is exactly the question "is `From` to `To`
non-narrowing?", asked of the compiler rather than answered by hand with a table
of widths and signednesses.

### `std::void_t<...>`: discard the answer, keep the question

```cpp
template <typename...> using void_t = void;
```

That is the entire definition. For any valid argument it is `void`. It looks
useless and it is exactly the point: it throws the type away and keeps only
*whether there was a type at all*. If the argument is ill-formed, `void_t` of it
is ill-formed too, and that failure is the signal.

### Partial specialisation as an if/else on well-formedness

Putting the three together gives a compile-time boolean:

```cpp
template <typename To, typename From, typename = void>
struct converts_without_narrowing : std::false_type {};            // fallback

template <typename To, typename From>
struct converts_without_narrowing<To, From,
                                  std::void_t<decltype(To{std::declval<From>()})>>
    : std::true_type {};                                           // preferred
```

Read it as an if/else. The first is the general case and the answer is "no". The
second is a **partial specialisation**: it is the same template with the third
argument pinned to something specific. When the compiler can compute that third
argument it prefers the specialisation, because a more specific match always wins;
when it cannot, the specialisation is not a candidate and the general case
answers.

So `converts_without_narrowing<To, From>::value` is `true` exactly when
`To{From}` compiles. `std::true_type` and `std::false_type` are standard empty
structs carrying a `static constexpr bool value`.

### Why `declval` not being a constant expression is load-bearing

This is the part that is easy to get wrong, and getting it wrong produces a rule
that behaves differently depending on where a value came from.

C++ has a deliberate exception to the narrowing rule: a **constant expression**
whose value fits is not narrowing. So both of these involve an `int64` source and
only one is legal:

```cpp
std::int32_t x{5L};       // legal:      5L is constant and 5 fits
std::int32_t y{big};      // ill-formed: big is a run-time int64
```

That exception is correct for values and wrong for a rule about types. Written
against a real constant, the trait would say "yes" for `SlotId{5L}` and "no" for
`SlotId{p.tag}`, and the rule would become "may an `int64` become a `SlotId`?
it depends". `std::declval<From>()` is deliberately **not** a constant
expression: it names a value of the type and says nothing about which value. So
the trait answers about the type, uniformly, and the constant-fits exception never
enters.

### `std::enable_if_t`, and SFINAE

```cpp
template <bool B, typename T = void> struct enable_if {};                 // no member `type`
template <typename T>                struct enable_if<true, T> { using type = T; };
template <bool B, typename T = void> using enable_if_t = typename enable_if<B, T>::type;
```

`enable_if_t<true>` is a type. `enable_if_t<false>` **is not**: the false
specialisation has no member `type`, so naming it is an error.

That looks like a strange thing to want until you meet the rule it feeds.
**SFINAE** stands for *substitution failure is not an error*: when the compiler
substitutes deduced template arguments into a template's signature and the result
is ill-formed, it does not report an error, it quietly removes that template from
the list of candidates and carries on.

So an `enable_if_t` in a signature is a switch. True and the template stays a
candidate; false and it vanishes. In `Tagged` the switch is wired to the trait, so
the constructor exists for non-narrowing sources and does not exist for narrowing
ones. `SlotId s{p.tag}` then fails with "no matching function for call to
`Tagged<int, tags::slot>::Tagged`", which is a hard error under every flag
combination, unlike the warning it replaced.

Note the shape of the win: the fix is not a better diagnostic on a bad
conversion. It is the **removal of the conversion**, so there is nothing left to
diagnose.

### Why a plain template constructor would hijack copy construction

This is the trap, and it is why the constraint cannot simply be dropped in favour
of a `static_assert` inside the body.

Write the constructor as an unconstrained template:

```cpp
template <typename U>
constexpr explicit Tagged(U v) : v_{v} { static_assert(...); }   // do NOT do this
```

Now consider copying a non-`const` value:

```cpp
SlotId a{1};
SlotId b{a};        // which constructor?
```

The candidates are the implicit copy constructor, `Tagged(const Tagged&)`, and
the template with `U = SlotId`. The copy constructor needs a qualification
adjustment to bind a non-`const` lvalue to a `const&`; the template is an exact
match. **The template wins**, and copy construction turns into a call that tries
to initialise `Rep` from a `Tagged`. The `static_assert` fires on a line that is
merely copying something.

The constraint is what prevents this, and it does so without a special case for
`Tagged`. For `U = SlotId`, the trait asks whether `std::int32_t{declval<SlotId>()}`
is well formed. It is not: `Tagged` defines no conversion operator to its
representation, `get()` being the only exit (section 7's note on the asymmetry).
So the trait is `false`, the template is removed, and the implicit copy
constructor is left holding the call.

Both spellings were checked rather than assumed:

```cpp
SlotId a{1};  SlotId b{a};     // ok, direct-initialisation
SlotId a{1};  SlotId b = a;    // ok, copy-initialisation
```

### Why the old constructor had to be removed, not shadowed

The tempting minimal change is to keep `Tagged(Rep)` and add a deleted overload
for the bad cases. It does not work, and the reason is worth knowing because it
is a place g++ is more permissive than the standard reads.

In `SlotId s{p.tag}` the narrowing happens while converting an argument to a
**constructor parameter**, and g++ treats narrowing in that position as
`-Wnarrowing`, a warning. So `Tagged(Rep)` stays viable, it is a better match than
any deleted template, and it is exactly what the bad call binds to. Keeping it
keeps the hole open. Only removing it removes the conversion.

### A measurement worth keeping, about braced member initialisers

The constructor initialises with braces, `v_{v}`, and the natural reading is that
this is a second line of defence, since a braced initialiser forbids narrowing.
**It is not.** Measured, by building both variants:

| Variant | `SlotId s{p.tag}` |
|---|---|
| constraint removed, braces kept | **compiles**, with `-Wnarrowing` and `-Wconversion` |
| constraint kept, braces replaced by `v_(v)` | rejected |

The constraint is solely load-bearing. The braces are defeated by the same
permissiveness described just above, which is exactly why reaching for them as
the fix does not work. They are kept for stating the rule where the value lands,
not for enforcing it.

### What this costs

Nothing at run time. `enable_if_t`, `void_t`, `declval` and the trait all
evaluate during compilation and emit no code; the constructor is still a single
`constexpr` assignment, still trivially inlined, and `Tagged` is still the same
size as its representation. Section 15's answer is unchanged. What it costs is
compile time and one paragraph of reading, which is the trade this whole file
exists to argue for.

---

## 24. Copy control on a polymorphic base, and a virtual with a body (unit A4b)

Four things arrive with the first concrete `CacheArray`: the third access label,
the five special member functions and what happens when you touch one of them, a
virtual function that has a default body instead of `= 0`, and one integer trap
that section 22's rule does not cover.

### `protected`, the third access label

Section 4 introduced `public` and `private`. There is one more:

```cpp
class CacheArray {
public:
    virtual ~CacheArray() = default;
    virtual SlotId probe(LineId) const = 0;
protected:
    CacheArray() = default;                 // reachable from a derived class,
    CacheArray(const CacheArray&) = default; // not from anywhere else
};
```

`protected` means: reachable from inside this class **and from inside any class
derived from it**, and from nowhere else. C has no equivalent, because C has no
inheritance.

It is the right label whenever a member is part of how a subclass is built but
not part of what a caller may do. That is exactly the case below.

### The five special member functions

C++ writes six functions for you if you do not: a default constructor, a
destructor, a copy constructor, a copy assignment operator, a move constructor,
and a move assignment operator. In C you write `struct S a = b;` and the compiler
copies the bytes; C++ generalises that into functions you can declare, default,
delete, or hide.

```cpp
CacheArray()                             = default;   // CacheArray a;
CacheArray(const CacheArray& other)      = default;   // CacheArray a = b;
CacheArray(CacheArray&& other)           = default;   // CacheArray a = std::move(b);
CacheArray& operator=(const CacheArray&) = default;   // a = b;
CacheArray& operator=(CacheArray&&)      = default;   // a = std::move(b);
```

`= default` asks for the compiler's version explicitly (section 8 introduced it
beside `= delete`). Writing them out changes nothing about *what* they do; it
changes *who may call them*, because the access label they sit under now applies.

### The bug this closes, measured rather than argued

A base class with public assignment can be assigned through a base reference, and
what gets copied is only the base part:

```cpp
struct A : CacheArray { int derived_state = 7; /* ...overrides... */ };

A a1;  A a2;  a2.derived_state = 9;
CacheArray& r1 = a1;
CacheArray& r2 = a2;
r1 = r2;                     // compiles
a1.derived_state;            // 7. Not 9.
```

This is **slicing**: `operator=` was chosen from the static type `CacheArray`, so
it assigned the `CacheArray` subobject, which holds nothing, and left everything
the derived class added untouched. No warning, no crash. For a cache array that
is a half-assigned object still answering queries.

Worth knowing which half of the classic slicing story applies here. The other
half, copying by value,

```cpp
CacheArray b = r2;           // error: cannot allocate an object of abstract type
void f(CacheArray a);        // same reason
```

was never possible, because a class with a pure virtual function is abstract and
no object of it can exist (section 19). So for an abstract base it is
**assignment**, not copying, that is the live hazard, and a test that only proves
"you cannot pass the base by value" is proving abstractness rather than copy
control.

### `protected` versus `= delete`, and why they are not interchangeable

Both stop the line above. They differ in what they leave a *derived* class:

| | base assignment `r1 = r2` | `Derived b = a;` | `std::vector<Derived>` |
|---|---|---|---|
| public (before) | compiles, **slices** | fine | fine |
| `protected` + `= default` | error, inaccessible | fine | fine |
| `= delete` | error, deleted | **error** | **error** |

`= delete` propagates: a derived class whose base has a deleted copy constructor
has its own implicitly deleted too, so the whole class becomes non-copyable and
non-movable, and `std::vector<Derived>` will not compile because a vector needs
to move or copy its elements when it grows.

Protected keeps the derived class copyable **as itself**, where the copy is whole
and correct, and makes the base unusable as either end of one, where it would not
be. That is the standard treatment of a polymorphic base, and here it is load
bearing rather than stylistic: the engine holds one L1 array per core over a
swept range of 8 to 256 cores, so a container of concrete arrays is the ordinary
case.

### The trap: declaring any constructor removes the implicit default one

This is the part that bites, and it is worth memorising as a rule.

> The compiler writes a default constructor for you **only if you declare no
> constructor at all.** Declaring one, of any kind, including a copy constructor,
> and including one you immediately `= default` or `= delete`, suppresses it.

So this alone breaks every subclass in the tree:

```cpp
protected:
    CacheArray(const CacheArray&) = default;    // a declared constructor!
```

```
error: use of deleted function 'A::A()'
note:  error: no matching function for call to 'wcache::CacheArray::CacheArray()'
```

...because `struct A : CacheArray { };` now has nothing to call for its base. The
first line names the subclass, which is not where the mistake is; the second line
is the one to read.
The fix is one line, and it must not be forgotten:

```cpp
    CacheArray() = default;
```

Note the asymmetry: declaring `operator=` would *not* have done this, because an
assignment operator is not a constructor. It is specifically the constructors
that suppress.

### A virtual function with a body, and when to prefer it to `= 0`

Section 19 covered the pure virtual, `= 0`: no body, class cannot be
instantiated, every subclass must implement it. A virtual function may also have
an ordinary body:

```cpp
class AddressMapper {
    virtual std::int64_t line_size_bytes() const = 0;              // pure: you MUST
    virtual std::string  line_size_terms() const {                 // default: you MAY
        return std::to_string(line_size_bytes());
    }
};
```

Dispatch is identical for both: the call goes to the override if the object has
one. The difference is what happens to a subclass that provides nothing. Pure
means it does not compile. A default means it inherits the base's body.

The rule that decides between them is not taste, it is **blast radius**. A pure
virtual is a demand on every implementation that will ever exist, so add one only
when no sensible default is possible or when a wrong default would be silently
harmful. Here the function exists to make one error message more informative, and
making it pure would have broken sixteen deliberately non-conforming test fakes
and four `compile_fail.sh` cases at once, for a diagnostic. A default that is
always correct if uninformative costs nothing and demands nothing.

The cost to watch is the opposite one, and this unit hit it: a default body is
easy to inherit *by accident*, and the base's default here calls
`line_size_bytes()` a second time, so a mapper that does not override it is asked
twice within one message. A pure virtual would have made that impossible by
forcing an answer. Neither choice is free; the trade is a demand on every
implementer against a default nobody notices.

### One more integer trap: a product no cast can save

Section 22 records the widening rule, that the cast must sit on an operand before
the multiply because `int32 * int32` overflows before it is assigned to an
`int64`. That rule assumes the fix exists. Sometimes it does not:

```cpp
std::int64_t line_bytes = mapper.line_size_bytes();   // up to 9.2e18 in this tree
std::int64_t assoc      = 2;
if (size % (line_bytes * assoc) != 0) { ... }         // both already int64
```

There is no wider type to cast to. Signed overflow is **undefined behaviour**,
not wraparound, so this is not a wrong number that a later check might catch: the
compiler is entitled to assume the overflow did not happen and optimise on that
basis, which can delete the very check you wrote.

The options are to guard the multiply (`b > INT64_MAX / a`, which
`block_pack.cpp` does), or to restructure so the product is never formed at all.
A4b took the second: `size % (L * A) == 0` is exactly equivalent to
`size % L == 0 && (size / L) % A == 0`, and the second form only ever divides.
Worth stating as a general habit, because it is easy to reach for the checked
multiply reflexively: **an equivalent expression that cannot overflow beats a
guard on one that can**, and it usually reads better too.

### What this costs

Nothing at run time. Every one of these is a compile-time access rule or a
defaulted function that generates the same code the compiler was generating
anyway, and the restructured check trades one multiply for one divide, once per
array construction.

---

## 25. Interfaces, ownership, and indexing by a tagged scalar (units A4c and A5)

A5 is the first unit in the tree that **owns** an object rather than borrowing
one, and the first that destroys one through a base pointer. That is where most
of this section is. The rest is the shape of a three-level class hierarchy and
the one thing that happens when a `std::vector` has to be indexed by a type that
is deliberately not an integer.

### An abstract interface and its implementations, in two *headers*

Section 20 covers the header / `.cpp` split, which is about translation units and
link time. This is a different split and it happens one level up, between two
headers:

```
layout.h  (abstract AddressMapper)      block_pack.h  (concrete BlockPackMapper)
cache.h   (abstract CacheArray)         set_associative.h  (concrete array)
policy.h  (abstract ReplacementPolicy)  stamp_policy.h     (LRU, FIFO, factory)
```

Three instances of the same arrangement now. The reason is not symmetry, and it
is worth stating because "one class per header" is a rule people apply for its
own sake and this is not that.

**An interface header includes only what the interface's signatures need.**
`policy.h` includes `<vector>`, `cache.h` and `types.h`, and nothing else. That
is a checkable claim, and the tree checks it: `compile_fail.sh` compiles cases
against `cache.h` alone, so a case that compiles is evidence that the array
interface needs no layout header. Fold the concrete class into the interface
header and that evidence evaporates silently, because the preamble now
transitively includes what it was proving it did not need. The cases do not fail;
they stop meaning anything, which is worse.

The implementation headers pull in more: `stamp_policy.h` adds `<memory>` for
`std::unique_ptr`, `<cstdint>` and `<cstddef>`. A file that only wants to talk
about policies in the abstract never pays for those.

### A class that stays abstract without saying `= 0` again

```cpp
class ReplacementPolicy {
public:
    virtual void   on_hit(SlotId)        = 0;
    virtual void   on_fill(SlotId)       = 0;
    virtual void   on_invalidate(SlotId) = 0;
    virtual SlotId pick_victim(const std::vector<Candidate>&) = 0;
};

class StampPolicy : public ReplacementPolicy {   // still abstract
public:
    void   on_fill(SlotId slot) override;
    void   on_invalidate(SlotId slot) override;
    SlotId pick_victim(const std::vector<Candidate>& c) override;
    //  on_hit is not mentioned at all
};

class LruPolicy  final : public StampPolicy { void on_hit(SlotId) override; };
class FifoPolicy final : public StampPolicy { void on_hit(SlotId) override; };
```

`StampPolicy` overrides three of the four pure virtuals and says nothing about
the fourth. It therefore **inherits `on_hit` as still pure**, and is itself
abstract:

```
error: cannot declare variable 'p' to be of abstract type 'wcache::StampPolicy'
note:   because the following virtual functions are pure within 'StampPolicy':
note:     'virtual void wcache::ReplacementPolicy::on_hit(wcache::SlotId)'
```

The thing to notice, coming from C: **there is no keyword for this.**
Abstractness is not declared, it is the residue of what has not been overridden,
recomputed by the compiler at every level of the hierarchy. Section 19 stated the
rule in passing; A5 is the first place in the tree that *uses* it as a design.
`StampPolicy` holds the whole mechanism (one stamp per slot, victim is the
smallest stamp) and leaves exactly the one decision that distinguishes the two
policies to the two leaves, which are three lines each.

`final` on the leaves is section 20's, applied here because a class deriving from
`LruPolicy` would be inheriting the recency rule in order to disagree with part
of it.

### `using StampPolicy::StampPolicy;`: inheriting constructors

```cpp
class LruPolicy final : public StampPolicy {
public:
    using StampPolicy::StampPolicy;      // this line
    void on_hit(SlotId slot) override;
};
```

Constructors are the one kind of member that is **not** inherited by default, and
the reason is sound: a base constructor cannot know about members the derived
class added, so silently inheriting one would leave them uninitialised.

The `using` declaration says "inherit them anyway". Every constructor of
`StampPolicy` becomes available as a constructor of `LruPolicy`, so
`LruPolicy p(256);` finds `StampPolicy(std::int32_t)`. Without it, both leaves
would need a forwarding constructor whose only job is to pass an argument along:

```cpp
explicit LruPolicy(std::int32_t n) : StampPolicy(n) {}     // not written
```

which is the same line twice, and a third time for every policy added later.

**The trap, since it is invisible until it bites.** The inherited constructor
runs the base's constructor and then default-initialises the derived class's own
members. Today both leaves have no members, so this is exactly right. The day one
gains a member, the inherited constructor will not initialise it, and there is no
diagnostic beyond whatever the member's own default gives. So a policy that adds
state must either give the member a default member initialiser at its
declaration, or replace the `using` with a real constructor. Same discipline as
the zero-initialised members in `set_associative.h`.

### `protected` on an ordinary member function

Section 24 introduced `protected` on the special member functions. Here it labels
a plain one:

```cpp
protected:
    void stamp(SlotId slot);      // stamp_[slot] = next_stamp_++;
```

Callable from `LruPolicy::on_hit`, which is the whole point, and not from
outside. `public` would make the recency mechanism part of what a policy promises
its callers, so the engine could stamp a slot with no event behind it. `private`
would put it out of reach of the one class that needs it. It is the access level
that says "this is for my subclasses", and it is the only one that does.

### `const` on a virtual is a decision that binds every future override

Section 19 records that an override may not *drop* the `const` on a base's
virtual. The other half of that rule is what shows up here: **the base's choice
is final for every implementation that will ever exist**, including ones nobody
has written.

```cpp
virtual SlotId pick_victim(const std::vector<Candidate>& candidates) = 0;   // NOT const
```

`const` is part of the function's type for override matching. A derived
`pick_victim` declared without `const`, against a base that has it, does not
override anything: it is a different function that happens to share a name, and
`override` turns that from a silent bug into a compile error.

```
error: 'SlotId RandomPolicy::pick_victim(const std::vector<Candidate>&)'
       marked 'override', but does not override
```

So the const-ness has to be right on the interface **before** the implementations
that need it exist. Here LRU and FIFO could both be `const` at this verb; they
only read stamps. A Random policy cannot, because drawing from an RNG advances
it. Making the interface `const` today would buy nothing and would force an
interface change across both cache levels and every fixture the day Random lands.
It is left non-`const` once, for a class that does not exist yet.

The practical consequence: a non-`const` member function can only be called
through a non-`const` reference, so the engine must hold its policies as
`ReplacementPolicy&` rather than `const ReplacementPolicy&`. That is not a loss,
since three of the four verbs mutate anyway.

### `std::unique_ptr`, `std::make_unique`, and returning ownership

```cpp
std::unique_ptr<ReplacementPolicy> make_policy(PolicyKind kind, std::int32_t num_slots) {
    switch (kind) {
        case PolicyKind::LRU:  return std::make_unique<LruPolicy>(num_slots);
        case PolicyKind::FIFO: return std::make_unique<FifoPolicy>(num_slots);
        ...
    }
}
```

`std::unique_ptr<T>` is a pointer that owns what it points at: when it goes out
of scope, it calls `delete`. There is exactly one owner at a time, which the type
enforces by being **move-only**. `auto b = a;` on a `unique_ptr` does not
compile; `auto b = std::move(a);` does, and leaves `a` null. Copying an owning
pointer is how a C program frees the same allocation twice, and here it is a
compile error rather than a rule to remember.

`std::make_unique<LruPolicy>(num_slots)` allocates an `LruPolicy`, forwards
`num_slots` to its constructor, and wraps the result, all in one expression.
Preferred over `std::unique_ptr<LruPolicy>(new LruPolicy(num_slots))` because
there is no point at which a raw pointer exists unowned. In this function it
matters concretely: `StampPolicy`'s constructor throws for a non-positive
`num_slots`, and with `make_unique` a throw during construction leaks nothing,
because no ownership was ever handed over.

**The conversion in the return statement is the interesting part.**
`make_unique<LruPolicy>` produces a `std::unique_ptr<LruPolicy>`, and the
function returns `std::unique_ptr<ReplacementPolicy>`. That converts because
`LruPolicy*` converts to `ReplacementPolicy*`, and `unique_ptr` allows the same
conversion on itself. It is a move, not a copy, so nothing is duplicated and the
caller ends up sole owner.

What this replaces, in C, is `Policy* make_policy(...)` plus a documented
`free_policy()` that every caller must remember to call on every return path
including the ones that throw. The `unique_ptr` version has the compiler emit the
free, at the right place, on every path.

### Destroying through a base pointer, and where the virtual destructor earns it

Section 19 states the rule: any class meant to be inherited from and held by base
pointer gets a virtual destructor, because deleting a derived object through a
base pointer with a non-virtual one is undefined behaviour. Until A5 that rule was
**prophylactic**. Nothing in the tree ever destroyed through a base pointer:
`AddressMapper` is held by `const&`, `SetAssociativeArray` is held as itself.

`make_policy` is the first place it is load-bearing. The returned
`std::unique_ptr<ReplacementPolicy>` holds a pointer whose *static* type is
`ReplacementPolicy*` and whose *dynamic* type is `LruPolicy`, and when it goes out
of scope it calls `delete` on the static type. With

```cpp
virtual ~ReplacementPolicy() = default;
```

that dispatches to `~LruPolicy`, then `~StampPolicy` (which frees `stamp_`), then
the base. Without the `virtual`, only the base destructor runs, `stamp_` is never
freed, and the usual symptom is a leak rather than a crash. At 8 bytes per slot
over one policy per core, that leak is not small.

`g++` will warn under `-Wdelete-non-virtual-dtor` when the static type has virtual
functions and a non-virtual destructor, which catches the common case, but the
warning is not the guarantee. The declaration is.

Note also that `unique_ptr` does **not** solve this for you. It calls `delete` on
the type it was told about; whether that reaches the derived destructor is the
base class's business, not the smart pointer's.

### `std::vector` indexed by a tagged scalar, and the `.get()` boundary

Section 8 records the friction a tagged type causes at construction
(`std::vector<SlotId> v(4);` does not compile). A4c and A5 hit the other half:
**a tagged type cannot subscript a vector at all.**

```cpp
std::vector<std::int64_t> stamp_;
SlotId slot = ...;
stamp_[slot] = 1;          // error: no match for 'operator[]'
```

`std::vector::operator[]` takes `size_type`, which is `std::size_t`. `SlotId` has
no implicit conversion to anything (section 7's `explicit`), so there is no
conversion sequence and the call simply does not exist. That is the design
working, not fighting it: the whole reason `SlotId` is a type is that a raw `int`
sitting where a slot id belongs is the bug this tree spends effort to prevent.

So the unwrap has to happen, and the discipline is that it happens at **one
place per class**, not at every subscript:

```cpp
// stamp_policy.cpp
std::size_t StampPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || static_cast<std::size_t>(s) >= stamp_.size()) {
        throw std::out_of_range(...);
    }
    return static_cast<std::size_t>(s);
}

stamp_[index_or_reject("stamp", slot)] = next_stamp_;
```

Three things are being done at once here, and only the first is obvious.

**One, the unwrap.** `.get()` returns the `std::int32_t` inside. That call is the
boundary: above it the code speaks in slot ids, below it in indices, and the
boundary is a named function rather than a `.get()` scattered through the file.
`set_associative.cpp` does the same job with a file-local `as_size()`, and states
the reason in a comment: with the cast spread across subscript expressions
instead, `-Wsign-conversion` would be answered with several casts rather than one
reviewable site.

**Two, the sign check happens in signed arithmetic, before the cast.** Writing
the comparison directly,

```cpp
if (s >= stamp_.size())      // int32 against size_t
```

triggers the usual arithmetic conversions, which convert the *signed* operand to
unsigned. `-Wsign-compare` warns about it, and the reason it warns is that a
negative `s` becomes an enormous unsigned value. Here that happens to give the
right answer, since the enormous value is also out of range, but it is right by
accident. Splitting it into `s < 0` (evaluated as `int32`) and then a cast makes
the rule explicit and keeps the file warning-clean under `-Wsign-conversion`.

**Three, one check for every verb.** `on_fill`, `on_invalidate`, `stamp` and
`pick_victim` all route through this function, so no two of them can disagree
about whether the top of the range is open or closed. `SetAssociativeArray` does
the same with `slot_or_reject`. The parameter is the *verb name*, not the class
name, because a caller holding a stray slot id needs to know which call it
reached.

### What this costs

One indirect call per policy verb, against a function body of one array write.
`std::unique_ptr` is the size of a raw pointer and its destructor inlines to the
`delete` you would have written. The inherited constructors and the access labels
generate nothing at all. `index_or_reject` is one predictable compare against a
member already in cache, and it is deliberately kept even on `on_hit`, the
hottest call in the model, because what it prevents is a silent out-of-bounds
write into `stamp_` when a policy is handed the slot ids of a differently sized
array.

### What these two units did *not* add to this file

Recorded so the absence does not read as an oversight. All of these appear in
A4c or A5 and are already covered:

| Feature in this batch | Where it is already explained |
|---|---|
| `virtual`, `= 0`, abstract classes, virtual destructors | section 19 |
| `override`, `final`, the header / `.cpp` split, `[[noreturn]]`, unnamed parameters (`void FifoPolicy::on_hit(SlotId) {}`), picking between the standard exception types | section 20 |
| `enum class PolicyKind : std::uint8_t`, exhaustive `switch`, the `throw` after it | section 18 |
| `protected` as an access label, the five special member functions, the trap that declaring any constructor removes the implicit default one | section 24 |
| `explicit` on a one-argument constructor | section 7 |
| `constexpr` on a namespace-scope constant (`kNeverStamped`), unnamed namespaces | sections 11 and 1 |
| where the cast goes, and signed / unsigned mixing | section 22 |

---

## 26. A min-heap, a template over a payload, node stability, and one measured piece of undefined behaviour (plan units B1, B2 and B3)

A note on the numbering before anything else, because this section is the first
to hit it. **The plan's Phase B units are named B1, B2, B3, and `PROGRESS.md`'s
board decisions are also numbered B1 through B104.** They are different things.
Below, a unit of the plan is always written "plan unit B2" and a board ruling is
always written "decision B2". Neither is written bare.

Plan unit B1 (`Port`) introduced no new C++ at all: two `SimTime` members, a
compare, and a `throw` that section 20 already covers. Everything in this section
comes from plan units B2 and B3.

### `std::priority_queue`, and getting a min-heap out of a max-heap

```cpp
// event.h
private:
    struct Later {
        bool operator()(const Event<Payload>& a, const Event<Payload>& b) const {
            return key_less(b.key, a.key);       // note the swapped arguments
        }
    };

    std::priority_queue<Event<Payload>, std::vector<Event<Payload>>, Later> q_;
```

**`std::priority_queue` is not a container.** It is a *container adaptor*: it owns
some other container (a `std::vector` unless you say otherwise) and keeps the heap
property in it using the same `<algorithm>` machinery you could call by hand
(`std::push_heap`, `std::pop_heap`). What it adds is that you cannot reach past
the interface and break the invariant.

Its interface is three calls and no more:

```cpp
q_.push(e);                  // insert,  O(log n)
const Event<P>& t = q_.top();// look at the winner, O(1), const reference
q_.pop();                    // remove the winner, O(log n), returns VOID
```

**`top()` is the element that compares *greatest* under the comparator.** The
default comparator is `std::less<T>`, so the default `priority_queue` is a
**max-heap**. The engine loop needs the earliest event, which is a min-heap, so
something has to be inverted. There are two places to do it, and the choice is
the interesting part:

- invert the *key comparator*, so `key_less` would actually mean "later than";
- keep `key_less` meaning what its name says, and invert at the single point where
  the container demands it, by **swapping the arguments**: `key_less(b.key, a.key)`.

The code does the second. `key_less` is read by the tests, by the oracle in
`test_event.cpp`, and by anyone reasoning about plan 3.6's key, and a comparator
whose name lies is a defect waiting for its first reader. The inversion is one
expression, in a private struct, next to the container that needs it.

**Three template arguments, and you have to write the second to reach the third.**
`std::priority_queue<T, Container, Compare>` defaults `Container` to
`std::vector<T>`, but C++ has no way to skip a template argument, so
`std::vector<Event<Payload>>` is spelled out even though it is the default. That
is why the declaration looks heavier than it is.

**The comparator is a *type*, not a function.** The `priority_queue` stores an
object of type `Later`, default-constructed. That is why `Later` is a `struct`
with an `operator()` rather than a lambda: in C++17 a lambda's type has no name
you can write in a template argument list, and a closure type has no default
constructor, so a lambda comparator has to be constructed separately and passed to
the `priority_queue` constructor. A named struct with `operator()` is spellable
and default-constructible. The mechanism is the same one section 13 explained for
`std::hash`: a class whose whole content is a call operator.

Two properties worth stating because the code depends on both:

**`pop()` returns nothing, so reading the winner is two steps.**

```cpp
Event<Payload> e = q_.top();   // copy out first
q_.pop();                      // then remove
now_ = e.key.time;
return e;
```

`top()` returns a **`const` reference** into the heap, so the value has to be
copied before `pop()` invalidates it. This is not an oversight in the standard
library: separating "look" from "remove" is what lets `pop()` be `noexcept`-ish in
practice, since a `pop()` that returned by value could throw *after* it had
already modified the container, leaving the element lost. It is also why
`pop_min()` returns by value here.

**A `priority_queue` cannot be iterated at all.** There is no `begin()`. That is a
feature in this tree rather than a limitation: nothing can accidentally read the
queue in container order and let the heap's internal arrangement leak into a
result. The only ordering anything can observe is the pop sequence, which is the
total order plan 3.6 specifies.

### A class template over a payload type, and why it is not a decision in disguise

```cpp
template <typename Payload>
struct Event {
    EventKey  key;
    EventKind kind;
    Payload   payload;
};

template <typename Payload>
class EventQueue { ... };
```

Section 5 introduced templates through `Tagged`, where the parameter is a **tag**:
a type that is never defined, never instantiated, and exists only to make
`Tagged<int64, sim_time>` a different type from `Tagged<int64, refusal_order>`.
This is the other use of the same feature, and it is worth separating because they
look identical on the page and do opposite jobs.

Here `Payload` is a **real type**. It is stored in the struct, copied into the
queue, and returned from `pop_min`. The template exists because **plan unit B2 does
not know what an event is about**: it is a `Request`, an `Mshr` entry, a core, or a
tile, and every one of those belongs to a later unit. Naming a concrete payload
here would be this unit deciding a downstream unit's storage.

The two ways to dodge that without a template are both worse and both are worth
naming, because they are the shapes a C programmer reaches for first:

- **`void*`.** Drops the type entirely, so nothing stops a `Request*` being popped
  as an `Mshr*`, which is precisely the class of accident the whole `Tagged`
  apparatus exists to prevent.
- **An opaque integer handle.** Looks type-safe and is not: it forces *this* unit
  to invent a handle table, a numbering, and a lifetime rule for entries it knows
  nothing about. That is the same decision the template avoids, taken anyway and
  hidden behind an `int`.

The ordering, which is all this unit owns, does not depend on the payload at all,
which is what makes the parameter free rather than speculative generality.

Two consequences, both already half-explained elsewhere in this file:

**The whole class lives in the header** (section 5, "templates live in headers").
There is no `event.cpp`, and there cannot be one, because the compiler must see the
body at every instantiation.

**Members of a class template are compiled only when used.** A template that is
included but never instantiated is barely checked: name lookup that does not depend
on the parameter happens at definition, everything else waits. So a header-only
unit is **not** tested by the library building, and `tests/test_event.cpp` says so
in its own opening comment. That is the C++ form of decision B33's lesson (an
interface with no implementation still has testable contracts): here, a unit with
no `.cpp` still needs a test that instantiates it, or a clean build proves nothing.

### `std::unordered_map`, node stability, and why `Request::mshr1` is safe

```cpp
// mshr.h
std::unordered_map<LineId, Mshr> entries_;

// mshr.cpp
Mshr& MshrFile::allocate(LineId line, Request& primary) {
    ...
    return entries_.emplace(line, std::move(entry)).first->second;
}
```

`std::unordered_map<Key, T>` is a hash table with **separate chaining**: a bucket
array of pointers, and every element in a separately allocated **node**. That
implementation is not an accident of one library; the standard's requirements
force it, and they force it by specifying exactly what survives what.

**The guarantee, which is the whole reason this container was chosen:**

| operation | invalidates iterators | invalidates **references and pointers** to elements |
|---|---|---|
| `insert` / `emplace` (no rehash) | no | **no** |
| `insert` / `emplace` **causing a rehash** | **yes** | **no** |
| `erase(it)` | only `it` | only the erased element's |

A rehash rebuilds the bucket array and re-links the nodes. **It moves pointers,
not nodes**, so an `Mshr&` handed out by `allocate` stays valid while any number
of other lines are allocated and retired around it.

That is load-bearing rather than convenient. `Request::mshr1` is a raw `Mshr*`
that a request holds across **the entire downstream round trip**: plan 4.1's
argument is that a request blocked at the L2 never released its L1 MSHR entry, so
the L2's wait sets are views over L1 entries that already exist (I6b). Concretely,
an `mshr1` taken at cycle 0 must still point at a live entry when its fill lands
110 cycles later, during which the same L1 file may have allocated and retired
entries for a dozen other lines.

**Compare `std::vector<Mshr>`,** which is what the same job would look like with
the container section 8 already covers: `push_back` may reallocate, and every
pointer into the vector dangles the moment it does. The header says exactly this.
An index instead of a pointer would work, but it replaces a pointer whose meaning
is fixed with an index whose meaning depends on what the vector does to the slots
of erased entries, which is a policy this class would then have to invent and
document.

Three smaller things the code depends on:

**`std::hash<LineId>` is what makes a tagged scalar a legal key.** Section 13
wrote that specialization at A1a, three units before anything used it. This map is
what it was written for.

**`emplace` returns `std::pair<iterator, bool>`.** So
`entries_.emplace(line, std::move(entry)).first->second` reads as: `.first` is the
iterator, `->second` is the mapped `Mshr`, and the reference to it is what is
returned. The `bool` is discarded here because `allocate` has already refused the
duplicate-line case with a `throw`, which is the stricter answer.

**Nothing ever iterates it, and that is a deliberate discipline.** A hash map's
iteration order is unspecified and may differ between library versions, builds, or
insertion histories. In a simulator whose whole exit criterion is bit-identical
re-runs (plan unit B2, D11), letting that order reach a result is a reproducibility
bug that no test failure announces. So every read of `entries_` is a lookup by line
or a `size()`, and the header states it. If a later unit ever needs to walk the
file, it must sort what it walks.

### `std::stable_sort` versus `std::sort`, and when stability is observable at all

```cpp
// mshr.cpp, at the end of retire()
std::stable_sort(out.wake.begin(), out.wake.end(),
                 [](const Request* a, const Request* b) { return key_less(*a, *b); });
```

Section 22 introduced `std::sort`. The difference here is one word:

| | guarantee | typical implementation | cost |
|---|---|---|---|
| `std::sort` | none about equivalent elements | introsort (quicksort with a heapsort fallback) | O(n log n), no extra memory |
| `std::stable_sort` | elements that compare **equivalent** keep their relative order | merge sort | O(n log n) with a temporary buffer; O(n log^2 n) if it cannot allocate one |

**Stability is observable only when two things are both true.** The comparator must
call two elements equivalent (neither `less(a,b)` nor `less(b,a)`), **and** those
two elements must be distinguishable by something the program later reads. If the
comparator is a strict total order over the elements actually present, no two are
ever equivalent, and `sort` and `stable_sort` produce **identical output** on every
input. The choice is then unobservable and is purely about cost.

That is exactly the situation here, and the code says so:

> Stable, so that if two stamps ever tie the result is still a function of
> insertion order rather than of the sort's internals. They cannot tie today,
> since every member of both indices was stamped by the write-once counter (I2),
> and that is exactly why the weaker guarantee is free.

The comparator is `a.refusal < b.refusal`, and refusal stamps are unique across
the whole run (I2). So there are no ties, nothing is paid in output, and the only
cost is a merge sort instead of an introsort over a list bounded by the wait
population.

**What the weaker guarantee buys is a failure mode, not a behaviour.** If the
uniqueness invariant ever weakens (a second stamp source, or a request reaching
the list unstamped and carrying `NoRefusal`), the answer stays a function of
insertion order rather than of the sort's internal pivot choices. Compare this
with plan unit B2's lesson in `EXPLAIN.md`: a result that is reproducible only
because the implementation happens to be deterministic is the shape that passes a
reproducibility test while being wrong.

**There is a stronger move, and this tree uses it elsewhere.** A5's `pick_victim`
(section 25, decision B93) faced the same problem and solved it in the
*comparator* instead: it breaks stamp ties on the smallest slot id, which makes
the answer invariant under **any** permutation of the input, not just under the
input order. That is stronger where a second meaningful field exists. Here it does
not: two requests with the same refusal stamp would have no second field with an
agreed meaning, so preserving insertion order is the honest fallback rather than a
weaker choice made out of habit.

### Signed integer overflow is undefined behaviour, and the optimiser will use that

This one is a measurement from this round, not a rule quoted from the standard,
and it is the most useful thing in this section.

**The rule.** Unsigned integer arithmetic wraps modulo 2^N, and that wrap is
**defined** by the standard. Signed integer overflow is **undefined behaviour**.
"Undefined" does not mean "some implementation-defined number"; it means the
compiler may assume it never happens and optimise on that assumption. The textbook
consequence is that a compiler may fold `x + 1 > x` to `true` for signed `x`,
because the only way it could be false is a path the standard says cannot exist.

**The measurement.** The randomized soak in `tests/test_mshr.cpp` drives the MSHR
file with a linear congruential generator. A linear congruential generator's entire
mechanism **is** the wrap: it multiplies by a large constant and relies on the
truncation. The first version of that line kept the state in an `int64_t`:

```cpp
std::int64_t rng = 12345;                                    // WRONG
auto next = [&rng]() {
    rng = rng * 6364136223846793005 + 1442695040888963407;    // signed overflow -> UB
    return (rng >> 17) & 0x7fffffff;
};
```

What happened:

- at `-O0` (the `fixture` build) the stream was a reasonable pseudo-random walk and
  the soak exercised allocations, merges, both wait indices, retires and grants;
- at `-O2` (the `release` build) **the stream collapsed into an allocate/retire
  alternation** that reached none of the paths the soak exists to reach;
- **and the test still reported zero mismatches.** The independent model agreed
  with the file, perfectly, about a stream that tested nothing.

That last line is the shape worth memorising: the failure did not look like a
failure. Nothing threw, nothing compared unequal, and the check that was supposed
to be the strongest in the file was silently checking almost nothing.

**Only the coverage floors caught it.** The soak counts allocations, merges,
line-waits, slot-waits, retires, drops, grants and releases, and asserts a minimum
for each. Those floors went unmet at `-O2`, which is the only signal there was.

**The fix is one type.**

```cpp
std::uint64_t rng = 12345;                                   // defined wrap
auto next = [&rng]() {
    rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
    return static_cast<std::int64_t>((rng >> 17) & 0x7fffffffULL);
};
```

Both builds now drive the same stream, which is also what makes a soak failure
reproducible between them.

**Why this belongs in this file.** It is a freshly measured example of why the
release-mode gate exists. The Makefile builds `fixture` at `-O0 -g` and `release`
at `-O2 -DNDEBUG`, with no `-fwrapv` and no sanitizers, and the suite is required
to be green in **both**. Before this round the argument for that requirement was
that `-DNDEBUG` compiles the asserts out; this is the first time in this tree that
the two builds have been measured to **behave differently on the same source**.

It is also the third instance of one recurring lesson, and the other two are
already on the record:

| shape | what the compiler does | how it is caught |
|---|---|---|
| a narrowing conversion into `Tagged` (decision B29, A4a) | `-Wnarrowing` **warning**, not an error, and `compile_fail.sh` runs without `-Werror` | SFINAE, at compile time, by construction |
| a destructor that loses its `virtual` (decision B104) | **warning**, not an error | a runtime destructor count through a base-pointer `unique_ptr` |
| **signed overflow in a wrapping accumulator** (this round) | **no diagnostic at all**, and the optimiser is entitled to act on it | a runtime coverage floor |

**In this suite, a defect the compiler is allowed to ignore is caught at run time
or not at all**, and the amount of it that is caught at run time is exactly the
amount someone wrote a floor or a counter for.

**The rule this tree follows, stated so it does not have to be re-derived.** A
counter or accumulator whose intended behaviour *includes* wrapping is
**unsigned**, with a cast at the boundary where it becomes a value. A quantity that
must **never** wrap stays **signed** (decision B5's convention for the ids), so
that the overflow remains undefined and a future sanitizer run or a bound check can
find it, rather than being silently defined into a wrong answer.

The two related hazards already recorded elsewhere are the same undefined
behaviour reasoned about rather than observed: `tag * num_sets` in U16's
obligation row, and section 24's "a product no cast can save". This round is the
first time the tree has watched one actually change a result.

### What this costs

`std::priority_queue` compiles to `std::push_heap` and `std::pop_heap` over a
`std::vector`: one comparison chain per sift step, no allocation beyond the
vector's growth, and no indirection per element. `Later::operator()` is a call to a
`constexpr` function on five scalars and inlines to the compare chain you would
have written.

The `Payload` template parameter costs nothing at run time and one instantiation
per distinct payload at compile time.

`std::unordered_map` is the expensive one and is the only container here that
allocates per element: one node per live MSHR entry, plus a bucket array that
grows by rehash. That is bought deliberately, for the reference stability
`Request::mshr1` needs; the alternative was not a cheaper container but an index
scheme with a policy to maintain.

`std::stable_sort` allocates a temporary buffer where `std::sort` does not. The
list being sorted is one entry's line waiters plus the grants of one retire,
bounded by I11 and by the credit supply, so it is small and the allocation is the
dominant cost of the call rather than the comparisons.

The unsigned LCG costs nothing over the signed one; it is the same multiply.

### What this batch did *not* add to this file

Recorded so the absence does not read as an oversight. All of these appear in the
Phase B sources and are already covered:

| Feature in this batch | Where it is already explained |
|---|---|
| `enum class EventClass / EventKind / WaitReason / Level` with an explicit `: std::uint8_t`, and the `throw` after an exhaustive `switch` (`class_of`) | section 18 |
| `struct` as a plain data carrier with member initialisers (`Request`, `Mshr`, `EventKey`, `RetireResult`) | section 18 |
| the header / `.cpp` split, `[[noreturn]]` refusal helpers, and choosing between `std::invalid_argument` and `std::logic_error` | section 20 |
| `constexpr` on `class_of` and on `event.h`'s `key_less` | section 11 |
| `inline` on a free function defined in a header (`mshr.h`'s `key_less` for requests) | section 12, which explains the same one-definition problem for a variable; on a function `inline` licenses the definition to appear in every translation unit that includes the header, and the `constexpr` functions beside it are `inline` implicitly |
| `std::vector` as a member, and why `std::vector<SlotId> v(4)` does not compile | sections 8 and 25 |
| the `.get()` boundary, `static_cast` placement, and signed / unsigned mixing in `as_count` | sections 22 and 25 |
| `std::hash` on a tagged scalar, which is what lets `LineId` key the map | section 13 |
| `std::min_element` with a comparator, in `collect_grants` | section 22's `<algorithm>` note; it is `std::sort`'s comparator convention with one element returned instead of a range reordered |
| operator overloading on `SimTime` (`accept + ii_` in `Port::reserve`) | section 9, and the deliberate absence of arithmetic on the other tagged scalars is section 21's "a delta is not a tagged type" |
| `std::move` into `emplace` | still owed, and it stays owed: it appears once, as an optimisation of a copy that would also have been correct, so section 17's move-semantics row is unchanged and still points at plan unit C2 |
