# Optional homepage meter card

The editor works without a card. To embed one on an existing private site,
proxy PiNuke under `/pinuke/` on the **same origin** as that site's homepage.
Load `/pinuke/pip.css`, include `<div data-pinuke-pip hidden></div>` in an area
you allocate, then load `/pinuke/pip.js` as a module. It mounts automatically.

`examples/homepage.html` contains only a generic integration fragment. It is
not a replacement homepage or installer. The default fragment uses its own
wrapper and does not alter existing content. Review placement locally before
adding it to a site. No household-specific page assets or patcher are included.

The card starts hidden, appears after real identity confirmation and disappears
on sustained unavailable state. It never leaves a permanent offline card. The
editor route itself remains available. Clicking the card opens a full-page
dialog; π and Escape ask the editor to return, protecting pending edits and
transactions. Meter viewing resumes after returning.

## Optional companion-card layout

For a paired layout, load `/pinuke/pip-zone.css` **only when you intentionally
use its expected structure** inside a positioned anchor:

```html
<div class="my-pip-anchor" style="position:relative">
  <!-- Existing content remains above this allocated lower zone. -->
  <div data-pinuke-zone>
    <div class="pinuke-pip-pair">
      <section id="pip-card">Your existing companion card</section>
      <div data-pinuke-pip hidden></div>
    </div>
  </div>
</div>
```

These rules intentionally change the **outer** companion card's positioning and
width within the wrapper. Its internal design/player logic is not supplied by
PiNuke. The optional zone is positioned below its anchor; allocate space for it
and review overlap/scrolling on your own page. All selectors are scoped under
`[data-pinuke-zone]`.

At a zone width of at least `48.5rem` (776 px with a 16 px root font), the pair
centers: companion card up to 600 px, minimum 460 px, PiNuke 300 px, 16 px gap.
Below that width it stacks: companion up to 600 px and PiNuke up to 380 px,
each capped to the available width. A lone active card centers.
Do not assume the 776 px threshold is the viewport width: it is the container
width, and depends on root font size. Companion activity visibility is owned
by the embedding site; PiNuke only manages its own availability.

Keep other dialogs outside this wrapper. Preserve existing page/player behavior,
and avoid global framing or style changes to accommodate this card.
