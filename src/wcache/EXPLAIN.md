# EXPLAIN: increment A2c, the flatten helpers

**Erasable.** Overwritten at every increment. The record is `PROGRESS.md`.

Changed files: `native/include/wcache/block_pack.h`, `native/src/block_pack.cpp`.
Nothing else in the model changed. No test file was touched: A2c's tests are the
reviewer's next round.

Plan reference: v3 Part 2.1 (address-generator row), Part 7 unit A2, N11, V15,
board decisions B17, B22, B23, B24, and the two carried obligations `A2b -> A2c`
(the strides are fixed, A2c implements them) and `B24 -> A2c` (they live in an
array indexed by `Axis`).

```
$ make clean && make test
92 compile cases, 0 failures
145 checks, 0 failures        (test_block_pack)
9270 checks, 0 failures        (test_layout)
263 checks, 0 failures         (test_types)
exit 0
```

Counts unchanged from what the reviewer left, which is the expected result: A2c
adds behaviour that nothing tests yet, and the one thing the existing suite says
about it is that the A2d stubs still throw. They still do.

Warning-clean under `-Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion
-Wshadow`, with no cast added to silence anything.

---

## 1. What landed

Three public member functions and one private member.

```cpp
class BlockPackMapper final : public AddressMapper {
public:
    std::int64_t line_stride(Axis a) const;   // the radix of axis `a`
    std::int64_t block_len(Axis a)   const;   // the extent of `a`, in lines
    LineId       line_of(const Coord& c) const;   // the flatten

private:
    std::int64_t stride_[4] = {0, 0, 0, 0};   // indexed by static_cast<int>(Axis)
};
```

`expand` and `locate` are untouched. They are still the `std::logic_error` stubs
naming A2d, and `tests/test_block_pack.cpp` still asserts that they throw.

The constructor gained four assignments at its end:

```cpp
stride_[static_cast<int>(Axis::COUT)] = 1;
stride_[static_cast<int>(Axis::CIN)]  = n_cout_blocks_;
stride_[static_cast<int>(Axis::KW)]   = checked_mul(n_cin_blocks_, n_cout_blocks_, "KW line stride");
stride_[static_cast<int>(Axis::KH)]   = checked_mul(shape.KW, stride_[static_cast<int>(Axis::KW)], "KH line stride");
```

and the file gained two small helpers in its anonymous namespace: `reject_range`,
which throws `std::out_of_range` with the same `BlockPackMapper: ` prefix the
constructor uses, and `block_size_on`, which answers "what do I divide a
coordinate on this axis by to get a block index" with 1 for KH and KW.

---

## 2. The running example

Layer `3x3x512x512` at `cin_block = cout_block = 16`. This is B22's worked case
on the board, so the numbers below can be checked against a row that was written
before the code was.

```
KH = 3, KW = 3, CIN = 512, COUT = 512, cin_block = cout_block = 16

n_cin_blocks  = ceil(512 / 16) = 32
n_cout_blocks = ceil(512 / 16) = 32
num_lines     = 3 * 3 * 32 * 32 = 9216
```

The four strides, computed innermost first, which is how the constructor writes
them and how they are easiest to read:

| Axis | stride | why that number |
|---|---|---|
| COUT | `1` | innermost: consecutive cout blocks are consecutive lines |
| CIN | `n_cout_blocks` = `32` | one step in cin skips a whole run of 32 cout blocks |
| KW | `n_cin * n_cout` = `32 * 32` = `1024` | one step in kw skips a whole 32 by 32 block plane |
| KH | `KW * n_cin * n_cout` = `3 * 1024` = `3072` | one step in kh skips a whole kw row of those planes |

and `block_len`, which answers a different question on the same layer:

| Axis | `block_len` | why |
|---|---|---|
| KH | `3` | KH is not blocked, so its extent in lines is its extent |
| KW | `3` | same |
| CIN | `32` | the block count, not 512 |
| COUT | `32` | the block count, not 512 |

Note that `line_stride` and `block_len` are the two different factorisations of
the same 9216: the product of the four `block_len`s is `3 * 3 * 32 * 32 = 9216`,
and `block_len(KH) * line_stride(KH) = 3 * 3072 = 9216` as well. That identity
holds for the outermost axis only, and it is a good thing for a test to pin,
because it is exactly what a swapped pair of strides breaks.

Verified empirically while writing this, on the real object rather than on
paper: enumerating all `3 * 3 * 512 * 512 = 2359296` coordinates of that layer
and counting how often each line id comes out gives every one of the 9216 lines
hit exactly 256 times, `256 = 16 * 16` being the elements in a block, and no
line unreached. That is the surjectivity onto `[0, num_lines)` that B23 says the
engine rests on.

---

## 3. Worked example one: an ordinary `line_of`

```
c = (kh = 1, kw = 2, cin = 80, cout = 48)
```

Step by step, in the loop's order:

```
KH:   coord 1,  in [0, 3)   ok,  block index = 1        (KH is unblocked)
KW:   coord 2,  in [0, 3)   ok,  block index = 2        (KW is unblocked)
CIN:  coord 80, in [0, 512) ok,  block index = 80 / 16 = 5
COUT: coord 48, in [0, 512) ok,  block index = 48 / 16 = 3

line = 1 * 3072
     + 2 * 1024
     + 5 * 32
     + 3 * 1
     = 3072 + 2048 + 160 + 3
     = 5283
```

The code prints 5283. And 5283 is in `[0, 9216)`, as it must be.

The same result through the Horner spelling in `block_pack.cpp`'s header comment,
as a cross-check that the loop and the comment agree:

```
((1 * 3 + 2) * 32 + 5) * 32 + 3 = (5 * 32 + 5) * 32 + 3 = 165 * 32 + 3 = 5283
```

The loop is what the code actually does. The Horner form is written in the file
as documentation and is deliberately NOT the implementation: it hardcodes the
order into the expression, which is the thing B24 asks to keep in one place.

### And the burst B22 worked

The board's row for B22 says the burst `[kh=1, kw=2, cin=80, cout 0..511 stride
1]` gives ids 5280 to 5311, contiguous. The code:

```
line_of(1, 2, 80,   0) = 5280
line_of(1, 2, 80, 511) = 5311
```

512 elements collapse to 32 distinct lines because `cout_block = 16`, and those
32 ids are contiguous. This is the first time the board's claim has been checked
against running code rather than against a hand calculation, and it agrees.

---

## 4. Worked example two: mid-block, where the division matters

Three coordinates that are different elements and the same line:

```
c1 = (1, 2, 80, 48)   ->  80 / 16 = 5,  48 / 16 = 3   ->  5283
c2 = (1, 2, 85, 50)   ->  85 / 16 = 5,  50 / 16 = 3   ->  5283
c3 = (1, 2, 80, 51)   ->  80 / 16 = 5,  51 / 16 = 3   ->  5283
```

All three print 5283. This is the whole point of the layout and not a rounding
accident: a line holds the `16 x 16` tile `cin in [80, 96) x cout in [48, 64)`,
so every one of those 256 elements is the same fetch. `c2` is five rows and two
columns into the tile and `c3` is three columns in.

The boundary is what a test should push on, since "the division truncates" and
"the division is a shift by 4" agree everywhere except at the edges:

```
line_of(1, 2, 95, 63) = 5283    the last element of that tile
line_of(1, 2, 96, 48) = 5315    cin crosses into block 6:   5283 + 32
line_of(1, 2, 80, 64) = 5284    cout crosses into block 4:  5283 +  1
```

The two increments, `+32` and `+1`, are `line_stride(CIN)` and
`line_stride(COUT)` respectively. That is a second way to state what a stride is
and a second thing worth testing: stepping one block on an axis moves the line id
by exactly that axis's stride.

The two extremes of the layer:

```
line_of(0, 0,   0,   0) = 0
line_of(2, 2, 511, 511) = 2 * 3072 + 2 * 1024 + 31 * 32 + 31 = 6144 + 2048 + 992 + 31 = 9215
```

and 9215 is `num_lines - 1`, which is the tight end of the range. A flatten with
a stride one too small would produce a maximum below 9215 and nothing would
crash; the ids would just be aliased, several coordinates sharing a line that
should not. That is the failure this increment is most exposed to, and it is
invisible in every check that only asks whether the answer is in range.

---

## 5. Worked example three: a negative coordinate, and what truncation hides

```
line_of(1, 2, -1, 48)
```

Without the explicit check, here is what would happen. C++ integer division
truncates toward zero, so `-1 / 16 == 0`, not `-1`. The flatten would compute

```
line = 1 * 3072 + 2 * 1024 + 0 * 32 + 3 * 1 = 5123
```

which is a perfectly ordinary line id inside `[0, 9216)`, belonging to the tile
`cin in [0, 16) x cout in [48, 64)`. Nothing about 5123 announces that it came
from a coordinate the tensor does not have. The whole range
`cin in [-15, -1]` maps to block 0 the same way, so an off-by-one in a caller's
loop, or a trace field decoded at the wrong offset, produces a hit on a real line
and a hit rate that looks plausible. This is the v1 lesson the archive preserved,
and it is why signedness alone is not the fix: making the coordinate signed is
what lets the wrong value be represented, and only a check makes it visible.

What actually happens:

```
BlockPackMapper: CIN coordinate out of range [0, 512), got -1
```

thrown as `std::out_of_range`. The message carries the prefix, the axis name, the
legal half-open range, and the offending value, which is what N11 asks for and
what decision B7 said the thrower has to assemble because it is the only place
holding the coordinate and the shape at once.

Two more, to show the check is a range and not a sign test:

```
line_of(1, 2, -15, 48)  ->  out_of_range, "CIN coordinate out of range [0, 512), got -15"
line_of(0, 0, 512,  0)  ->  out_of_range, "CIN coordinate out of range [0, 512), got 512"
line_of(3, 0,   0,  0)  ->  out_of_range, "KH coordinate out of range [0, 3), got 3"
```

The last one matters as much as the negative: `cin = 512` divides to block 32,
`32 * 32 = 1024`, and the flatten would return `1024` more than it should, which
on this layer walks into the next `kw` plane. Overshoot aliases just as silently
as undershoot.

### Why the check reads the shape and not `block_len`

This was a real fork, and I took the shape.

`line_of` validates `0 <= coord_on(c, a) < extent_on(shape_, a)`. The
alternative was to divide first and validate the quotient against
`block_len(a)`. Three reasons for the shape:

1. **The shape check is strictly stronger.** Take `CIN = 100` with
   `cin_block = 32`, so `n_cin_blocks = 4`. A `cin` of 100 is not an element of
   the layer, but `100 / 32 = 3` and `3 < 4`, so a `block_len` check accepts it.
   Every coordinate in the padded tail `cin in [100, 128)` gets through the same
   way. On the negative side, `cin = -1` gives block 0 and `0 < 4` accepts it
   too. So the `block_len` version passes exactly the two cases section 5 exists
   to catch.
2. **They are different quantities.** A coordinate is an element index and
   `block_len` counts blocks. Comparing them is a category error that happens to
   typecheck because everything here is an integer.
3. **A shared path is a shared failure mode.** Routing the check through
   `block_len` would mean one mutation to `block_len` reddens both the range
   check and the flatten at once, which is a real testability gain and is the
   argument on the other side. It also means the range check can no longer
   disagree with the flatten, and disagreeing is precisely its job here: the
   check is about elements, the flatten is about blocks.

The cost I am accepting: `block_len` now has no caller inside the library. Its
first real consumer is A2d's range check on a walked burst. Until then it is only
as good as the reviewer's direct tests of it, and a mutation to `block_len` alone
will not redden `line_of`. That is a deliberate trade, not an oversight.

---

## 6. Worked example four: an asymmetric shape

Symmetric examples hide everything: with `n_cin == n_cout` a swapped stride pair
changes nothing, and with `KH == KW` a dropped factor can cancel. Layer
`3 x 5 x 100 x 50` at `cin_block = 32`, `cout_block = 8`, which is the shape
`test_block_pack.cpp` already uses for the constructor, so the block counts are
pinned by existing tests:

```
n_cin_blocks  = ceil(100 / 32) = 4     (floor would give 3)
n_cout_blocks = ceil(50 / 8)   = 7     (floor would give 6)
num_lines     = 3 * 5 * 4 * 7 = 420
```

Every one of the eight numbers this increment produces is distinct here:

| Axis | `line_stride` | `block_len` |
|---|---|---|
| KH | `KW * n_cin * n_cout` = `5 * 4 * 7` = `140` | `3` |
| KW | `n_cin * n_cout` = `4 * 7` = `28` | `5` |
| CIN | `n_cout` = `7` | `4` |
| COUT | `1` | `7` |

Note `line_stride(CIN) == 7` and `block_len(COUT) == 7` are the same number for
an unrelated reason, which is a nice reminder that the two functions answer
different questions and a test that conflated them would still pass here.

Three flattens on that layer:

```
line_of(0, 0, 96, 48):  0*140 + 0*28 + (96/32)*7 + (48/8)*1 = 0 + 0 + 21 + 6 = 27
line_of(1, 3, 64, 16):  1*140 + 3*28 + (64/32)*7 + (16/8)*1 = 140 + 84 + 14 + 2 = 240
line_of(2, 4, 99, 49):  2*140 + 4*28 + (99/32)*7 + (49/8)*1 = 280 + 112 + 21 + 6 = 419
```

The last is `num_lines - 1 = 419`, and it is the interesting one: `cin = 99` is
the last legal element, `99 / 32 = 3`, which is the fourth block and holds only
`100 - 96 = 4` real columns out of 32. `cout = 49` gives `49 / 8 = 6`, the
seventh block, holding `50 - 48 = 2` real rows out of 8. So line 419 is
`4 * 2 = 8` real elements in a `32 x 8 = 256` element line, and it is still a
whole line. That is B13's ceiling rule and D2's padding-fraction obligation
meeting each other in one line id.

And the degenerate case the tiny verification trace needs, `3x3x1x4` at
`cin_block = cout_block = 1`:

```
n_cin = 1, n_cout = 4, num_lines = 36
strides: KH 12, KW 4, CIN 4, COUT 1
block_len: KH 3, KW 3, CIN 1, COUT 4
line_of(2, 2, 0, 3) = 2*12 + 2*4 + 0*4 + 3*1 = 24 + 8 + 0 + 3 = 35 = num_lines - 1
```

Here `line_stride(CIN) == line_stride(KW) == 4`, because `CIN` has only one block
and so contributes no depth at all. A stride table with a duplicate in it is
legal and this is when it happens.

---

## 7. The four decisions inside this increment

### `stride_[4]`, not four named members

Board obligation `B24 -> A2c`. The array means the flatten reads its order out of
data rather than out of an expression: `line_of` never mentions `n_cout_blocks_`
and never mentions which axis is innermost. A permutation parameter, if it is
ever wanted, is an edit to the four assignments at the end of the constructor and
to nothing else, and `expand` and `locate` at A2d will read the same array.

What makes the indexing safe is the four `static_assert`s already at
`block_pack.cpp:32-35`. They pin `Axis::KH == 0` through `Axis::COUT == 3`, so
reordering the enumerators in `types.h` stops the build in this file. Without
them, `static_cast<int>(Axis::CIN)` would quietly become a different slot and the
line ids would be plausible and wrong.

### `line_stride` returns `std::int64_t`, not `LineId`

The v1 tree returned `LineId`. That is no longer possible, and the reason is a
real consequence of A1's typing rather than a style preference: `LineId` is
`Tagged<std::int64_t, tags::line>` with no arithmetic operators at all, so
`stride * block_index` would not compile, and the only way to write the flatten
would be to call `.get()` on the stride at every use. A tag that has to be
stripped before every use is not carrying anything.

The deeper reason is that a stride is a **delta** and `LineId` is an **address**.
They have different algebra: two line ids can be subtracted to give a stride, a
stride can be scaled by a coordinate, and adding two line ids together is
meaningless. This is the same distinction C draws between `ptrdiff_t` and a
pointer. `line_of` therefore does all its arithmetic in plain `int64` and
constructs the `LineId` once, on the return statement.

### The out-of-enumerator `Axis` follows `extent_on`

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

The switch covers every enumerator and the throw is after it, which is exactly
the shape `extent_on`, `coord_on`, `with_coord_on` and `axis_name` use in
`types.h`. `-Wswitch` is what makes it cheap: adding a fifth enumerator is a
build failure here rather than a fall-through to the throw at run time.

`std::logic_error` and not `std::out_of_range`, matching `extent_on`: an `Axis`
that is not one of the four did not come from a range, it came from a cast or
from uninitialised memory, and that is a bug in the program. The message spelling
is `BlockPackMapper::line_stride: ` rather than `extent_on: ` because this file
already qualifies its messages with the class name (the A2d stubs do), so the
class-name prefix stays greppable while the function-name-then-colon shape is
`types.h`'s.

The `switch` looks redundant next to a plain array index, and it is not: the
index would be silently out of bounds for a cast-in value, which is exactly the
accident the array form of B24 introduces and has to pay for.

### `checked_mul` on the strides, and where the fill sits

The strides are filled **after** `num_lines_`, deliberately. `num_lines_` is
`KH * stride_[KH]` and `KH >= 1` has already been validated, so every stride is
bounded above by `num_lines_`, and once `num_lines_` has been checked to fit in
`int64` no stride can overflow. The two `checked_mul` calls are therefore
provably unreachable today.

They are written anyway, and the reason is that the bound above is an argument
about the order of two blocks of code, not something the code states. Move the
stride block above `num_lines_`, or relax the KH check, and the guard is the
difference between a diagnosed refusal and undefined behaviour. Two divisions,
once per mapper, is not a price worth arguing about. The messages are `"KW line
stride"` and `"KH line stride"` so that if one ever does fire it says which.

One consequence for the reviewer: the existing overflow tests all fire inside
`num_lines`, and it is not possible to construct a mapper where a stride
overflows and `num_lines` does not. A test asserting a `"KH line stride
overflows"` message cannot be written, and that is a statement about the
arithmetic rather than a gap in the suite.

---

## 8. What A2c does not do

- No `expand` and no `locate`. They are still the A2d stubs and
  `test_block_pack.cpp:test_the_a2d_members_are_still_stubs` still passes.
- No range check on a `LineId` coming in. That is `locate`'s, owed by A2d, and
  it is the mirror of `line_of`'s check: `line_of` guards the domain,
  `locate` guards the codomain.
- No decision about `count == 0` on a burst. Still A2d's, still open on the
  board.
- No tests. The reviewer takes A2c next round.

`CPP_NOTES.md` gained **section 21**, covering the two things A2c actually
forced. Both were checked against what is already there before being written.

The first is indexing an array by an `enum class`. Section 18 covers the cast
being mandatory and covers `static_cast<Axis>(9)` being well defined; what it
does not cover is what those two facts mean together once an array is involved,
which is that a raw subscript is unchecked, `std::array::operator[]` is unchecked
too, and the well-defined out-of-enumerator cast is therefore a read past the end
of the object. That is why `line_stride` is a `switch` rather than a one-line
index, and it is a rule that will apply again to any per-axis or per-level table.

The second is why a stride is `int64` and not `LineId`, written as a general test
rather than as a note about this function, because A4 decides the same question
for `SetIndex`: a `Tagged` type is right when the operations you need on the
value survive having no arithmetic. An id survives, a delta does not.

What was left out: the `stride_[4]` idiom itself, which is plain C and needs no
explanation, and a general essay on `Tagged`, which section 6 already covers.

---

## 9. Open questions

**U1 (already on the board, and I hit it head on).** Which exception type is a
range failure? I used `std::out_of_range` for `line_of`. That is not specified in
`layout.h` and not in the plan; I chose it on the strength of a **comment in
`tests/check.h`** naming `out_of_range`, plus `CPP_NOTES.md` section 20's table,
which reserves `out_of_range` for "A2d: a burst coordinate outside the tensor".
Both are notes rather than specification. What I am confident about is the
negative half: it must not be `std::invalid_argument`, because that is the
constructor's type and a caller must be able to tell "your configuration is
wrong" from "your coordinate is wrong". `layout.h` should state the type in a
comment on `expand` before A2d writes the second thrower.

**U7, new.** Is a coordinate inside a layer's **padding** legal? Right now it is
not: `CIN = 100` with `cin_block = 32` gives 4 blocks covering `cin in [0, 128)`,
and `line_of` rejects `cin = 100` even though line 3 exists and holds it. I think
rejecting is right, because the trace only ever names real elements and a
coordinate in the padding is a caller bug. But it means `line_of` is not
surjective onto `[0, num_lines)` for a non-dividing layer, and A2d's
`locate` will happily place a line that `line_of` can never produce. Worth
stating in `layout.h` before D2 tries to reason about coverage.

**U8, new.** Should `block_len` exist at all before A2d needs it? It has no
caller in the library today, since section 5 explains why `line_of` does not use
it. It was specified for this increment and it is what A2d's burst range check
compares against, so I built it, but a reader looking at the tree today sees a
public function nothing calls. If the answer is "A2d justifies it", nothing needs
doing. If not, it could move to A2d.

**U9, new.** Should the identity `block_len(a) * line_stride(a) == num_lines()`
be asserted for the outermost axis, or the more general
`line_stride(outer) == block_len(inner) * line_stride(inner)` for each adjacent
pair? It is true by construction for all four axes here and it is a cheap
invariant that catches a swapped or dropped radix. It reads as a test rather than
as production code, so I did not put it in the constructor, but it is exactly the
sort of thing that could be an assert. Flagging it as a suggestion for the
reviewer rather than deciding it.

**U10, new.** The message says `CIN coordinate out of range [0, 512), got -1`. It
names the axis, the range, and the value, but not the layer. V15 wants tile,
tick, core and coord together, and A2a already carries an obligation that
something above A2 must catch and re-throw with the other three, unowned. This
increment is the first code that actually throws such a message, so the
obligation is now live rather than hypothetical.
