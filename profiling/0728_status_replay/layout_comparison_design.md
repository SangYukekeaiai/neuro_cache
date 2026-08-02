# COUT-only versus CIN × COUT layout board

## 1) Layout plan

1. **One LoAS burst**
   - Fixed `KH, KW, CIN`
   - 16 consecutive COUT weights
   - Base unit is 16 B
2. **COUT only**
   - Keep one CIN per line
   - 32 B reaches 32 COUT
   - 64 B reaches 64 COUT
3. **CIN × COUT**
   - Keep each COUT run 16-wide
   - 32 B packs 2 adjacent CIN
   - 64 B packs 4 adjacent CIN
4. **Where they diverge**
   - Identical at 16 B
   - Different at 32/64 B
   - Same total line capacity

Arrows: `1 → 2`, `1 → 3`, `2 → 4`, `3 → 4`.

## 2) Image-generation prompt

Create a dark-slate chalkboard teaching diagram with subtle chalk texture and
large, high-contrast handwritten typography. Arrange four bubbles
left-to-right with a branch from the first bubble into the second and third,
then merge into the fourth. Bubble 1 title “ONE LOAS BURST” with “Fixed KH,
KW, CIN”, “16 consecutive COUT weights”, “Base unit is 16 B”. Bubble 2 title
“COUT ONLY” with “Keep one CIN per line”, “32 B reaches 32 COUT”, “64 B
reaches 64 COUT”. Bubble 3 title “CIN × COUT” with “Keep each COUT run
16-wide”, “32 B packs 2 adjacent CIN”, “64 B packs 4 adjacent CIN”. Bubble 4
title “WHERE THEY DIVERGE” with “Identical at 16 B”, “Different at 32/64 B”,
“Same total line capacity”. Use teal chalk for COUT-only, orange and blue
segments for adjacent CIN groups, generous margins, and correct spelling.
Avoid photorealistic people, logos, tiny paragraphs, dense equations, and
cropped text.

## 3) Narration script

LoAS supplies a natural 16-weight unit: one fixed KH, KW, and CIN with 16
consecutive COUT weights. The COUT-only layout spends every extra byte by
continuing farther along the output-channel dimension. A 32-byte line
therefore covers 32 COUT values for one CIN, and a 64-byte line covers 64.
The CIN × COUT layout holds the COUT run at 16 and spends extra capacity on
adjacent input channels. It packs two CIN groups at 32 bytes and four at 64
bytes. Both layouts are identical at 16 bytes and use the same total capacity;
only the dimension receiving the extra spatial coverage changes.

## 4) Alt text

A branched diagram starts with one 16-weight LoAS COUT burst. The COUT-only
branch keeps one input channel and extends to 32 or 64 output channels as the
line grows. The CIN × COUT branch keeps each output-channel run 16-wide and
packs two or four adjacent input channels. The branches are identical at 16
bytes and diverge at 32 and 64 bytes.
