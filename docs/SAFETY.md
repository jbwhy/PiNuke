# Editing behavior

Editing is off until `--enable-edits` is passed. Turning it on does not itself
send a DSP setter. Read the amplifier, stage changes, and click Apply explicitly;
pressing Enter in an input does not submit settings.

Apply checks origin, JSON schema, a current read revision, fresh device identity,
and full DSP state. It writes a persistent before-state/requested-change record
before sending changed groups. It queries each changed group and performs a
full read afterward. Comparisons allow float32 roundoff; untouched fields retain
their original values. Read/Apply and telemetry share a serialized USB lock.

If validation, state, identity, or audit preflight fails, setters are not sent.
If a later step fails, processing stops without retry or automatic restoration.
Some changes may already have reached the amplifier. Read again and inspect
the audit outcome before another edit. Applying multiple groups is not atomic.

Bounds are application validation inherited from the client, not measured
hardware limits or recommended tuning. Hardware clamping causes verification
failure. Physical level knobs, presets, amp mode/name, and reported gain/mute
are outside the editor's write scope.

Keep before-state and outcome records private. Export omits preset slots and
cannot be imported as a full amp restore. Pause playback before settings changes.
