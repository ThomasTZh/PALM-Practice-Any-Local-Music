# PALM — product goals

PALM (Practice Any Local Music) is a private, local practice studio. It turns a
recording the user already owns into a reliable practice room: the song, the
bass part, the musical grid, and the practice controls all stay on the user's
computer.

## What the finished product must do

1. **Open and play real music reliably.** The user can bring a normal audio or
   video file, see its waveform, seek, and play it without setup rituals or
   surprises.

2. **Make the bass easy to hear and control.** The user can separate the bass
   from the rest of the mix and adjust the bass, the other instruments, and the
   overall balance while practising.

3. **Slow down and repeat without changing pitch.** The user can practise a
   difficult passage at any practical speed and loop it cleanly.

4. **Follow the music, not just the clock.** Bars, beats, tempo, and meter line
   up with what the user hears. The metronome and count-in give a dependable
   reference. When the automatic reading is wrong, the user can correct it and
   the rest of the practice state follows the correction.

5. **Support a complete practice session.** The user can select a section,
   create a loop, choose a count-in, set a speed, practise, and return later
   without losing work.

6. **Work offline and remain portable.** A project can be saved, moved, and
   reopened on another machine without the original recordings, model files,
   or an internet connection. Practice behaviour survives the move.

7. **Be trustworthy under real use.** Long songs and long sessions do not
   stutter, drift, lose timing, or exhaust memory. Failures are explained in
   plain language and leave existing work intact.

8. **Keep the user in control of their data.** No account, no cloud upload, no
   hidden network access, and no vendor lock-in for the user's music.

9. **Be measured, not assumed.** Beat, downbeat, tempo, and meter quality are
   measured on realistic material. Practice timing is verified, not inferred
   from the fact that the controls exist.

10. **Be usable first on Firefox on Linux.** The core practice path must work
   reliably there before expanding to other browsers and platforms.

## What the user should be able to say

> “I opened one of my songs, removed or lowered the bass, looped the difficult
> part, slowed it down, practised with a count-in and a metronome that matched
> the song, and came back the next day to the same project — all offline.”

## Out of scope for the current product

- Accounts, cloud sync, sharing, or multi-user collaboration.
- Mobile applications and non-Linux platforms.
- Downloading music from streaming services.
- Automatic bass transcription, harmony analysis, or score generation as a
  finished feature (possible later, not required for the practice product).

## Definition of done

The product is done for a release when the five supplied recordings can each go
through the complete practice path on Firefox in one sitting, the measured
musical and timing accuracy meets the stated acceptance thresholds, portable
projects reopen offline, and the remaining known limitations are documented
rather than hidden.
