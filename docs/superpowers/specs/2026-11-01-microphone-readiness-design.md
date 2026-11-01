# Microphone readiness

Continue the user's authorized Windows microphone/Hinglish reliability and inline
settings work. Preserve Windows/PyQt and local multilingual Whisper.

The current recorder uses only the system default input, conflates all OS errors
with missing hardware, and cannot expose signal level before a real capture.

Approaches considered: keep the OS default and provide external troubleshooting;
add input selection and a local test in existing Capture settings. Use the latter
as an implementation choice: users can diagnose the actual production recorder
without saving a screenshot or contacting an agent. No separate settings dialog.

Select System default or an enumerated input, save its name + host API rather
than a volatile PortAudio index, and resolve it each recording. Missing or
ambiguous saved inputs fail visibly rather than silently switching microphones.
An explicit refresh enumerates inputs in a worker; it never records.

An explicit microphone test records for at most 10 seconds after opening, with
Stop and Cancel, real level feedback and the locally recognized transcript.
It uses the current language selection, including automatic Hindi/English.
The transcript is plain text and remains in the panel; no capture/agent/clipboard
or persisted audio is created. Hide/close/settings navigation and Quit cancel
the test. Starting a normal capture cancels it; active captures block testing.

Production and test recorders share device ownership. Generation guards suppress
stale audio/phase/result events. Digital silence must not become invented words;
quiet nonzero input is not rejected by a heuristic speech threshold. Opening,
recording and local transcription have distinct feedback. Distinguish missing
runtime, unavailable device, permission denial and stream failure.

No claim of physical microphone or Hinglish accuracy follows from synthetic
tests or inventory. The inline test enables the real Windows user to assess
their own microphone and mixed speech. Preserve existing settings and captures.
