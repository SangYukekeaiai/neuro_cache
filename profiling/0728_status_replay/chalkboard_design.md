# Hit-rate correction chalkboard

## 1) Layout plan

Concept: Why must cache hit rate be counted per burst rather than per
expanded weight?

1. **One physical burst**
   - `(kh, kw, cin, cout 0→4)`
   - Four logical weights
   - One memory transaction
2. **Old: element-wise**
   - Replay tags `A, A, A, A`
   - Count `MISS + HIT + HIT + HIT`
   - Three artificial intra-burst hits
3. **Correct: burst-wise**
   - Expand only to form line tags
   - Dedup inside the event: `[A]`
   - Replay one cache decision
4. **Result**
   - Tiny trace: `38/48 → 2/12`
   - `79.17% → 16.67%`
   - Distinct lines still count separately

Arrows: `1 → 2`, `2 → 3`, `3 → 4`.

## 2) Image-generation prompt

Create a dark-slate chalkboard teaching diagram with subtle chalk texture and
large, high-contrast handwritten chalk typography. Arrange four rounded
bubbles left-to-right with chalk arrows: “ONE PHYSICAL BURST” with
“(kh, kw, cin, cout 0→4)”, “Four logical weights”, “One memory transaction”;
“OLD: ELEMENT-WISE” with “Replay tags A, A, A, A”, “MISS + HIT + HIT + HIT”,
“Three artificial intra-burst hits”; “CORRECT: BURST-WISE” with “Expand only
to form line tags”, “Dedup inside event: [A]”, “Replay one cache decision”;
and “RESULT” with “Tiny trace: 38/48 → 2/12”, “79.17% → 16.67%”, “Distinct
lines still count separately”. Use muted coral chalk for the old path, teal
chalk for the corrected path, and warm yellow for the result. Keep generous
margins, minimal text, and correct spelling. Avoid photorealistic people,
logos, tiny paragraphs, dense equations, and cropped text.

## 3) Narration script

One weight-address event describes a single physical burst, even though it
can contain several logical weights. The old replay expanded the four weights
and treated all four identical cache-line tags as separate accesses. That
turned the first miss into three immediate, artificial hits. The corrected
path still expands weights because it needs their line tags, but it
deduplicates identical consecutive tags inside the event before replay. A
burst touching one line therefore makes one cache decision; a burst spanning
multiple lines makes one decision per distinct line. In the hand-derived
example, this changes the reported hit rate from 38/48 to the physically
meaningful 2/12.

## 4) Alt text

A four-stage chalkboard diagram compares old element-wise cache accounting
with corrected burst-wise accounting. Four weights in one burst all map to
line A; the old method counts one miss and three artificial hits. The corrected
method deduplicates the tags to one A access. The tiny example's hit rate
therefore changes from 79.17% to 16.67%.
